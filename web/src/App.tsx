import { Component, lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Check, ChevronDown, ChevronRight, CircleHelp, Crosshair, Expand, Eye, Focus, Layers3, LoaderCircle, Maximize2, MoveUpRight, Pause, Play, Radio, RefreshCw, RotateCcw, ScanLine, Settings2, ShieldCheck, SlidersHorizontal, Unplug, X } from 'lucide-react'
import { api, ApiError, FILES, PIECE_NAMES, SYMBOLS, pieceCode } from './types'
import type { LabState, Vec3 } from './types'
import { SharedControlBar, TeamLogin, useSharedSession } from './shared'

const Scene = lazy(() => import('./Scene'))

class CanvasBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <div className="canvas-message"><Layers3 size={36} /><strong>3D rendering unavailable</strong><span>Enable WebGL in your browser to view the digital twin. The chess controls are still available.</span></div> : this.props.children }
}

function RobotMark({ size = 24 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M7 26h18M11 26v-5l5-7m0 0-4-7 6-3 6 10-8 0Zm8 0 2 5-3 4m-7-9-5 7" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" /><circle cx="16" cy="14" r="3" fill="currentColor"/><circle cx="11" cy="21" r="2.5" fill="currentColor"/></svg>
}

function formatTime(time: string | number) {
  const date = new Date(typeof time === 'number' && time < 10_000_000_000 ? time * 1000 : time)
  return Number.isNaN(date.getTime()) ? String(time).slice(0, 8) : date.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Chessboard({ state, selected, onSquare, disabled }: { state: LabState; selected: string | null; onSquare: (square: string) => void; disabled: boolean }) {
  const pieces = new Map(state.pieces.map(piece => [piece.square, piece]))
  const targets = new Set(state.legal_moves.filter(move => move.startsWith(selected || ' ')).map(move => move.slice(2, 4)))
  return <div className="camera-board-wrap">
    <div className="files-labels">{FILES.split('').map(file => <span key={file}>{file}</span>)}</div>
    <div className="rank-labels">{Array.from({ length: 8 }, (_, i) => <span key={i}>{i + 1}</span>)}</div>
    <div className="chessboard" role="grid" aria-label="Chessboard, a1 in the upper left. White starts on ranks 1 and 2.">
      {Array.from({ length: 64 }, (_, i) => {
        const file = i % 8, rank = Math.floor(i / 8), square = `${FILES[file]}${rank + 1}`, piece = pieces.get(square)
        const code = piece ? pieceCode(piece.piece) : ''
        const lastMove = state.last_move?.slice(0, 2) === square || state.last_move?.slice(2, 4) === square
        return <button key={square} role="gridcell" className={`square ${(file + rank) % 2 === 0 ? 'dark' : 'light'} ${selected === square ? 'selected' : ''} ${lastMove ? 'last-move' : ''} ${targets.has(square) && piece ? 'capture-target' : ''}`} onClick={() => onSquare(square)} disabled={disabled} aria-label={`${square}${piece ? `, ${piece.color} ${PIECE_NAMES[code] || code}` : ', empty'}${targets.has(square) ? ', legal destination' : ''}`} aria-selected={selected === square}>
          {piece && <span className={`chess-piece ${piece.color}`} aria-hidden="true">{SYMBOLS[code] || code}</span>}
          {targets.has(square) && !piece && <span className="move-dot" />}
          {square === 'a1' && <span className="a1-label">a1</span>}
        </button>
      })}
    </div>
    <div className="board-corner tl" /><div className="board-corner tr" /><div className="board-corner bl" /><div className="board-corner br" />
  </div>
}

function Calibration({ state, canMutate, onClose, onRefresh, reportError }: { state: LabState | null; canMutate: boolean; onClose: () => void; onRefresh: () => Promise<void>; reportError: (message: string) => void }) {
  const [corners, setCorners] = useState<[number, number][]>([])
  const [cornerText, setCornerText] = useState(['', '', '', ''])
  const [frameSize, setFrameSize] = useState<[number, number]>([640, 480])
  const [frame, setFrame] = useState<string | null>(null)
  const [working, setWorking] = useState(false)
  const [message, setMessage] = useState('')
  const [calibrationError, setCalibrationError] = useState('')
  const [manual, setManual] = useState(false)
  const [size, setSize] = useState((state?.config.board.square_size_m ?? .0381) * 1000)
  const [origin, setOrigin] = useState<Vec3>((state?.config.board.origin_m || [-.1524, .08, .0254]).map(v => v * 1000) as Vec3)
  const labels = ['a1 outer', 'h1 outer', 'h8 outer', 'a8 outer']
  const perform = async (action: () => Promise<void>) => {
    if (!canMutate) { setCalibrationError('Take control of the shared session before changing calibration.'); return }
    setWorking(true); setMessage(''); setCalibrationError('')
    try { await action(); await onRefresh() } catch (error) { const message = error instanceof Error ? error.message : 'Calibration failed'; setCalibrationError(message); reportError(message) } finally { setWorking(false) }
  }
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className="calibration-modal" role="dialog" aria-modal="true" aria-labelledby="calibration-title">
      <header className="modal-header"><div><div className="eyebrow">REAL WORLD → DIGITAL TWIN</div><h2 id="calibration-title">One board. Both worlds.</h2><p>Measure the board with the overhead RGB-D camera.</p></div><button className="icon-button" aria-label="Close calibration" onClick={onClose}><X size={21} /></button></header>
      <div className="calibration-body">
        {!canMutate && <p className="calibration-readonly"><Eye size={16} /> Read-only view. An operator must take control to capture frames or update calibration.</p>}
        <div className="calibration-steps"><div className="calibration-step"><span>01</span><div><strong>Find the White back rank</strong><p>Identify a1–h1 in the original camera image. Keep the image unmirrored and clear hands from the board.</p></div></div><div className="calibration-step"><span>02</span><div><strong>Capture an RGB-D frame</strong><p>Gemini 336 supplies color, depth, and camera intrinsics through the Orbbec SDK.</p></div></div><div className="calibration-step"><span>03</span><div><strong>Select four playing-grid corners</strong><p>Click a1 → h1 → h8 → a8 in any image orientation, excluding the border. Depth determines the metric scale.</p></div></div></div>
        <div className="calibration-capture">
          <div className="capture-toolbar"><span><ScanLine size={16} /> OVERHEAD RGB-D</span><button className="small-button" disabled={!state || working || !canMutate} onClick={() => perform(async () => { await api('camera/capture', { camera: 'top' }); setFrame(`/api/camera/top.jpg?t=${Date.now()}`); setCorners([]); setCornerText(['', '', '', '']) })}>{working ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />} Capture frame</button></div>
          <div className={`capture-image ${frame ? 'has-frame' : ''}`}>
            {frame ? <><img src={frame} alt="Latest unmirrored Orbbec top camera frame. Click a1, h1, h8, then a8 playing-grid corners." onLoad={event => setFrameSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])} onError={() => { setFrame(null); setCalibrationError('The top camera frame could not be loaded.') }} onClick={event => { if (corners.length >= 4) return; const image = event.currentTarget, rect = image.getBoundingClientRect(); const next: [number, number] = [Math.round((event.clientX - rect.left) / rect.width * image.naturalWidth), Math.round((event.clientY - rect.top) / rect.height * image.naturalHeight)]; setCornerText(old => old.map((value, i) => i === corners.length ? next.join(', ') : value)); setCorners([...corners, next]) }} />{corners.map((corner, i) => corner && <span key={i} className="camera-corner-marker" style={{ left: `${corner[0] / frameSize[0] * 100}%`, top: `${corner[1] / frameSize[1] * 100}%` }}>{i + 1}</span>)}{corners.length < 4 && <span className="capture-prompt">Click {labels[corners.length]} corner</span>}</> : <><Focus size={36} strokeWidth={1.2} /><strong>No camera frame yet</strong><span>Connect Gemini 336 and capture a frame.<br />A live hardware connection is required.</span></>}
          </div>
          <div className="corner-inputs">{labels.map((label, i) => <div key={label} className={corners[i] ? 'complete' : ''}><span>{corners[i] ? <Check size={12} /> : i + 1}</span><label>{label}<input aria-label={`${label} pixel coordinates x,y`} placeholder="x, y" value={cornerText[i]} onChange={event => { const value = event.target.value; setCornerText(old => old.map((text, index) => i === index ? value : text)); const parts = value.split(','); const values = parts.map(Number); if (parts.length === 2 && parts.every(part => part.trim()) && values.every(Number.isFinite)) setCorners(old => { const next = [...old]; next[i] = [values[0], values[1]]; return next }) }} /></label></div>)}</div>
          <div className="capture-actions"><button className="text-button" onClick={() => { setCorners([]); setCornerText(['', '', '', '']) }}>Clear corners</button><button className="primary-button" disabled={!canMutate || working || corners.length !== 4 || ![0, 1, 2, 3].every(i => corners[i] && /^\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*$/.test(cornerText[i])) || !state} onClick={() => perform(async () => { await api('calibration/measure', { corners_px: corners }); setMessage('RGB-D measurement saved. Confirm the robot-to-board transform before physical motion.') })}><Crosshair size={16} /> Measure from depth</button></div>
        </div>
        {calibrationError && <div className="calibration-error" role="alert"><Unplug size={16} />{calibrationError}</div>}
        {message && <div className="success-note"><Check size={16} />{message}</div>}
        <div className="calibration-note"><ShieldCheck size={19} /><p>Camera measurements establish board scale and pose. The robot base transform and piece grasp heights still need verification before hardware movement.</p></div>
        <button className="advanced-toggle" onClick={() => setManual(!manual)} aria-expanded={manual}><SlidersHorizontal size={15} /> Simulation geometry <ChevronDown size={15} className={manual ? 'rotate' : ''} /></button>
        {manual && <div className="manual-fields"><p>Sample values for simulation. Applying these values resets the game; they do not calibrate the physical robot.</p><div className="geometry-fields"><label>Square width · mm<input type="number" min="15" max="80" step=".1" value={size} onChange={event => setSize(Number(event.target.value))} /></label>{['X', 'Y', 'Z'].map((axis, i) => <label key={axis}>Origin {axis} · mm<input type="number" step=".1" value={origin[i]} onChange={event => setOrigin(old => old.map((v, index) => index === i ? Number(event.target.value) : v) as Vec3)} /></label>)}</div><button className="secondary-button" disabled={!canMutate || working || !state || size <= 0} onClick={() => perform(async () => { await api('config/board', { square_size_m: size / 1000, origin_m: origin.map(v => v / 1000) }); setMessage('Simulation geometry updated. Game reset.') })}>Apply & reset simulation <ArrowRight size={15} /></button></div>}
      </div>
    </section>
  </div>
}

export default function App() {
  const session = useSharedSession()
  const [state, setState] = useState<LabState | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [working, setWorking] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<'orbit' | 'top'>('orbit')
  const [showPath, setShowPath] = useState(true)
  const [calibrating, setCalibrating] = useState(false)
  const [demo, setDemo] = useState(false)
  const [help, setHelp] = useState(false)
  const [showJoints, setShowJoints] = useState(false)
  const scenePanel = useRef<HTMLElement>(null)
  const mounted = useRef(true)
  const sessionKey = `${session.mode}:${session.member?.id || ''}`
  const sessionKeyRef = useRef(sessionKey)
  sessionKeyRef.current = sessionKey
  const refresh = useCallback(async () => {
    const key = sessionKeyRef.current
    if (key === 'checking:' || key === 'shared:') return
    try { const next = await api<LabState>('state'); if (mounted.current && key === sessionKeyRef.current) { setState(next); setConnected(true) } }
    catch (error) {
      if (!mounted.current || key !== sessionKeyRef.current) return
      if (error instanceof ApiError && error.status === 401) { session.requireLogin(); setState(null); setDemo(false); setCalibrating(false) }
      else { setConnected(false); if (error instanceof ApiError && error.status !== 503) setError(`Engine request failed (${error.status}). ${error.message}`) }
    }
  }, [session.requireLogin])
  useEffect(() => {
    mounted.current = true
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 400)
    return () => { mounted.current = false; clearInterval(timer) }
  }, [refresh, sessionKey])
  useEffect(() => {
    if (!session.canMutate) { setDemo(false); setSelected(null) }
    if (session.mode === 'shared' && !session.member) { setState(null); setCalibrating(false) }
  }, [session.canMutate, session.mode, session.member])

  const busyStatus = state ? /executing|moving|planning|thinking|busy/.test(state.status.toLowerCase()) : false
  const busy = working || busyStatus
  const finished = state ? state.game_over || /checkmate|stalemate|game.over|draw/.test(state.status.toLowerCase()) || state.legal_moves.length === 0 : false
  const act = useCallback(async (path: string, body: unknown = {}) => {
    if (!session.canMutate) { setError('Take control of the shared session before changing the lab.'); return }
    setWorking(true); setError(null); setSelected(null)
    try { await api(path, body); await refresh() }
    catch (error) { setError(error instanceof Error ? error.message : 'Something went wrong'); setDemo(false); if (error instanceof ApiError && error.status === 401) session.requireLogin(); else if (session.mode === 'shared') void session.refreshControl() }
    finally { setWorking(false) }
  }, [refresh, session.canMutate, session.mode, session.requireLogin, session.refreshControl])

  // Polls update the state object frequently; schedule the demo from stable game facts.
  const demoSnapshot = useRef('')
  useEffect(() => { if (state?.status === 'blocked') setDemo(false) }, [state?.status])
  useEffect(() => {
    if (!demo || !state || !connected || !session.canMutate || busy || finished || state.status === 'blocked') return
    const key = state.fen
    if (demoSnapshot.current === key) return
    demoSnapshot.current = key
    const timer = window.setTimeout(() => {
      if (state.turn === 'black') void act('robot', { execute: true })
      else {
        const preferred = ['e2e4', 'g1f3', 'f1c4', 'd2d4', 'b1c3', 'd1e2', 'e1g1', 'c1g5']
        const move = preferred.find(candidate => state.legal_moves.includes(candidate)) || state.legal_moves[0]
        if (move) void act('move', { uci: move })
      }
    }, 750)
    return () => { clearTimeout(timer); demoSnapshot.current = '' }
  }, [demo, state?.fen, connected, session.canMutate, busy, finished, act])

  const onSquare = (square: string) => {
    if (!state || busy || state.turn !== 'white' || demo || !connected || !session.canMutate || finished) return
    const ownPiece = state.pieces.find(piece => piece.square === square && piece.color === 'white')
    if (selected) {
      const candidate = `${selected}${square}`
      const move = state.legal_moves.includes(candidate) ? candidate : state.legal_moves.includes(`${candidate}q`) ? `${candidate}q` : null
      if (move) { void act('move', { uci: move }); return }
    }
    setSelected(ownPiece && selected !== square ? square : null)
  }

  const fullMove = state ? Number(state.fen.split(' ')[5] || 1) : 1
  const moveNumber = state ? (fullMove - 1) * 2 + (state.turn === 'black' ? 1 : 0) : 0
  const maxError = state?.plan?.waypoints.length ? Math.max(...state.plan.waypoints.map(point => point.error_m)) * 1000 : null
  const title = !connected ? 'A little space to think.' : finished ? 'A game well played.' : busy ? 'Thinking in three dimensions.' : state?.turn === 'black' ? 'Over to you, Nono.' : 'Make your next move.'
  const turnDescription = !connected ? 'Start the local engine to bring your chess lab online.' : demo ? 'Demo running · both sides are playing in simulation.' : finished ? 'The game has ended. Reset the board for another round.' : state?.turn === 'black' ? 'White has moved. Let the robot plan its response.' : 'You play White. Select a piece, then its destination.'

  if (session.mode === 'shared' && !session.member) return <TeamLogin session={session} />

  return <div className="app-shell">
    <aside className="rail"><a className="brand-icon" href="/" aria-label="NONO Chess Lab">n<span>•</span></a><div className="rail-divider" /><button className="rail-button active" aria-label="Chess lab" title="Chess lab"><Layers3 size={21} /></button><button className={`rail-button ${calibrating ? 'active' : ''}`} aria-label="Calibration" title="Calibration" onClick={() => setCalibrating(true)}><ScanLine size={21} /></button><button className={`rail-button ${showJoints ? 'active' : ''}`} aria-label="Toggle robot joints" title="Robot joints" onClick={() => setShowJoints(!showJoints)}><Activity size={21} /></button><div className="rail-bottom"><button className="rail-button" aria-label="How to use this lab" title="How to use this lab" onClick={() => setHelp(!help)}><CircleHelp size={21} /></button><span className="rail-avatar">P</span></div></aside>
    <div className="main-shell">
      <header className="topbar"><div className="wordmark">NONO<span>/</span><span className="wordmark-sub">Chess Lab</span><span className="version-tag">α 0.1</span></div><div className="topbar-right"><span className={`connection ${connected ? 'online' : ''}`}><i />{session.mode === 'checking' ? 'Checking server access…' : connected ? session.mode === 'shared' ? 'Shared server online' : 'Local engine online' : session.mode === 'shared' ? 'Server unavailable' : 'Engine offline'}</span><span className="topbar-divider" /><button className="text-button" onClick={() => setCalibrating(true)}><Settings2 size={16} /> Calibration <ArrowUpRight size={14} /></button></div></header>
      <main>
        {session.mode === 'shared' && <SharedControlBar session={session} revision={session.server?.revision || state?.server?.revision} />}
        {session.mode === 'checking' && session.error && <div className="error-banner" role="alert"><Unplug size={17} /><span>{session.error}</span><button onClick={() => void session.retry()}>Retry</button></div>}
        <div className="page-intro"><div><div className="eyebrow"><span className="tiny-square" /> HUMAN × ROBOT</div><h1>{session.mode === 'shared' && connected && !session.canMutate ? 'A shared view of the game.' : title}</h1><p>{session.mode === 'shared' && !session.canMutate ? 'Follow every move live. The current operator controls this shared session.' : turnDescription}</p></div><div className="intro-actions"><button className="secondary-button reset-button" disabled={!connected || !session.canMutate} onClick={() => { setDemo(false); void act('reset') }}><RotateCcw size={16} /> Reset board</button><button className={`primary-button ${demo ? 'demo-active' : ''}`} disabled={!connected || !session.canMutate || finished} onClick={() => setDemo(!demo)}>{demo ? <Pause size={16} fill="currentColor" /> : <Play size={15} fill="currentColor" />}{demo ? 'Pause demo' : 'Play demo'}</button></div></div>
        {error && <div className="error-banner" role="alert"><Unplug size={17} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)}><X size={16} /></button></div>}
        {state?.plan?.warnings.length ? <details className="plan-warning"><summary><ShieldCheck size={16} /><span>{state.plan.status === 'blocked' ? 'Motion paused — this plan needs review.' : 'Motion plan notes'} <small>{state.plan.warnings.length} {state.plan.warnings.length === 1 ? 'note' : 'notes'}</small></span><ChevronDown size={15} /></summary><ul>{state.plan.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : null}
        {help && <div className="help-banner"><CircleHelp size={20} /><p><strong>From your move to robot motion.</strong> Select a White piece on the overhead board, then a highlighted square. Choose “Play robot move” to plan and animate Black’s reply. Play demo runs both sides. Open Calibration to measure your physical board from an Orbbec RGB-D frame.</p><button className="icon-button" aria-label="Close help" onClick={() => setHelp(false)}><X size={17} /></button></div>}
        <div className="workspace-grid">
          <section className="scene-panel panel" ref={scenePanel} aria-label="MuJoCo digital twin">
            <div className="panel-heading scene-heading"><div className="panel-title"><span className="live-square" /><h2>Digital twin</h2><span className="subtle-label">SO-101</span></div><span className="mode-tag"><span /> SIMULATION</span></div>
            <div className="scene-canvas">
              {state && connected ? <CanvasBoundary><Suspense fallback={<div className="canvas-message"><LoaderCircle className="spin" /><span>Loading digital twin…</span></div>}><Scene state={state} view={view} showPath={showPath} /></Suspense></CanvasBoundary> : <div className="canvas-message offline-scene"><div className="offline-symbol"><RobotMark size={54} /></div><strong>{session.mode === 'shared' ? 'Reconnecting to the shared table.' : 'The lab is ready when you are.'}</strong><span>{session.mode === 'checking' ? 'Checking access to the lab…' : session.mode === 'shared' ? 'The shared engine is temporarily unreachable.' : 'Waiting for the local MuJoCo engine.'}</span>{session.mode === 'local' && <code>uv run python scripts/dev.py</code>}<button className="secondary-button" onClick={() => { if (session.mode === 'checking') void session.retry(); else void refresh() }}><RefreshCw size={15} /> Reconnect</button></div>}
              <div className="scene-overlay-top"><span className="scene-label"><span /> MUJOCO KINEMATICS</span><span className="scene-scale">METRIC SCENE · SAMPLE FIXTURE</span></div>
              <div className="scene-view-controls"><button className={view === 'orbit' ? 'active' : ''} onClick={() => setView('orbit')}><Layers3 size={14} /> Orbit</button><button className={view === 'top' ? 'active' : ''} onClick={() => setView('top')}><Maximize2 size={14} /> Top</button></div>
              <div className="scene-tools"><button className={`icon-button ${showPath ? 'active' : ''}`} title="Toggle motion path" aria-label="Toggle motion path" aria-pressed={showPath} onClick={() => setShowPath(!showPath)}><MoveUpRight size={17} /></button><button className="icon-button" title="Expand digital twin" aria-label="Expand digital twin" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void scenePanel.current?.requestFullscreen().catch(() => setError('Fullscreen is not available in this browser.')) }}><Expand size={17} /></button></div>
              <div className="scene-axis"><svg width="48" height="48" viewBox="0 0 48 48" aria-label="World coordinate axes"><path d="M19 30V8" stroke="#698875" /><path d="m19 30 22 8" stroke="#bd846b" /><path d="m19 30-13 8" stroke="#8796ab" /><circle cx="19" cy="30" r="2.5" fill="#657267" /><text x="16" y="7" fill="#698875">Z</text><text x="40" y="44" fill="#bd846b">X</text><text x="0" y="45" fill="#8796ab">Y</text></svg></div>
              {state?.plan && <div className="plan-chip"><span className={busy ? 'pulse' : ''} /><span>{state.plan.uci.slice(0, 2)} → {state.plan.uci.slice(2, 4)}</span><b>{busy ? 'EXECUTING' : state.plan.status.replaceAll('_', ' ').toUpperCase()}</b></div>}
            </div>
            <div className="scene-footer"><div><span className={`status-dot ${busy ? 'moving' : ''}`} /><strong>{!connected ? 'Engine unavailable' : busy ? 'Simulating robot motion' : 'Robot at rest'}</strong><span className="footer-separator">/</span><span>{!connected ? 'Connect to begin' : 'Grasps unverified'}</span></div><span className="drag-hint">{view === 'orbit' ? 'Drag to orbit · Scroll to zoom' : 'World top view · Scroll to zoom'}</span></div>
          </section>
          <section className="camera-panel panel"><div className="panel-heading"><div className="panel-title"><ScanLine size={17} /><h2>Overhead view</h2></div><span className="small-tag">VIRTUAL</span></div><div className="camera-subheading"><span>Board state</span><span><i className="camera-dot" /> {connected ? 'Engine projection' : 'No signal'}</span></div>
            {state ? <Chessboard state={state} selected={selected} onSquare={onSquare} disabled={!connected || !session.canMutate || busy || state.turn !== 'white' || demo || finished} /> : <div className="empty-board"><ScanLine size={31} /><span>The board appears when<br />the engine is connected.</span></div>}
            <div className="board-caption"><span><span className="white-piece-dot" /> White · ranks 1–2</span><button className="text-button" onClick={() => setCalibrating(true)}>Align camera <ArrowUpRight size={13} /></button></div>
            <div className="turn-card"><span className={`turn-piece ${state?.turn === 'black' ? 'black' : 'white'}`}>{state?.turn === 'black' ? <RobotMark size={22} /> : '♙'}</span><div><strong>{!connected ? 'Waiting for engine' : finished ? 'Game complete' : busy ? 'Planning & moving' : state?.turn === 'white' ? 'Your turn, White' : 'Nono’s turn, Black'}</strong><span>{selected ? `${selected} selected · choose a highlighted square` : state?.turn === 'black' ? 'Ready to plan a move' : 'Select a piece to make your move'}</span></div>{connected && <span className="turn-counter">{String(fullMove).padStart(2, '0')}</span>}</div>
            <button className="robot-move-button" disabled={!connected || !session.canMutate || busy || state?.turn !== 'black' || demo || finished} onClick={() => void act('robot', { execute: true })}>{busy ? <LoaderCircle size={17} className="spin" /> : <RobotMark size={20} />}<span>{busy ? 'Executing in simulation…' : 'Play robot move'}</span><ArrowRight size={16} /></button>
          </section>
          <section className="telemetry-panel panel"><div className="panel-heading"><div className="panel-title"><Activity size={16} /><h2>Session telemetry</h2></div><span className="subtle-label">LIVE FROM ENGINE</span></div><div className="telemetry-grid"><div className="metric"><span>MOVES PLAYED</span><strong>{String(moveNumber).padStart(2, '0')}<small>plies</small></strong><p>{state?.last_move ? `${state.last_move.slice(0, 2)} → ${state.last_move.slice(2, 4)} · last move` : 'Opening position'}</p></div><div className="metric"><span>IK POSITION ERROR</span><strong>{maxError === null ? '—' : maxError.toFixed(2)}<small>mm</small></strong><p>{maxError === null ? 'Awaiting first motion plan' : 'Maximum waypoint residual'}</p></div><div className="metric captured-metric"><span>OFF-BOARD CAPTURES</span><strong>{String(state?.captures.length || 0).padStart(2, '0')}<small>pieces</small></strong><p>{state?.captures.length ? state.captures.map(piece => SYMBOLS[pieceCode(piece.piece)]).join(' ') : 'Capture tray is clear'}</p></div><div className="metric"><span>BOARD SCALE</span><strong>{state ? (state.config.board.square_size_m * 1000).toFixed(1) : '—'}<small>mm / sq</small></strong><p>{state?.calibration.status === 'measured_scale' ? 'Measured from RGB-D' : 'Sample geometry · calibrate'}</p></div></div>
            {showJoints && <div className="joint-panel"><div className="joint-heading"><strong>SO-101 joint positions</strong><span>Radians from MuJoCo</span></div>{state?.simulation.joints.map(joint => <div className="joint-row" key={joint.name}><span>{joint.name.replaceAll('_', ' ')}</span><div><i style={{ width: `${Math.max(0, Math.min(100, (joint.position - joint.min) / (joint.max - joint.min || 1) * 100))}%` }} /></div><code>{joint.position.toFixed(3)}</code></div>)}</div>}
          </section>
          <section className="activity-panel panel"><div className="panel-heading"><div className="panel-title"><Radio size={16} /><h2>Activity</h2></div><span className="subtle-label">SESSION LOG</span></div><div className="events-list">{state?.events.length ? state.events.slice(-4).reverse().map((event, i) => <div className="event" key={`${event.time}-${i}`}><span className={`event-marker ${i === 0 ? 'recent' : ''}`} /><div><p>{event.message}</p><time>{formatTime(event.time)}</time></div>{i === 0 && <ArrowDownLeft size={13} />}</div>) : <div className="empty-log"><span className="event-marker" /><p>{connected ? 'Ready for the first move.' : 'Connect the local engine to start a session.'}</p></div>}</div></section>
        </div>
        <div className="hardware-strip"><div className="hardware-label"><RobotMark size={20} /><strong>YOUR RIG</strong><span className="hardware-status">Physical connection not enabled</span></div><div className="hardware-items"><span>SO-101 follower <i /></span><span>Gemini 336 <small>RGB-D · SDK</small><i /></span><span>icspring wrist <small>UVC</small><i /></span><button onClick={() => setCalibrating(true)}>Set up calibration <ChevronRight size={15} /></button></div></div>
        <footer className="page-footer"><span>Built for a shared table.</span><span>SIMULATION FIRST <span>·</span> HUMAN IN THE LOOP <span>·</span> NONO LAB / 2026</span></footer>
      </main>
    </div>
    {calibrating && <Calibration state={state} canMutate={connected && session.canMutate} onClose={() => setCalibrating(false)} onRefresh={refresh} reportError={setError} />}
  </div>
}
