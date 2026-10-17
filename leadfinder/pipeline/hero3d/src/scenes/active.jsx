// Fitness, lessons, and everything with wheels.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, useCanvasTexture, useCfg } from "../kit.jsx";
import { NamePlaque } from "./care.jsx";

// ------------------------------------------------------------ fitness
export function Kettlebell() {
  const { accent } = useCfg();
  const body = useMemo(() => {
    const pts = [];
    for (let i = 0; i <= 32; i++) { const a = -Math.PI / 2 + (i / 32) * Math.PI * 0.92; pts.push(new THREE.Vector2(Math.max(0.001, Math.cos(a) * 0.82), Math.sin(a) * 0.78)); }
    return new THREE.LatheGeometry(pts, 72);
  }, []);
  const g = useRef();
  useFrame((_, dt) => { if (g.current) { g.current.rotation.y += dt * (0.4 + input.tap * 4); g.current.position.y = Math.sin(performance.now() / 700) * 0.06; } });
  return (
    <group>
      <group ref={g}>
        <mesh geometry={body}><meshPhysicalMaterial color="#1d1d20" roughness={0.42} clearcoat={0.6} clearcoatRoughness={0.3} /></mesh>
        <mesh position={[0, 0.98, 0]} scale={[1, 1.1, 1]}><torusGeometry args={[0.42, 0.11, 24, 72, Math.PI * 1.25]} /><Metal color="#2a2a2e" roughness={0.35} /></mesh>
        <mesh position={[0, 0.05, 0]} rotation={[Math.PI / 2, 0, 0]}><torusGeometry args={[0.8, 0.035, 12, 96]} /><Gloss color={accent} /></mesh>
      </group>
      <NamePlaque position={[1.45, -0.55, 0.3]} rotation={[0, -0.5, 0]} width={1.35} />
      <Shadow y={-0.95} scale={2.2} />
    </group>
  );
}

export function PilatesRing() {
  const { accent } = useCfg();
  const g = useRef();
  useFrame((_, dt) => { if (g.current) { g.current.rotation.y += dt * (0.35 + input.tap * 3); g.current.rotation.z = Math.sin(performance.now() / 1600) * 0.15; } });
  return (
    <group>
      <group ref={g}>
        <mesh><torusGeometry args={[1.0, 0.07, 24, 120]} /><Gloss color={accent} /></mesh>
        {[1, -1].map((s) => (<mesh key={s} position={[s * 1.06, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.2, 0.2, 0.14, 40]} /><meshPhysicalMaterial color="#1f1f22" roughness={0.6} /></mesh>))}
      </group>
      <mesh position={[0, 0, -0.3]}><sphereGeometry args={[0.62, 64, 48]} /><Glass primary thickness={1.2} chroma={0.06} /></mesh>
      <NamePlaque position={[0, -1.55, 0.3]} width={1.7} />
    </group>
  );
}

// ------------------------------------------------------------ lessons
function Note({ color, flag = true }) {
  return (
    <group>
      <mesh scale={[1.25, 0.92, 0.8]} rotation={[0, 0, 0.45]}><sphereGeometry args={[0.2, 32, 24]} /><Gloss color={color} /></mesh>
      <mesh position={[0.22, 0.5, 0]}><cylinderGeometry args={[0.025, 0.025, 1.0, 16]} /><Gloss color={color} /></mesh>
      {flag && <mesh position={[0.36, 0.86, 0]} rotation={[0, 0, -0.6]}><boxGeometry args={[0.32, 0.07, 0.04]} /><Gloss color={color} /></mesh>}
    </group>
  );
}

export function MusicNotes() {
  const { accent } = useCfg();
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 1700) * 0.5 + input.px * 0.3; });
  return (
    <group>
      <group ref={g}>
        <group position={[-0.45, -0.2, 0]} scale={1.5}><Note color={accent} /></group>
        <group position={[0.55, 0.15, -0.3]} scale={1.2}><Note color="#1c1c1f" flag={false} /></group>
      </group>
      <Drift count={12} spread={[6, 4, 2]} speed={0.18} rise make={(p) => (
        <group scale={0.3 + (p.i % 3) * 0.1}><Note color={p.i % 2 ? accent : "#26262a"} flag={p.i % 3 !== 0} /></group>
      )} />
      <NamePlaque position={[0, -1.55, 0.3]} width={1.8} />
    </group>
  );
}

export function Books() {
  const { accent, name, displayFont } = useCfg();
  const spine = useCanvasTexture(1024, 160, (ctx, w, h) => {
    ctx.fillStyle = accent; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    fitText(ctx, name, displayFont, 600, 92, w - 120); ctx.fillText(name, w / 2, h / 2 + 4);
  }, [accent, name, displayFont]);
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2000) * 0.35 - 0.3 + input.px * 0.2; });
  const pages = <meshStandardMaterial color="#f4f1ea" roughness={0.9} />;
  return (
    <group ref={g}>
      {[["#1f2430", 1.9, 0.32, -0.7, 0.05], ["#c9c1b2", 1.75, 0.28, -0.4, -0.06], [accent, 2.0, 0.34, -0.06, 0.02]].map(([c, w, h, y, r], i) => (
        <group key={i} position={[0, y, 0]} rotation={[0, r, 0]}>
          <RoundedBox args={[w, h, 1.3]} radius={0.03}><meshPhysicalMaterial color={c} roughness={0.55} clearcoat={0.3} /></RoundedBox>
          <mesh position={[0.02, 0, 0]}><boxGeometry args={[w - 0.06, h - 0.06, 1.26]} />{pages}</mesh>
          {i === 2 && <mesh position={[0, 0, 0.651]}><planeGeometry args={[w * 0.98, h * 0.96]} /><meshBasicMaterial map={spine} toneMapped={false} /></mesh>}
        </group>
      ))}
      <group position={[0.35, 0.5, 0.1]} rotation={[0.2, 0.2, -1.1]}>
        <mesh><cylinderGeometry args={[0.07, 0.07, 1.6, 6]} /><meshPhysicalMaterial color="#f2c14e" roughness={0.4} /></mesh>
        <mesh position={[0, -0.88, 0]} rotation={[Math.PI, 0, 0]}><coneGeometry args={[0.07, 0.16, 6]} /><meshStandardMaterial color="#e8d3a9" /></mesh>
        <mesh position={[0, 0.84, 0]}><cylinderGeometry args={[0.072, 0.072, 0.12, 16]} /><Metal /></mesh>
      </group>
      <Shadow y={-0.95} scale={2.6} />
    </group>
  );
}

// ------------------------------------------------------------ wheels
export function SteeringWheel() {
  const { accent, initials, displayFont } = useCfg();
  const badge = useCanvasTexture(256, 256, (ctx, w) => {
    ctx.fillStyle = accent; ctx.beginPath(); ctx.arc(w / 2, w / 2, w / 2, 0, 7); ctx.fill();
    ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `600 100px ${displayFont}`; ctx.fillText(initials, w / 2, w / 2 + 6);
  }, [accent, initials, displayFont]);
  const lplate = useCanvasTexture(256, 256, (ctx, w) => {
    ctx.fillStyle = "#ffd200"; ctx.fillRect(0, 0, w, w);
    ctx.fillStyle = "#111"; ctx.font = "800 190px Geist, system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("L", w / 2, w / 2 + 10);
  }, []);
  const wheel = useRef(), plate = useRef();
  useFrame((_, dt) => {
    const t = performance.now() / 1000;
    if (wheel.current) wheel.current.rotation.z = Math.sin(t * 0.8) * 0.6 + input.px * 0.4 + input.tap * 2;
    if (plate.current) plate.current.rotation.y = Math.sin(t * 1.1) * 0.5;
  });
  const leather = <meshPhysicalMaterial color="#19191c" roughness={0.55} sheen={0.5} sheenColor="#555" />;
  return (
    <group rotation={[-0.25, 0.25, 0]}>
      <group ref={wheel}>
        <mesh><torusGeometry args={[1.05, 0.13, 32, 128]} />{leather}</mesh>
        {[Math.PI / 2, Math.PI / 2 + 2.15, Math.PI / 2 - 2.15].map((a, i) => (
          <mesh key={i} position={[Math.cos(a + Math.PI) * 0.5, Math.sin(a + Math.PI) * 0.5, 0]} rotation={[0, 0, a + Math.PI / 2]}><boxGeometry args={[0.16, 1.0, 0.08]} /><Metal color="#9aa0a8" roughness={0.3} /></mesh>
        ))}
        <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.36, 0.36, 0.2, 64]} />{leather}</mesh>
        <mesh position={[0, 0, 0.105]}><circleGeometry args={[0.3, 64]} /><meshBasicMaterial map={badge} toneMapped={false} /></mesh>
      </group>
      <group ref={plate} position={[1.35, 0.95, 0.3]}>
        <RoundedBox args={[0.6, 0.6, 0.03]} radius={0.04}><meshStandardMaterial color="#ffd200" /></RoundedBox>
        <mesh position={[0, 0, 0.017]}><planeGeometry args={[0.56, 0.56]} /><meshBasicMaterial map={lplate} toneMapped={false} /></mesh>
        <mesh position={[0, 0, -0.017]} rotation={[0, Math.PI, 0]}><planeGeometry args={[0.56, 0.56]} /><meshBasicMaterial map={lplate} toneMapped={false} /></mesh>
      </group>
      <NamePlaque position={[0, -1.42, 0.5]} width={1.7} />
    </group>
  );
}

export function Tyre() {
  const { accent } = useCfg();
  const tread = useCanvasTexture(512, 64, (ctx, w, h) => {
    ctx.fillStyle = "#1a1a1a"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#0b0b0b"; ctx.lineWidth = 7;
    for (let x = -h; x < w + h; x += 22) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + h * 0.6, h / 2); ctx.lineTo(x, h); ctx.stroke(); }
  }, []);
  useMemo(() => { tread.wrapS = tread.wrapT = THREE.RepeatWrapping; tread.repeat.set(6, 1); }, [tread]);
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.z -= dt * (0.6 + input.scroll * 4 + input.tap * 8); });
  return (
    <group rotation={[0, -0.55, 0]}>
      <group ref={g}>
        <mesh><torusGeometry args={[0.95, 0.36, 40, 128]} /><meshStandardMaterial map={tread} roughness={0.85} /></mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.7, 0.7, 0.42, 64, 1, true]} /><Metal color="#b9bec5" roughness={0.25} /></mesh>
        {Array.from({ length: 5 }, (_, i) => (
          <mesh key={i} rotation={[0, 0, (i / 5) * Math.PI * 2]} position={[0, 0, 0.12]}><boxGeometry args={[0.16, 1.26, 0.06]} /><Metal color="#d4d8dd" roughness={0.18} /></mesh>
        ))}
        <mesh position={[0, 0, 0.16]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.2, 0.2, 0.08, 48]} /><Gloss color={accent} /></mesh>
      </group>
      <NamePlaque position={[1.3, -0.9, 0.7]} rotation={[0, 0.45, 0]} width={1.4} />
      <Shadow y={-1.45} scale={2.4} />
    </group>
  );
}
