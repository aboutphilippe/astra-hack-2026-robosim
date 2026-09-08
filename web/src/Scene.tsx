import { Component, Suspense, useEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'
import { Canvas, useLoader, useThree } from '@react-three/fiber'
import { ContactShadows, Grid, Line, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import type { Geom, LabState, Vec3 } from './types'
import { FILES, pieceCode } from './types'

THREE.Object3D.DEFAULT_UP.set(0, 0, 1)

class SceneErrorBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false }
  static getDerivedStateFromError() { return { error: true } }
  render() { return this.state.error ? null : this.props.children }
}

const profiles: Record<string, [number, number][]> = {
  p: [[0, 0], [.009, 0], [.010, .003], [.008, .005], [.006, .006], [.004, .016], [.006, .018], [.006, .020], [.004, .022], [0, .023]],
  r: [[0, 0], [.011, 0], [.011, .004], [.008, .006], [.006, .008], [.006, .026], [.010, .028], [.010, .034], [0, .034]],
  n: [[0, 0], [.010, 0], [.011, .003], [.008, .005], [.006, .007], [.006, .012], [0, .012]],
  b: [[0, 0], [.010, 0], [.011, .003], [.008, .006], [.005, .008], [.003, .026], [.007, .028], [.007, .030], [.003, .031], [0, .032]],
  q: [[0, 0], [.012, 0], [.012, .003], [.009, .006], [.006, .008], [.004, .029], [.008, .031], [.008, .034], [.006, .035], [.009, .042], [0, .042]],
  k: [[0, 0], [.012, 0], [.012, .003], [.009, .006], [.006, .008], [.004, .033], [.008, .035], [.008, .038], [.004, .040], [.004, .045], [0, .045]],
}

function ChessPiece({ kind, color, position, height }: { kind: string; color: string; position: Vec3; height?: number | null }) {
  const code = pieceCode(kind)
  const profile = profiles[code] || profiles.p
  const geometry = useMemo(() => new THREE.LatheGeometry(profile.map(([r, z]) => new THREE.Vector2(r, z)), 24), [profile])
  const material = useMemo(() => new THREE.MeshStandardMaterial({ color: color === 'white' ? '#eeeade' : '#293932', roughness: .35, metalness: .08 }), [color])
  useEffect(() => () => { geometry.dispose(); material.dispose() }, [geometry, material])
  const nominalHeight = ({ p: .0315, r: .0385, n: .0475, b: .047, q: .0495, k: .0565 })[code as 'p'] || .032
  return <group position={position} scale={[1, 1, height && height > 0 ? height / nominalHeight : 1]}>
    <mesh geometry={geometry} material={material} rotation={[Math.PI / 2, 0, 0]} castShadow receiveShadow />
    {code === 'p' && <mesh position={[0, 0, .025]} material={material} castShadow><sphereGeometry args={[.0065, 20, 16]} /></mesh>}
    {code === 'b' && <group position={[0, 0, .036]}><mesh scale={[.006, .006, .009]} material={material} castShadow><sphereGeometry args={[1, 20, 16]} /></mesh><mesh position={[0, 0, .009]} material={material}><sphereGeometry args={[.002, 12, 12]} /></mesh></group>}
    {code === 'q' && <mesh position={[0, 0, .046]} material={material} castShadow><sphereGeometry args={[.0035, 16, 12]} /></mesh>}
    {code === 'k' && <group position={[0, 0, .049]}><mesh material={material} castShadow><boxGeometry args={[.0035, .0035, .015]} /></mesh><mesh position={[0, 0, .002]} material={material} castShadow><boxGeometry args={[.011, .0035, .0035]} /></mesh></group>}
    {code === 'n' && <group rotation={[0, 0, color === 'white' ? 0 : Math.PI]}><mesh position={[0, -.001, .022]} rotation={[.18, 0, 0]} material={material} castShadow><boxGeometry args={[.010, .012, .022]} /></mesh><mesh position={[0, .004, .035]} rotation={[-.25, 0, 0]} material={material} castShadow><boxGeometry args={[.009, .018, .011]} /></mesh><mesh position={[0, -.003, .043]} material={material} castShadow><coneGeometry args={[.004, .009, 3]} /></mesh></group>}
    {code === 'r' && Array.from({ length: 6 }, (_, i) => <mesh key={i} position={[Math.cos(i * Math.PI / 3) * .007, Math.sin(i * Math.PI / 3) * .007, .036]} rotation={[0, 0, i * Math.PI / 3]} material={material} castShadow><boxGeometry args={[.005, .005, .005]} /></mesh>)}
  </group>
}

function BoardLabel({ label, position }: { label: string; position: Vec3 }) {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 128; canvas.height = 128
    const context = canvas.getContext('2d')!
    context.fillStyle = '#635d4f'; context.font = '500 80px monospace'; context.textAlign = 'center'; context.textBaseline = 'middle'
    context.fillText(label, 64, 65)
    return new THREE.CanvasTexture(canvas)
  }, [label])
  useEffect(() => () => texture.dispose(), [texture])
  return <mesh position={position}><planeGeometry args={[.013, .013]} /><meshBasicMaterial map={texture} transparent depthWrite={false} /></mesh>
}

function STLMesh({ url, color, opacity }: { url: string; color: THREE.Color; opacity: number }) {
  const geometry = useLoader(STLLoader, url)
  return <mesh geometry={geometry} castShadow receiveShadow><meshStandardMaterial color={color} roughness={.55} metalness={.15} transparent={opacity < 1} opacity={opacity} /></mesh>
}

function RobotGeom({ geom }: { geom: Geom }) {
  const { size: s, quaternion: q } = geom
  const rgba = geom.color || [.3, .35, .32, 1]
  const alpha = rgba[3] ?? 1
  const kind = typeof geom.type === 'number' ? ['plane', 'hfield', 'sphere', 'capsule', 'ellipsoid', 'cylinder', 'box', 'mesh'][geom.type] : geom.type.toLowerCase()
  const color = new THREE.Color(rgba[0], rgba[1], rgba[2])
  if (alpha < .05 || kind === 'plane') return null
  return <group position={geom.position} quaternion={[q[1], q[2], q[3], q[0]]}>
    {geom.mesh ? <SceneErrorBoundary><Suspense fallback={null}><STLMesh url={geom.mesh} color={color} opacity={alpha} /></Suspense></SceneErrorBoundary> : <mesh rotation={kind === 'cylinder' || kind === 'capsule' ? [Math.PI / 2, 0, 0] : [0, 0, 0]} scale={kind === 'ellipsoid' ? [s[0], s[1], s[2]] : undefined} castShadow receiveShadow>
      {kind === 'box' || kind === 'mesh' ? <boxGeometry args={[s[0] * 2, s[1] * 2, s[2] * 2]} /> : kind === 'cylinder' ? <cylinderGeometry args={[s[0], s[0], s[1] * 2, 24]} /> : kind === 'capsule' ? <capsuleGeometry args={[s[0], s[1] * 2, 8, 16]} /> : <sphereGeometry args={[kind === 'ellipsoid' ? 1 : s[0], 20, 16]} />}
      <meshStandardMaterial color={color} roughness={.5} metalness={.15} transparent={alpha < 1} opacity={alpha} />
    </mesh>}
  </group>
}

function CameraRig({ view, center, framingScale }: { view: 'orbit' | 'top'; center: Vec3; framingScale: number }) {
  const controls = useRef<OrbitControlsImpl>(null)
  const { camera, size } = useThree()
  const cameraScale = framingScale * Math.max(1, size.height / Math.max(size.width, 1))
  const cx = center[0], cy = center[1], cz = center[2]
  useEffect(() => {
    camera.up.set(0, 0, 1)
    if (view === 'top') {
      camera.up.set(0, -1, 0)
      camera.position.set(cx, cy, cz + .88 * cameraScale)
    } else camera.position.set(cx + .56 * cameraScale, cy - .70 * cameraScale, cz + .69 * cameraScale)
    camera.lookAt(cx, cy, cz)
    controls.current?.target.set(cx, cy, cz)
    controls.current?.update()
  }, [view, cx, cy, cz, cameraScale, camera])
  return <OrbitControls ref={controls} makeDefault target={center} enableRotate={view !== 'top'} minDistance={.28} maxDistance={1.7 * cameraScale} maxPolarAngle={Math.PI / 2.02} enableDamping dampingFactor={.1} />
}

function Twin({ state, view, showPath }: { state: LabState; view: 'orbit' | 'top'; showPath: boolean }) {
  const { square_size_m: size, origin_m: origin, border_m: border, height_m: height, yaw_rad: yaw = 0 } = state.config.board
  const width = 8 * size
  const center: Vec3 = [origin[0] + width / 2 * (Math.cos(yaw) - Math.sin(yaw)), origin[1] + width / 2 * (Math.sin(yaw) + Math.cos(yaw)), origin[2]]
  const configuredBase = state.config.robot.base_position_m
  const base = configuredBase?.length === 3 && configuredBase.every(Number.isFinite) ? configuredBase : null
  // Frame the fixture from its fixed board/base positions, so animation never recenters the camera.
  const framingCenter: Vec3 = base ? [(center[0] * 2 + base[0]) / 3, (center[1] * 2 + base[1]) / 3, Math.max(center[2], base[2]) + .07] : [center[0], center[1] + .035, center[2] + .06]
  const framingSpan = Math.max(width + border * 2, base ? Math.hypot(base[0] - center[0], base[1] - center[1], base[2] - center[2]) + width / 2 + border : 0)
  const framingScale = Math.max(1, framingSpan / .55)
  const visibleGeoms = state.simulation.geoms.filter(geom => !/^(board|square|piece|capture|floor|table|ground)/i.test(geom.name))
  const path = state.plan?.waypoints.map(point => point.target)
  const lastFrom = state.last_move?.slice(0, 2), lastTo = state.last_move?.slice(2, 4)
  return <>
    <CameraRig view={view} center={framingCenter} framingScale={framingScale} />
    <ambientLight intensity={1.1} />
    <hemisphereLight args={['#fbfff6', '#819182', 1.1]} />
    <directionalLight position={[-.5, -.3, 1.2]} intensity={2.5} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-.75} shadow-camera-right={.75} shadow-camera-top={.85} shadow-camera-bottom={-.7} shadow-bias={-.0001} />
    <directionalLight position={[.8, .8, .5]} intensity={1} />
    <mesh rotation={[0, 0, 0]} position={[0, .2, -.008]} receiveShadow><planeGeometry args={[20, 20]} /><meshStandardMaterial color="#e6e8df" roughness={1} /></mesh>
    <Grid position={[0, .2, -.0075]} rotation={[Math.PI / 2, 0, 0]} args={[3, 3]} cellSize={.0254} cellThickness={.4} cellColor="#d4d9ce" sectionSize={.127} sectionThickness={.7} sectionColor="#cbd1c6" fadeDistance={2} fadeStrength={3} infiniteGrid />
    <group position={origin} rotation={[0, 0, yaw]}>
    <mesh position={[width / 2, width / 2, -height / 2]} receiveShadow castShadow><boxGeometry args={[width + border * 2, width + border * 2, height]} /><meshStandardMaterial color="#aa987b" roughness={.7} /></mesh>
    <mesh position={[width / 2, width / 2, -.001]} receiveShadow><boxGeometry args={[width + border * 1.85, width + border * 1.85, .004]} /><meshStandardMaterial color="#d1bea0" roughness={.75} /></mesh>
    {Array.from({ length: 64 }, (_, i) => {
      const x = i % 8, y = Math.floor(i / 8), square = `${FILES[x]}${y + 1}`
      const isLast = square === lastFrom || square === lastTo
      return <mesh key={square} position={[(x + .5) * size, (y + .5) * size, .001]} receiveShadow><boxGeometry args={[size, size, .002]} /><meshStandardMaterial color={isLast ? (x + y) % 2 === 0 ? '#91a862' : '#bdcc8e' : (x + y) % 2 === 0 ? '#54705f' : '#c6cbb8'} roughness={.8} /></mesh>
    })}
    {FILES.split('').map((file, x) => <BoardLabel key={file} label={file.toUpperCase()} position={[(x + .5) * size, -border * .55, .002]} />)}
    {Array.from({ length: 8 }, (_, y) => <BoardLabel key={y} label={String(y + 1)} position={[-border * .55, (y + .5) * size, .002]} />)}
    {Array.from({ length: 8 }, (_, y) => <BoardLabel key={`h-${y}`} label={String(y + 1)} position={[width + border * .55, (y + .5) * size, .002]} />)}
    </group>
    {state.pieces.map(piece => <ChessPiece key={piece.square} kind={piece.piece} color={piece.color} position={piece.position} height={piece.height_m} />)}
    {state.captures.map((piece, i) => <ChessPiece key={`capture-${i}`} kind={piece.piece} color={piece.color} position={piece.position} />)}
    {visibleGeoms.map((geom, i) => <RobotGeom key={geom.name || i} geom={geom} />)}
    {showPath && path && path.length > 1 && <Line points={path} color="#448b72" lineWidth={1.5} dashed dashSize={.008} gapSize={.004} />}
    {showPath && state.simulation.tcp && <mesh position={state.simulation.tcp}><sphereGeometry args={[.003, 12, 12]} /><meshBasicMaterial color="#d4f384" /></mesh>}
    <ContactShadows position={[0, .2, -.006]} rotation={[Math.PI / 2, 0, 0]} opacity={.25} scale={2} blur={2} far={.8} resolution={512} />
  </>
}

export default function Scene({ state, view, showPath }: { state: LabState; view: 'orbit' | 'top'; showPath: boolean }) {
  return <Canvas shadows dpr={[1, 2]} camera={{ position: [.5, -.5, .6], fov: 38, near: .005, far: 30 }} gl={{ antialias: true }}>
    <color attach="background" args={['#e6e8df']} />
    <fog attach="fog" args={['#e6e8df', 1.5, 3.5]} />
    <Suspense fallback={null}><Twin state={state} view={view} showPath={showPath} /></Suspense>
  </Canvas>
}
