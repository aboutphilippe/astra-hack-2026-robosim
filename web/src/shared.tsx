import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, Eye, KeyRound, LoaderCircle, LogOut, Radio, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, ApiError } from './types'
import './shared.css'

export type TeamMember = { id: string; name: string; role: 'viewer' | 'operator'; authentication?: 'bearer' | 'session' }
export type ControlLease = {
  owner: { id: string; name: string } | null
  held_by_you: boolean
  expires_at: number | null
  expires_in_seconds: number
  active: boolean
  busy: boolean
  cell_status: string
}
export type ServerInfo = { revision?: string; name?: string; [key: string]: unknown }

export function hasControl(mode: 'checking' | 'local' | 'shared', member: TeamMember | null, lease: ControlLease | null, now: number) {
  if (mode === 'local') return true
  return mode === 'shared' && member?.role === 'operator' && lease?.held_by_you === true && lease.active && (lease.expires_at ?? 0) * 1000 > now
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Could not reach the shared server.'
}

export function useSharedSession() {
  const [mode, setMode] = useState<'checking' | 'local' | 'shared'>('checking')
  const [member, setMember] = useState<TeamMember | null>(null)
  const [lease, setLease] = useState<ControlLease | null>(null)
  const [server, setServer] = useState<ServerInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const mounted = useRef(true)
  const explicitControl = useRef(false)
  const generation = useRef(0)
  const probing = useRef(false)
  const controlRequest = useRef(0)
  const controlInFlight = useRef(false)

  const requireLogin = useCallback(() => {
    generation.current += 1
    explicitControl.current = false
    setMode('shared'); setMember(null); setLease(null)
  }, [])

  const readServer = useCallback(async () => {
    try { const info = await api<ServerInfo>('server-info'); if (mounted.current) setServer(info) } catch { /* Optional on local/older servers. */ }
  }, [])

  const probe = useCallback(async () => {
    if (probing.current) return
    probing.current = true
    const epoch = generation.current
    try {
      const identity = await api<TeamMember>('auth/me')
      if (!mounted.current || epoch !== generation.current) return
      setMode('shared'); setMember(identity); setError(null)
      void readServer()
    } catch (error) {
      if (!mounted.current || epoch !== generation.current) return
      if (error instanceof ApiError && error.status === 404) { setMode('local'); setError(null) }
      else if (error instanceof ApiError && error.status === 401) { requireLogin(); setError(null); void readServer() }
      else setError(`Unable to check server access. ${errorMessage(error)}`)
    } finally { probing.current = false }
  }, [readServer, requireLogin])

  useEffect(() => {
    mounted.current = true
    void probe()
    return () => { mounted.current = false; explicitControl.current = false; probing.current = false; generation.current += 1 }
  }, [probe])

  // Retry an unavailable access endpoint without silently enabling local controls.
  useEffect(() => {
    if (mode !== 'checking') return
    const timer = window.setInterval(() => void probe(), 4000)
    return () => clearInterval(timer)
  }, [mode, probe])

  const refreshControl = useCallback(async () => {
    if (controlInFlight.current) return
    const epoch = generation.current
    const request = ++controlRequest.current
    try {
      const next = await api<ControlLease>('control')
      if (!mounted.current || epoch !== generation.current || request !== controlRequest.current) return
      setLease(next); setNow(Date.now())
      if (!next.held_by_you) explicitControl.current = false
    } catch (error) {
      if (!mounted.current || epoch !== generation.current || request !== controlRequest.current) return
      setLease(null); explicitControl.current = false
      if (error instanceof ApiError && error.status === 401) requireLogin()
      else setError(`Control status is unavailable. ${errorMessage(error)}`)
    }
  }, [requireLogin])

  useEffect(() => {
    if (mode !== 'shared' || !member) return
    void refreshControl()
    const poll = window.setInterval(() => void refreshControl(), 5000)
    const clock = window.setInterval(() => setNow(Date.now()), 1000)
    return () => { clearInterval(poll); clearInterval(clock) }
  }, [mode, member?.id, refreshControl])

  const control = useCallback(async (action: 'acquire' | 'renew' | 'release') => {
    if (controlInFlight.current) return
    controlInFlight.current = true
    controlRequest.current += 1
    setBusy(true); setError(null)
    const epoch = generation.current
    let failed = false
    if (action === 'release') { explicitControl.current = false; setLease(null) }
    try {
      const next = await api<ControlLease>(`control/${action}`, action === 'acquire' ? { ttl_seconds: 300 } : {})
      if (!mounted.current || epoch !== generation.current) return
      setLease(next); setNow(Date.now())
      explicitControl.current = action !== 'release' && next.held_by_you
    } catch (error) {
      if (!mounted.current || epoch !== generation.current) return
      setError(errorMessage(error))
      if (error instanceof ApiError && error.status === 401) requireLogin()
      else { setLease(null); failed = true }
    } finally { controlInFlight.current = false; if (mounted.current) { setBusy(false); if (failed) void refreshControl() } }
  }, [refreshControl, requireLogin])

  useEffect(() => {
    if (mode !== 'shared' || !member) return
    const timer = window.setInterval(() => {
      if (explicitControl.current) void control('renew')
    }, 60_000)
    return () => clearInterval(timer)
  }, [mode, member?.id, control])

  const login = useCallback(async (token: string) => {
    setBusy(true); setError(null)
    const epoch = ++generation.current
    try {
      const identity = await api<TeamMember>('auth/login', { token })
      if (!mounted.current || epoch !== generation.current) return false
      setMode('shared'); setMember(identity); setLease(null)
      void readServer()
      return true
    } catch (error) {
      if (mounted.current && epoch === generation.current) setError(errorMessage(error))
      return false
    } finally { if (mounted.current) setBusy(false) }
  }, [readServer])

  const logout = useCallback(async () => {
    explicitControl.current = false
    setBusy(true); setError(null)
    // Invalidate control polls so a late response cannot restore a logged-out lease.
    const epoch = ++generation.current
    setLease(null)
    try {
      await api('auth/logout', {})
      if (mounted.current && epoch === generation.current) requireLogin()
    } catch (error) {
      if (!mounted.current || epoch !== generation.current) return
      if (error instanceof ApiError && error.status === 401) requireLogin()
      else setError(`Sign out failed. Your session is still open. ${errorMessage(error)}`)
    } finally { if (mounted.current) setBusy(false) }
  }, [requireLogin])

  return { mode, member, lease, server, error, busy, now, autoRenew: explicitControl.current, canMutate: hasControl(mode, member, lease, now), requireLogin, login, logout, control, refreshControl, retry: probe }
}

export type SharedSession = ReturnType<typeof useSharedSession>

export function TeamLogin({ session }: { session: SharedSession }) {
  const [token, setToken] = useState('')
  return <main className="team-login-page">
    <a href="/" className="team-login-brand" aria-label="NONO Chess Lab">NONO <span>/ Chess Lab</span></a>
    <section className="team-login-card" aria-labelledby="team-login-title">
      <span className="login-icon"><KeyRound size={26} strokeWidth={1.5} /></span>
      <div className="eyebrow">ONE LAB · SHARED WITH YOUR TEAM</div>
      <h1 id="team-login-title">Join the shared table.</h1>
      <p>Use your team access token to enter the lab. Everyone sees the same robot, board, and session.</p>
      <form onSubmit={async event => { event.preventDefault(); if (await session.login(token.trim())) setToken('') }}>
        <label htmlFor="team-token">Team access token</label>
        <input id="team-token" name="token" type="password" autoComplete="current-password" autoFocus spellCheck={false} autoCapitalize="none" required value={token} onChange={event => setToken(event.target.value)} placeholder="Enter your access token" disabled={session.busy} aria-describedby={session.error ? 'team-login-error' : 'team-token-note'} />
        {session.error && <p className="team-login-error" id="team-login-error" role="alert">{session.error}</p>}
        <button className="primary-button" type="submit" disabled={session.busy || !token.trim()}>{session.busy ? <LoaderCircle size={16} className="spin" /> : <ArrowRight size={16} />}{session.busy ? 'Signing in…' : 'Enter Chess Lab'}</button>
      </form>
      <p id="team-token-note" className="team-token-note"><ShieldCheck size={15} /> Access is held in a session cookie. Your token is never saved in browser storage.</p>
    </section>
    <div className="team-login-footer"><Radio size={13} /> Shared server · sign in required{typeof session.server?.revision === 'string' && <code>rev {session.server.revision.slice(0, 12)}</code>}</div>
  </main>
}

export function SharedControlBar({ session, revision }: { session: SharedSession; revision?: string }) {
  const remaining = Math.max(0, Math.ceil(((session.lease?.expires_at ?? 0) * 1000 - session.now) / 1000))
  const owned = session.canMutate
  const otherOwner = session.lease?.active && !session.lease.held_by_you ? session.lease.owner?.name : null
  const title = owned ? 'You have control' : otherOwner ? `${otherOwner} has control` : session.member?.role === 'viewer' ? 'You’re viewing the shared session' : 'The controls are available'
  return <section className={`shared-control-bar ${owned ? 'has-control' : ''}`} aria-label="Shared server access">
    <div className="shared-control-status">{owned ? <Check size={17} /> : <Eye size={17} />}<div><strong>{title}</strong><p>{owned ? `Lease ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')} · ${session.autoRenew ? 'renews while you hold control' : 'renew to keep control in this tab'}` : session.member?.role === 'viewer' ? 'Read-only access. Operators can take control of this lab.' : 'Take control before moving pieces or changing calibration.'}</p></div></div>
    <div className="shared-control-actions"><span className="team-member-name">{session.member?.name}<small>{session.member?.role}</small></span>{revision && <code className="server-revision" title={`Server revision ${revision}${session.server?.dirty ? ' with local changes' : ''}`}>rev {revision.slice(0, 9)}{session.server?.dirty ? ' · modified' : ''}</code>}
      {session.member?.role === 'operator' && (owned ? <><button className="small-button" disabled={session.busy} onClick={() => void session.control('renew')} aria-label="Renew control lease"><RefreshCw size={13} /> Renew</button><button className="small-button" disabled={session.busy} onClick={() => void session.control('release')}>Release control</button></> : <button className="primary-button" disabled={session.busy || Boolean(otherOwner)} onClick={() => void session.control('acquire')}>{session.busy ? <LoaderCircle size={14} className="spin" /> : <KeyRound size={14} />} Take control</button>)}
      <button className="icon-button" aria-label="Sign out" title="Sign out" disabled={session.busy} onClick={() => void session.logout()}><LogOut size={17} /></button>
    </div>
    {session.error && <p className="shared-control-error" role="alert">{session.error}</p>}
  </section>
}
