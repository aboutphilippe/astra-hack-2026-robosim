"""Chess rules, conservative observation matching, and ordered piece transfers.

This module never commands hardware. Positions are nominal scene coordinates;
measured board-to-robot calibration is required before using them on the arm.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import chess

PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}
SQUARE_NAMES = frozenset(chess.SQUARE_NAMES)
DEFAULT_BOARD = {
    "square_size_m": 0.0381,
    "origin_m": [-0.1524, 0.08, 0.0254],
    "yaw_rad": 0.0,
}
DEFAULT_CAPTURES = {
    "origin_m": [-0.225, 0.10, 0.0254],
    "spacing_m": 0.033,
    "columns": 2,
    "capacity": 32,
}


def _vector3(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three coordinates in metres")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def square_position(square: str, config: dict | None = None) -> list[float]:
    """Nominal square center; origin is the outer a1 playing-grid corner.

    White's back rank is a1–h1. The camera's default display puts a1 at the
    top-left; this does not change this metric board coordinate convention.
    """
    settings = {**DEFAULT_BOARD, **(config or {}).get("board", {})}
    index = chess.parse_square(square)
    size = float(settings["square_size_m"])
    yaw = float(settings.get("yaw_rad", 0.0))
    if not math.isfinite(size) or size <= 0 or not math.isfinite(yaw):
        raise ValueError("Board square size must be positive and yaw finite")
    origin = _vector3(settings["origin_m"], "board.origin_m")
    x, y = (chess.square_file(index) + 0.5) * size, (chess.square_rank(index) + 0.5) * size
    c, s = math.cos(yaw), math.sin(yaw)
    return [origin[0] + c * x - s * y, origin[1] + s * x + c * y, origin[2]]


class ChessGame:
    """One game and its capture-tray allocation; simulation is the default."""

    def __init__(self, config: dict | None = None):
        self.config = deepcopy(config or {})
        self.capture_config = {**DEFAULT_CAPTURES, **self.config.get("captures", {})}
        self.capture_config["origin_m"] = _vector3(self.capture_config["origin_m"], "captures.origin_m")
        spacing = float(self.capture_config["spacing_m"])
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError("Capture spacing must be positive")
        for key in ("capacity", "columns"):
            value = self.capture_config[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Capture {key} must be a positive integer")
        self.board = chess.Board()
        self.captured_pieces: list[dict] = []
        # Validate nominal board geometry before accepting commands.
        square_position("a1", self.config)

    def pieces(self) -> dict[str, dict]:
        return {
            chess.square_name(square): {
                "piece": PIECE_NAMES[piece.piece_type],
                "color": "white" if piece.color else "black",
                "symbol": piece.symbol(),
                "position_m": square_position(chess.square_name(square), self.config),
            }
            for square, piece in sorted(self.board.piece_map().items())
        }

    def legal_moves(self) -> list[str]:
        return sorted(move.uci() for move in self.board.legal_moves)

    def state(self) -> dict:
        outcome = self.board.outcome(claim_draw=True)
        return {
            "fen": self.board.fen(),
            "turn": "white" if self.board.turn else "black",
            "pieces": self.pieces(),
            "legal_moves": self.legal_moves(),
            "in_check": self.board.is_check(),
            "game_over": outcome is not None,
            "result": outcome.result() if outcome else None,
            "capture_slots_used": len(self.captured_pieces),
            "capture_capacity": self.capture_config["capacity"],
            "captured_pieces": deepcopy(self.captured_pieces),
            "move_history": [move.uci() for move in self.board.move_stack],
        }

    def reset(self, fen: str | None = None) -> dict:
        board = chess.Board(fen) if fen else chess.Board()
        if not board.is_valid():
            raise ValueError("FEN is not a valid chess position")
        self.board = board
        self.captured_pieces.clear()
        return self.state()

    def _move(self, uci: str) -> chess.Move:
        try:
            move = chess.Move.from_uci(uci)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Move must use UCI notation, for example e2e4") from exc
        if move not in self.board.legal_moves:
            raise ValueError(f"Illegal move: {uci}")
        return move

    def _square_location(self, square: int) -> dict:
        name = chess.square_name(square)
        return {"square": name, "position_m": square_position(name, self.config)}

    def capture_position(self, slot: int) -> list[float]:
        if not 0 <= slot < self.capture_config["capacity"]:
            raise ValueError("Capture tray is full; clear and reconcile the tray before continuing")
        origin = self.capture_config["origin_m"]
        columns = self.capture_config["columns"]
        spacing = float(self.capture_config["spacing_m"])
        return [origin[0] + (slot % columns) * spacing, origin[1] + (slot // columns) * spacing, origin[2]]

    def plan_move(self, uci: str) -> dict:
        """Predict transfers without modifying board state or reserving tray slots."""
        move = self._move(uci)
        piece = self.board.piece_at(move.from_square)
        assert piece is not None
        transfers = []

        def transfer(moving: chess.Piece, source: int, destination: dict, role: str) -> dict:
            return {
                "piece": PIECE_NAMES[moving.piece_type],
                "symbol": moving.symbol(),
                "color": "white" if moving.color else "black",
                "source": self._square_location(source),
                "destination": destination,
                "role": role,
            }

        if self.board.is_capture(move):
            victim_square = move.to_square
            if self.board.is_en_passant(move):
                victim_square += -8 if piece.color == chess.WHITE else 8
            victim = self.board.piece_at(victim_square)
            assert victim is not None
            slot = len(self.captured_pieces)
            transfers.append(transfer(victim, victim_square, {
                "capture_slot": slot, "position_m": self.capture_position(slot),
            }, "capture"))
        transfers.append(transfer(piece, move.from_square, self._square_location(move.to_square), "move"))
        if self.board.is_castling(move):
            rank = chess.square_rank(move.from_square)
            kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
            rook_from = chess.square(7 if kingside else 0, rank)
            rook_to = chess.square(5 if kingside else 3, rank)
            rook = self.board.piece_at(rook_from)
            assert rook is not None
            transfers.append(transfer(rook, rook_from, self._square_location(rook_to), "castle_rook"))
        return {
            "uci": move.uci(),
            "san": self.board.san(move),
            "fen_before": self.board.fen(),
            "transfers": transfers,
            "promotion": {
                "required": True,
                "manual_swap_required": True,
                "square": chess.square_name(move.to_square),
                "piece": PIECE_NAMES[move.promotion],
                "color": "white" if piece.color else "black",
            } if move.promotion else None,
        }

    def apply_move(self, uci: str) -> dict:
        plan = self.plan_move(uci)
        self.board.push_uci(uci)
        self.captured_pieces.extend(deepcopy(t) for t in plan["transfers"] if t["role"] == "capture")
        return {"plan": plan, "state": self.state()}

    def infer_move(
        self, observed: Mapping[str, str | None], confidence: float = 1.0,
        min_confidence: float = 0.9,
    ) -> dict:
        """Match a complete color-occupancy observation against legal successors.

        Every square must be present. '?' means occluded, never empty. An
        observation compatible with the current board cannot establish a move.
        Color-only observations cannot disambiguate promotion piece choices.
        """
        def result(status: str, reason: str, candidates: list[str] | None = None) -> dict:
            candidates = candidates or []
            return {"status": status, "reason": reason, "uci": candidates[0] if status == "accepted" else None, "candidates": candidates}

        if not isinstance(observed, Mapping) or set(observed) != SQUARE_NAMES:
            return result("invalid", "Provide all 64 square names; use '?' for occluded squares")
        if any(value not in ("white", "black", None, "?") for value in observed.values()):
            return result("invalid", "Occupancy must be 'white', 'black', null, or '?'")
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return result("invalid", "Confidence must be a finite number between zero and one")
        if not isinstance(min_confidence, (int, float)) or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            return result("invalid", "Minimum confidence must be between zero and one")
        if confidence < min_confidence:
            return result("low_confidence", "Observation confidence is below the acceptance threshold")

        def matches(board: chess.Board) -> bool:
            for square, occupancy in observed.items():
                if occupancy == "?":
                    continue
                piece = board.piece_at(chess.parse_square(square))
                actual = ("white" if piece.color else "black") if piece else None
                if occupancy != actual:
                    return False
            return True

        if matches(self.board):
            return result("unchanged", "Visible squares do not prove a change from the current position")
        candidates = []
        for move in sorted(self.board.legal_moves, key=lambda m: m.uci()):
            successor = self.board.copy(stack=False)
            successor.push(move)
            if matches(successor):
                candidates.append(move.uci())
        if not candidates:
            return result("invalid", "Observation does not match a legal single move; wait for hands to clear and reobserve")
        if len(candidates) > 1:
            return result("ambiguous", "Multiple legal moves match visible occupancy; another observation is required", candidates)
        return result("accepted", "Exactly one legal move matches the observation", candidates)

    def choose_robot_move(self) -> str | None:
        """Deterministic two-ply material/position search; no external engine."""
        if self.board.is_game_over(claim_draw=True):
            return None
        side = self.board.turn
        values = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}

        def evaluate(board: chess.Board) -> float:
            outcome = board.outcome(claim_draw=True)
            if outcome:
                return 0 if outcome.winner is None else (100000 if outcome.winner == side else -100000)
            score = 0.0
            for square, piece in board.piece_map().items():
                file, rank = chess.square_file(square), chess.square_rank(square)
                advancement = rank if piece.color else 7 - rank
                center = 3.5 - (abs(file - 3.5) + abs(rank - 3.5)) / 2
                positional = 5 * advancement if piece.piece_type == chess.PAWN else 0
                if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                    positional += 10 * center
                score += (values[piece.piece_type] + positional) * (1 if piece.color == side else -1)
            return score

        best_move, best_score = None, -math.inf
        for move in sorted(self.board.legal_moves, key=lambda m: m.uci()):
            position = self.board.copy(stack=True)
            position.push(move)
            if position.is_game_over(claim_draw=True):
                score = evaluate(position)
            else:
                score = math.inf
                for reply in sorted(position.legal_moves, key=lambda m: m.uci()):
                    position.push(reply)
                    score = min(score, evaluate(position))
                    position.pop()
                    if score <= best_score:
                        break
            if score > best_score:
                best_move, best_score = move.uci(), score
        return best_move
