export type Vec3 = [number, number, number]
export type Piece = { square: string; piece: string; color: 'white' | 'black'; position: Vec3; height_m?: number | null }
export type Geom = {
  name: string
  type: string | number
  position: Vec3
  quaternion: [number, number, number, number]
  size: number[]
  color: number[]
  mesh?: string
}
export type Waypoint = { phase: string; target: Vec3; qpos: number[]; error_m: number }
export type RobotConfig = {
  base_position_m?: Vec3
  base_yaw_rad?: number
  pose_measured?: boolean
  placement?: {
    mode: string
    edge: string
    along_fraction: number
    base_origin_offset_m: number
    elevation_above_board_bottom_m: number
    measured: boolean
    source: string
  }
  [key: string]: unknown
}
export type LabState = {
  mode: string
  fen: string
  turn: 'white' | 'black'
  status: string
  game_over?: boolean
  in_check?: boolean
  legal_moves: string[]
  pieces: Piece[]
  captures: { piece: string; color: 'white' | 'black'; position: Vec3 }[]
  last_move: string | null
  events: { time: string | number; message: string }[]
  config: {
    board: { square_size_m: number; origin_m: Vec3; border_m: number; height_m: number; yaw_rad?: number }
    robot: RobotConfig
    [key: string]: unknown
  }
  calibration: { status: string; [key: string]: unknown }
  simulation: { joints: { name: string; position: number; min: number; max: number }[]; tcp: Vec3; geoms: Geom[] }
  plan: null | { uci: string; status: string; active_phase?: string; waypoints: Waypoint[]; warnings: string[] }
  server?: { revision?: string; name?: string; [key: string]: unknown }
}

export const FILES = 'abcdefgh'
export const SYMBOLS: Record<string, string> = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚' }
export const PIECE_NAMES: Record<string, string> = { p: 'pawn', n: 'knight', b: 'bishop', r: 'rook', q: 'queen', k: 'king' }
export function pieceCode(piece: string) {
  const names: Record<string, string> = { pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k' }
  return names[piece.toLowerCase()] || piece.toLowerCase()
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function api<T = unknown>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, body === undefined ? { credentials: 'same-origin' } : {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const result = await response.json().catch(() => ({ detail: `Server returned ${response.status}` }))
  if (!response.ok) throw new ApiError(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result.error || result), response.status)
  return result as T
}
