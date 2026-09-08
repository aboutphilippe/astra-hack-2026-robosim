import math

import chess
import pytest
from chessbot.chess_logic import ChessGame, square_position


def occupancy(board):
    return {
        square: ("white" if board.piece_at(chess.parse_square(square)).color else "black")
        if board.piece_at(chess.parse_square(square)) else None
        for square in chess.SQUARE_NAMES
    }


def test_square_positions_use_outer_grid_corner_and_white_rank_one():
    config = {"board": {"origin_m": [1, 2, 3], "square_size_m": 0.04}}
    assert square_position("a1", config) == pytest.approx([1.02, 2.02, 3])
    assert square_position("h8", config) == pytest.approx([1.30, 2.30, 3])
    config["board"]["yaw_rad"] = math.pi / 2
    assert square_position("a1", config) == pytest.approx([0.98, 2.02, 3])
    assert ChessGame().pieces()["a1"]["color"] == "white"
    assert ChessGame().pieces()["h2"]["piece"] == "pawn"


def test_capture_is_first_and_preview_does_not_consume_slots():
    game = ChessGame()
    game.apply_move("e2e4")
    game.apply_move("d7d5")
    fen = game.board.fen()
    first = game.plan_move("e4d5")
    second = game.plan_move("e4d5")
    assert first == second
    assert game.board.fen() == fen
    assert game.state()["capture_slots_used"] == 0
    capture, movement = first["transfers"]
    assert capture["role"] == "capture"
    assert capture["source"]["square"] == "d5"
    assert capture["destination"]["capture_slot"] == 0
    assert movement["source"]["square"] == "e4"
    game.apply_move("e4d5")
    next_plan = game.plan_move("d8d5")
    assert next_plan["transfers"][0]["destination"]["capture_slot"] == 1
    assert next_plan["transfers"][0]["destination"]["position_m"] != capture["destination"]["position_m"]


def test_en_passant_removes_actual_victim_square():
    game = ChessGame()
    for move in ["e2e4", "a7a6", "e4e5", "d7d5"]:
        game.apply_move(move)
    plan = game.plan_move("e5d6")
    assert plan["transfers"][0]["source"]["square"] == "d5"
    assert plan["transfers"][1]["destination"]["square"] == "d6"
    game.apply_move("e5d6")
    assert "d5" not in game.pieces()


@pytest.mark.parametrize("move,rook_from,rook_to", [("e1g1", "h1", "f1"), ("e1c1", "a1", "d1")])
def test_castle_moves_rook(move, rook_from, rook_to):
    game = ChessGame()
    game.reset("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    king, rook = game.plan_move(move)["transfers"]
    assert king["piece"] == "king"
    assert rook["role"] == "castle_rook"
    assert rook["source"]["square"] == rook_from
    assert rook["destination"]["square"] == rook_to


def test_promotion_requires_manual_swap_and_color_observation_is_ambiguous():
    game = ChessGame()
    game.reset("7k/P7/8/8/8/8/8/7K w - - 0 1")
    plan = game.plan_move("a7a8q")
    assert plan["promotion"]["manual_swap_required"]
    assert plan["promotion"]["piece"] == "queen"
    assert plan["transfers"][0]["piece"] == "pawn"
    observed_board = game.board.copy()
    observed_board.push_uci("a7a8q")
    inferred = game.infer_move(occupancy(observed_board))
    assert inferred["status"] == "ambiguous"
    assert len(inferred["candidates"]) == 4


def test_inference_accepts_only_a_single_legal_change_without_mutation():
    game = ChessGame()
    observed_board = game.board.copy()
    observed_board.push_uci("e2e4")
    observed = occupancy(observed_board)
    assert game.infer_move(observed)["uci"] == "e2e4"
    assert game.board.fen() == chess.STARTING_FEN
    assert game.infer_move(observed, confidence=0.5)["status"] == "low_confidence"
    assert game.infer_move(occupancy(game.board))["status"] == "unchanged"
    observed.pop("a1")
    assert game.infer_move(observed)["status"] == "invalid"


def test_occlusion_never_counts_as_empty_or_as_evidence_of_a_move():
    game = ChessGame()
    observed = occupancy(game.board)
    observed["e2"] = "?"
    observed["e3"] = "?"
    observed["e4"] = "?"
    assert game.infer_move(observed)["status"] == "unchanged"
    observed["e2"] = None
    assert game.infer_move(observed)["status"] == "ambiguous"
    assert game.infer_move(observed)["candidates"] == ["e2e3", "e2e4"]
    observed["e5"] = "white"
    assert game.infer_move(observed)["status"] == "invalid"


def test_illegal_move_and_full_capture_tray_leave_state_unchanged():
    game = ChessGame({"captures": {"capacity": 1}})
    with pytest.raises(ValueError, match="Illegal"):
        game.apply_move("e2e5")
    for move in ["e2e4", "d7d5", "e4d5"]:
        game.apply_move(move)
    before = game.state()
    with pytest.raises(ValueError, match="full"):
        game.apply_move("d8d5")
    assert game.state() == before
    game.reset()
    assert game.state()["capture_slots_used"] == 0


def test_engine_is_deterministic_legal_and_finds_mate():
    game = ChessGame()
    fen = game.board.fen()
    first = game.choose_robot_move()
    assert first == game.choose_robot_move()
    assert first in game.legal_moves()
    assert game.board.fen() == fen
    game.reset("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
    move = game.choose_robot_move()
    game.apply_move(move)
    assert game.board.is_checkmate()
    assert game.choose_robot_move() is None
