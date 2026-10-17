// Trades, cleaning, removals and gardens.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, rand, twoLines, useCanvasTexture, useCfg } from "../kit.jsx";
import { NamePlaque } from "./care.jsx";

const COPPER = "#c27a4a", BRASS = "#c9a24a";

export function Pipes() {
  const { accent } = useCfg();
  const tube = useMemo(() => {
    const path = new THREE.CurvePath();
    const P = (x, y, z) => new THREE.Vector3(x, y, z);
    const segs = [[P(-1.6, -0.8, 0), P(-0.4, -0.8, 0)], [P(-0.4, -0.8, 0), P(-0.1, -0.8, 0), P(-0.1, -0.5, 0)], [P(-0.1, -0.5, 0), P(-0.1, 0.4, 0)],
      [P(-0.1, 0.4, 0), P(-0.1, 0.7, 0), P(0.2, 0.7, 0)], [P(0.2, 0.7, 0), P(1.3, 0.7, 0)]];
    segs.forEach((s) => path.add(s.length === 2 ? new THREE.LineCurve3(...s) : new THREE.QuadraticBezierCurve3(...s)));
    return new THREE.TubeGeometry(path, 200, 0.13, 32, false);
  }, []);
  const drop = useRef();
  useFrame(() => {
    const t = (performance.now() / 1000) % 2.2;
    if (drop.current) { drop.current.position.set(1.3, 0.48 - Math.max(0, t - 0.8) ** 2 * 2.2, 0); drop.current.scale.setScalar(Math.min(1, t / 0.8) * 0.12); }
  });
  return (
    <group rotation={[0.1, -0.4, 0]}>
      <mesh geometry={tube}><Metal color={COPPER} roughness={0.28} /></mesh>
      {[[-0.4, -0.8, 0, Math.PI / 2], [-0.1, 0.4, 0, 0], [0.2, 0.7, 0, Math.PI / 2]].map(([x, y, z, r], i) => (
        <mesh key={i} position={[x, y, z]} rotation={[0, 0, r]}><cylinderGeometry args={[0.17, 0.17, 0.2, 40]} /><Metal color={BRASS} roughness={0.3} /></mesh>
      ))}
      <group position={[-0.1, 0.05, 0.2]} rotation={[Math.PI / 2, 0, 0]}>
        <mesh><cylinderGeometry args={[0.32, 0.32, 0.06, 40]} /><Gloss color={accent} /></mesh>
      </group>
      <mesh ref={drop}><sphereGeometry args={[1, 32, 24]} /><Glass thickness={0.3} tint="#dff3ff" /></mesh>
      <NamePlaque position={[0.6, -0.55, 0.6]} rotation={[0, 0.25, 0]} width={1.5} />
    </group>
  );
}

export function Bulb() {
  const { accent } = useCfg();
  const glass = useMemo(() => {
    // Profile from the neck up and over the dome (bottom → top) for the lathe.
    const pts = [new THREE.Vector2(0.3, -1.0), new THREE.Vector2(0.32, -0.8)];
    for (let i = 0; i <= 40; i++) { const a = 2.35 - (i / 40) * 2.35; pts.push(new THREE.Vector2(Math.max(0.001, Math.sin(a) * 0.75), Math.cos(a) * 0.75)); }
    return new THREE.LatheGeometry(pts, 64);
  }, []);
  const coil = useMemo(() => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(Array.from({ length: 40 }, (_, i) => new THREE.Vector3(-0.3 + (i / 39) * 0.6, Math.sin(i * 1.4) * 0.05 + 0.05, Math.cos(i * 1.4) * 0.05))), 120, 0.012, 6, false), []);
  const glow = useRef();
  useFrame(() => { if (glow.current) glow.current.emissiveIntensity = 2.2 + Math.sin(performance.now() / 300) * 0.25 + input.tap * 3; });
  return (
    <group rotation={[0, 0, 0.12]} position={[0, 0.2, 0]}>
      <mesh geometry={glass}><Glass primary thickness={0.15} chroma={0.05} /></mesh>
      <mesh geometry={coil}><meshStandardMaterial ref={glow} color={accent} emissive={accent} emissiveIntensity={2.4} /></mesh>
      {[-0.3, 0.3].map((x) => <mesh key={x} position={[x, -0.35, 0]}><cylinderGeometry args={[0.008, 0.008, 0.8, 6]} /><Metal /></mesh>)}
      {Array.from({ length: 5 }, (_, i) => (<mesh key={i} position={[0, -1.02 - i * 0.075, 0]}><torusGeometry args={[0.3, 0.03, 12, 48]} /><Metal color="#b9b9b9" /></mesh>))}
      <mesh position={[0, -1.18, 0]}><cylinderGeometry args={[0.3, 0.24, 0.42, 48]} /><Metal color="#c4c4c4" /></mesh>
      <pointLight color={accent} intensity={1.5} distance={4} />
      <NamePlaque position={[0, -1.85, 0.4]} width={1.7} />
    </group>
  );
}

export function Roller() {
  const { accent } = useCfg();
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.x += dt * (0.8 + input.tap * 6); });
  return (
    <group rotation={[0.2, -0.5, 0.3]}>
      <group ref={g}><mesh rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.36, 0.36, 1.6, 64]} /><meshPhysicalMaterial color={accent} roughness={0.85} sheen={1} sheenColor="#ffffff" /></mesh></group>
      <mesh position={[0.95, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.03, 0.03, 0.3, 12]} /><Metal /></mesh>
      <mesh position={[1.1, -0.55, 0]}><cylinderGeometry args={[0.03, 0.03, 1.1, 12]} /><Metal /></mesh>
      <mesh position={[1.1, -1.35, 0]}><cylinderGeometry args={[0.09, 0.08, 0.6, 32]} /><meshPhysicalMaterial color="#1d1d1f" roughness={0.4} /></mesh>
      <NamePlaque position={[-0.6, -1.0, 0.4]} rotation={[0, 0.3, -0.3]} width={1.5} />
    </group>
  );
}

export function Key() {
  const { initials, displayFont } = useCfg();
  const geom = useMemo(() => {
    const s = new THREE.Shape();
    s.absarc(0, 0, 0.55, 0, Math.PI * 2, false);
    const hole = new THREE.Path(); hole.absarc(-0.22, 0, 0.14, 0, Math.PI * 2, true); s.holes.push(hole);
    const blade = new THREE.Shape();
    blade.moveTo(0.4, 0.1); blade.lineTo(2.1, 0.1); blade.lineTo(2.1, -0.32);
    [[1.95, -0.32], [1.9, -0.22], [1.75, -0.36], [1.6, -0.22], [1.45, -0.3], [1.35, -0.18], [1.2, -0.28], [1.1, -0.1], [0.4, -0.1]].forEach(([x, y]) => blade.lineTo(x, y));
    blade.closePath();
    const o = { depth: 0.08, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3, curveSegments: 48 };
    return [new THREE.ExtrudeGeometry(s, o), new THREE.ExtrudeGeometry(blade, o)];
  }, []);
  const stamp = useCanvasTexture(256, 256, (ctx, w) => { ctx.fillStyle = "rgba(60,40,10,0.75)"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `600 96px ${displayFont}`; ctx.fillText(initials, w / 2, w / 2 + 6); }, [initials, displayFont]);
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.y += dt * (0.5 + input.tap * 5); });
  return (
    <group ref={g} position={[-0.6, 0.1, 0]} rotation={[0, 0, 0.35]}>
      <mesh geometry={geom[0]}><Metal color={BRASS} roughness={0.25} /></mesh>
      <mesh geometry={geom[1]}><Metal color={BRASS} roughness={0.25} /></mesh>
      <mesh position={[0.12, 0, 0.105]}><planeGeometry args={[0.5, 0.5]} /><meshBasicMaterial map={stamp} transparent depthWrite={false} /></mesh>
    </group>
  );
}

export function Fan() {
  const { accent } = useCfg();
  const blade = useMemo(() => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.bezierCurveTo(0.3, 0.15, 0.9, 0.35, 1.0, 0.05); s.bezierCurveTo(0.9, -0.15, 0.4, -0.12, 0, 0);
    return new THREE.ExtrudeGeometry(s, { depth: 0.03, bevelEnabled: true, bevelThickness: 0.01, bevelSize: 0.01, bevelSegments: 2 });
  }, []);
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.z -= dt * (2.5 + input.tap * 10); });
  return (
    <group rotation={[0, -0.35, 0]}>
      <group ref={g}>{Array.from({ length: 5 }, (_, i) => (<mesh key={i} geometry={blade} rotation={[0.25, 0, (i / 5) * Math.PI * 2]}><Gloss color={accent} roughness={0.35} /></mesh>))}</group>
      <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.16, 0.16, 0.2, 40]} /><Metal /></mesh>
      <mesh><torusGeometry args={[1.18, 0.06, 20, 120]} /><Glass thickness={0.2} /></mesh>
      <Drift count={14} spread={[6, 4, 2]} speed={0.16} make={() => (<mesh scale={0.05}><octahedronGeometry args={[1, 0]} /><meshPhysicalMaterial color="#e9f6ff" transmission={0.8} roughness={0.1} thickness={0.2} /></mesh>)} />
      <NamePlaque position={[0, -1.6, 0.3]} width={1.7} />
    </group>
  );
}

export function Tools() {
  const { accent } = useCfg();
  const spanner = useMemo(() => {
    // Open-ended spanner: handle, round head with the jaw cut into its right side.
    const s = new THREE.Shape();
    s.moveTo(-1.2, -0.1); s.lineTo(0.72, -0.1);
    s.absarc(1.0, 0, 0.34, Math.PI + 0.4, Math.PI * 2 - 0.5, false);
    s.lineTo(1.06, -0.13); s.lineTo(1.06, 0.13);
    s.absarc(1.0, 0, 0.34, 0.5, Math.PI - 0.4, false);
    s.lineTo(-1.2, 0.1);
    s.absarc(-1.22, 0, 0.1, Math.PI / 2, Math.PI * 1.5, false);
    return new THREE.ExtrudeGeometry(s, { depth: 0.06, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3 });
  }, []);
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 1700) * 0.4 + input.px * 0.3; });
  return (
    <group ref={g}>
      <mesh geometry={spanner} rotation={[0, 0, 0.6]}><Metal roughness={0.2} /></mesh>
      <group rotation={[0, 0, -0.6]} position={[0, 0, 0.15]}>
        <mesh position={[-0.3, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.09, 0.08, 1.9, 32]} /><Gloss color={accent} roughness={0.5} /></mesh>
        <RoundedBox args={[0.32, 0.72, 0.3]} radius={0.05} position={[0.8, 0, 0]}><Metal color="#5d6168" roughness={0.3} /></RoundedBox>
      </group>
      <NamePlaque position={[0, -1.4, 0.4]} width={1.7} />
    </group>
  );
}

// ------------------------------------------------------------ cleaning & removals
export function Bubbles() {
  const g = useRef();
  const big = useMemo(() => [[0, 0.1, 0, 0.95], [-1.05, -0.55, -0.4, 0.55], [1.0, 0.75, -0.6, 0.42], [0.85, -0.75, 0.3, 0.3]], []);
  useFrame(() => { if (g.current) g.current.children.forEach((m, i) => { m.position.y = big[i][1] + Math.sin(performance.now() / 900 + i) * 0.08; }); });
  return (
    <group>
      <group ref={g}>{big.map(([x, y, z, r], i) => (
        <mesh key={i} position={[x, y, z]} scale={r}><sphereGeometry args={[1, 64, 48]} />
          <meshPhysicalMaterial transmission={1} thickness={0.05} roughness={0} ior={1.2} iridescence={1} iridescenceIOR={1.33} iridescenceThicknessRange={[120, 480]} envMapIntensity={1.4} clearcoat={1} />
        </mesh>
      ))}</group>
      <Drift count={16} spread={[6, 4, 2]} speed={0.22} rise make={(p) => (
        <mesh scale={0.05 + (p.i % 4) * 0.04}><sphereGeometry args={[1, 32, 24]} /><meshPhysicalMaterial transmission={1} thickness={0.05} roughness={0} iridescence={1} iridescenceIOR={1.33} /></mesh>
      )} />
      <NamePlaque position={[0, -1.55, 0.4]} width={1.8} />
    </group>
  );
}

export function Boxes() {
  const { name, displayFont, accent } = useCfg();
  const print = useCanvasTexture(1024, 768, (ctx, w, h) => {
    ctx.fillStyle = "#c9a273"; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = accent; ctx.fillRect(w * 0.44, 0, w * 0.12, h);
    ctx.fillStyle = "rgba(30,22,12,0.85)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l, displayFont, 700, 120, w * 0.8)));
    ctx.font = `700 ${size}px ${displayFont}`;
    lines.forEach((l, i) => ctx.fillText(l, w / 2, h * 0.42 + (i - (lines.length - 1) / 2) * size));
    ctx.font = "600 44px Geist, system-ui, sans-serif"; ctx.fillText("HANDLE WITH CARE  ↑↑", w / 2, h * 0.82);
  }, [name, displayFont, accent]);
  const kraft = <meshStandardMaterial color="#c9a273" roughness={0.9} />;
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2200) * 0.3 - 0.35 + input.px * 0.2; });
  return (
    <group ref={g}>
      {[[0, -0.55, 0, 1.7, 1.1, 1.3, 0], [0.12, 0.45, 0, 1.3, 0.9, 1.0, 0.12], [-0.05, 1.2, 0, 0.9, 0.6, 0.75, -0.1]].map(([x, y, z, w, h, d, r], i) => (
        <group key={i} position={[x, y, z]} rotation={[0, r, 0]}>
          <RoundedBox args={[w, h, d]} radius={0.02}>{kraft}</RoundedBox>
          <mesh position={[0, 0, d / 2 + 0.002]}><planeGeometry args={[w, h]} />{i === 0 ? <meshStandardMaterial map={print} roughness={0.85} /> : kraft}</mesh>
          <mesh position={[0, h / 2 + 0.002, 0]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[w * 0.14, d]} /><meshStandardMaterial color={accent} roughness={0.5} /></mesh>
        </group>
      ))}
      <Shadow y={-1.12} scale={2.8} />
    </group>
  );
}

// ------------------------------------------------------------ gardens
export function Terrarium() {
  const { accent } = useCfg();
  const blades = useMemo(() => Array.from({ length: 70 }, () => ({ x: rand(-0.85, 0.85), z: rand(-0.85, 0.85), h: rand(0.15, 0.4), r: rand(-0.3, 0.3) })).filter((b) => b.x * b.x + b.z * b.z < 0.7), []);
  const tree = useRef();
  useFrame(() => { if (tree.current) tree.current.rotation.z = Math.sin(performance.now() / 1300) * 0.04 + input.px * 0.05; });
  return (
    <group position={[0, -0.1, 0]}>
      <mesh><sphereGeometry args={[1.2, 64, 48]} /><Glass primary thickness={0.15} chroma={0.05} /></mesh>
      <mesh position={[0, -0.72, 0]}><cylinderGeometry args={[0.95, 0.85, 0.25, 64]} /><meshStandardMaterial color="#5b4636" roughness={0.95} /></mesh>
      {blades.map((b, i) => (<mesh key={i} position={[b.x, -0.6 + b.h / 2, b.z]} rotation={[0, 0, b.r]}><coneGeometry args={[0.02, b.h, 4]} /><meshStandardMaterial color={i % 3 ? "#4f7d3c" : "#7aa354"} /></mesh>))}
      <group ref={tree} position={[0.1, -0.6, 0]}>
        <mesh position={[0, 0.3, 0]}><cylinderGeometry args={[0.04, 0.06, 0.6, 12]} /><meshStandardMaterial color="#6b4a32" /></mesh>
        {[[0, 0.75, 0, 0.32], [-0.18, 0.62, 0.1, 0.22], [0.2, 0.66, -0.05, 0.24]].map(([x, y, z, r], i) => (<mesh key={i} position={[x, y, z]}><icosahedronGeometry args={[r, 1]} /><meshStandardMaterial color={i ? "#5f8f45" : "#4a7a36"} flatShading /></mesh>))}
      </group>
      <mesh position={[0, 1.22, 0]}><torusGeometry args={[0.12, 0.025, 12, 32]} /><Gloss color={accent} /></mesh>
      <Drift count={14} spread={[6, 4, 2]} speed={0.25} make={(p) => (<mesh scale={[0.12, 0.05, 0.01]}><sphereGeometry args={[1, 12, 8]} /><meshStandardMaterial color={p.i % 2 ? "#6c9a4a" : "#a9c46f"} /></mesh>)} />
      <NamePlaque position={[1.4, -0.75, 0.5]} rotation={[0, -0.45, 0]} width={1.35} />
      <Shadow y={-0.92} scale={2.6} />
    </group>
  );
}
