import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { useSharedSession } from '../src/shared'
import type { ControlLease, TeamMember } from '../src/shared'
import type { LabState } from '../src/types'

vi.mock('../src/Scene', () => ({ default: () => <div aria-label="Digital twin canvas" /> }))

const operator: TeamMember = { id: 'operator-1', name: 'Alex', role: 'operator', authentication: 'session' }
const viewer: TeamMember = { id: 'viewer-1', name: 'Robin', role: 'viewer', authentication: 'session' }
const emptyLease: ControlLease = { owner: null, held_by_you: false, expires_at: null, expires_in_seconds: 0, active: false, busy: false, cell_status: 'ready' }
const heldLease = (): ControlLease => ({ ...emptyLease, owner: operator, held_by_you: true, active: true, expires_at: Date.now() / 1000 + 300, expires_in_seconds: 300 })
const state: LabState = {
  mode: 'simulation', fen: '8/4p3/8/8/8/8/4P3/8 w - - 0 1', turn: 'white', status: 'ready',
  legal_moves: ['e2e4'], pieces: [{ square: 'e2', piece: 'pawn', color: 'white', position: [0, 0, 0] }],
  captures: [], last_move: null, events: [], config: { board: { square_size_m: .0381, origin_m: [0, 0, .0254], border_m: .0254, height_m: .0254 }, robot: {} },
  calibration: { status: 'unmeasured' }, simulation: { joints: [], tcp: [0, 0, 0], geoms: [] }, plan: null,
}
const response = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

function setupApi(identity: TeamMember | 'local' | null = operator, initialLease = emptyLease) {
  let lease = initialLease
  const fetch = vi.fn((url: string, options?: RequestInit): Promise<Response> => {
    if (url === '/api/auth/me') return identity === 'local' ? response({ detail: 'Not found' }, 404) : identity ? response(identity) : response({ detail: 'Sign in required' }, 401)
    if (url === '/api/auth/login') return response(operator)
    if (url === '/api/auth/logout') { lease = emptyLease; return response({ ok: true }) }
    if (url === '/api/server-info') return response({ revision: '0123456789abc', dirty: true, name: 'nono-shared' })
    if (url === '/api/control') return response(lease)
    if (url === '/api/control/acquire' || url === '/api/control/renew') { lease = heldLease(); return response(lease) }
    if (url === '/api/control/release') { lease = emptyLease; return response(lease) }
    if (url === '/api/state' || url === '/api/reset' || url === '/api/move') return response(state)
    throw new Error(`Unexpected request ${options?.method || 'GET'} ${url}`)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear() })

describe('shared console access', () => {
  it('preserves local chess controls when authentication endpoints are absent', async () => {
    const fetch = setupApi('local')
    render(<StrictMode><App /></StrictMode>)
    await waitFor(() => expect((screen.getByRole('button', { name: 'Reset board' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.queryByLabelText('Team access token')).toBeNull()
    fireEvent.click(screen.getByRole('gridcell', { name: 'e2, white pawn' }))
    fireEvent.click(screen.getByRole('gridcell', { name: 'e4, empty, legal destination' }))
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === '/api/move')).toBe(true))
    const [, options] = fetch.mock.calls.find(([url]) => url === '/api/move')!
    expect(options?.credentials).toBe('same-origin')
    expect(JSON.parse(options?.body as string)).toEqual({ uci: 'e2e4' })
    expect(fetch.mock.calls.some(([url]) => url.startsWith('/api/control'))).toBe(false)
  })

  it('uses a password login without persisting tokens and requires an operator lease', async () => {
    const fetch = setupApi(null)
    render(<App />)
    const input = await screen.findByLabelText('Team access token')
    expect(input.getAttribute('type')).toBe('password')
    expect(screen.queryByText('Engine offline')).toBeNull()
    fireEvent.change(input, { target: { value: 'test-only-team-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enter Chess Lab' }))
    await screen.findByText('The controls are available')
    expect((screen.getByRole('button', { name: 'Reset board' }) as HTMLButtonElement).disabled).toBe(true)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    const [, loginOptions] = fetch.mock.calls.find(([url]) => url === '/api/auth/login')!
    expect(loginOptions?.credentials).toBe('same-origin')
    expect(JSON.parse(loginOptions?.body as string)).toEqual({ token: 'test-only-team-token' })
    expect(fetch.mock.calls.every(([url]) => !url.includes('test-only-team-token'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Take control' }))
    await screen.findByText('You have control')
    expect((screen.getByRole('button', { name: 'Reset board' }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.getByText(/rev 012345678 · modified/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Release control' }))
    await screen.findByText('The controls are available')
    expect((screen.getByRole('button', { name: 'Reset board' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('keeps viewer chess and calibration mutations disabled while allowing inspection', async () => {
    const fetch = setupApi(viewer)
    render(<App />)
    await screen.findByText('You’re viewing the shared session')
    const pawn = await screen.findByRole('gridcell', { name: 'e2, white pawn' })
    expect(screen.queryByRole('button', { name: 'Take control' })).toBeNull()
    for (const name of ['Reset board', 'Play demo', 'Play robot move']) expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Top' }) as HTMLButtonElement).disabled).toBe(false)
    expect((pawn as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(pawn)
    fireEvent.click(screen.getByRole('button', { name: 'Align camera' }))
    expect((screen.getByRole('button', { name: 'Capture frame' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Measure from depth' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Simulation geometry' }))
    expect((screen.getByRole('button', { name: 'Apply & reset simulation' }) as HTMLButtonElement).disabled).toBe(true)
    expect(fetch.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
  })

  it('shows login, not an offline board, when state access returns 401', async () => {
    const base = setupApi('local')
    const original = base.getMockImplementation()!
    base.mockImplementation((url, options) => url === '/api/state' ? response({ detail: 'Sign in required' }, 401) : original(url, options))
    render(<App />)
    await screen.findByLabelText('Team access token')
    expect(screen.queryByText('Engine offline')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reset board' })).toBeNull()
  })

  it('does not enable local controls when the access endpoint is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ detail: 'Service unavailable' }, 503)))
    render(<App />)
    await screen.findByText(/Unable to check server access/)
    expect((screen.getByRole('button', { name: 'Reset board' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByLabelText('Team access token')).toBeNull()
  })
})

describe('control lease lifetime', () => {
  it('renews only an explicitly held lease and stops on logout', async () => {
    vi.useFakeTimers()
    const fetch = setupApi()
    const { result } = renderHook(() => useSharedSession())
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.canMutate).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(fetch.mock.calls.filter(([url]) => url === '/api/control/renew')).toHaveLength(0)
    await act(async () => { await result.current.control('acquire') })
    expect(result.current.canMutate).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(fetch.mock.calls.filter(([url]) => url === '/api/control/renew')).toHaveLength(1)
    await act(async () => { await result.current.logout() })
    expect(result.current.member).toBeNull()
    expect(result.current.canMutate).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(fetch.mock.calls.filter(([url]) => url === '/api/control/renew')).toHaveLength(1)
  })

  it('does not renew a restored lease until requested and stops after unmount', async () => {
    vi.useFakeTimers()
    const fetch = setupApi(operator, heldLease())
    const { result, unmount } = renderHook(() => useSharedSession())
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.canMutate).toBe(true)
    expect(result.current.autoRenew).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(fetch.mock.calls.filter(([url]) => url === '/api/control/renew')).toHaveLength(0)
    await act(async () => { await result.current.control('renew') })
    expect(result.current.autoRenew).toBe(true)
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(fetch.mock.calls.filter(([url]) => url === '/api/control/renew')).toHaveLength(1)
  })

  it('ignores an old control poll that completes after acquisition', async () => {
    const fetch = setupApi()
    const original = fetch.getMockImplementation()!
    let resolvePoll: (response: Response) => void = () => {}
    fetch.mockImplementation((url, options) => url === '/api/control' ? new Promise(resolve => { resolvePoll = resolve }) : original(url, options))
    const { result } = renderHook(() => useSharedSession())
    await waitFor(() => expect(result.current.member?.id).toBe(operator.id))
    await act(async () => { await result.current.control('acquire') })
    expect(result.current.canMutate).toBe(true)
    await act(async () => { resolvePoll(await response(emptyLease)) })
    expect(result.current.canMutate).toBe(true)
  })

  it('disables mutations immediately while releasing a lease', async () => {
    const fetch = setupApi(operator, heldLease())
    const original = fetch.getMockImplementation()!
    let resolveRelease: (response: Response) => void = () => {}
    fetch.mockImplementation((url, options) => url === '/api/control/release' ? new Promise(resolve => { resolveRelease = resolve }) : original(url, options))
    const { result } = renderHook(() => useSharedSession())
    await waitFor(() => expect(result.current.canMutate).toBe(true))
    act(() => { void result.current.control('release') })
    expect(result.current.canMutate).toBe(false)
    await act(async () => { resolveRelease(await response(emptyLease)) })
    expect(result.current.canMutate).toBe(false)
  })
})
