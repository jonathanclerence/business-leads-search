// Nails, beauty, spas, tattoo.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, twoLines, useCanvasTexture, useCfg } from "../kit.jsx";

function mixHex(a, b, t) {
  const ca = new THREE.Color(a), cb = new THREE.Color(b);
  return "#" + ca.lerp(cb, t).getHexString();
}

/** The label on a bottle: their initials large, the name small underneath. */
function useBottleLabel(w, h, { light = true } = {}) {
  const { name, initials, displayFont } = useCfg();
  return useCanvasTexture(w, h, (ctx) => {
    ctx.fillStyle = light ? "rgba(255,255,255,0.94)" : "rgba(20,20,20,0.9)";
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.font = `400 ${h * 0.5}px ${displayFont}`; ctx.fillText(initials, w / 2, h * 0.56);
    const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l.toUpperCase(), "Geist, system-ui, sans-serif", 600, h * 0.085, w * 0.86)));
    ctx.font = `600 ${size}px Geist, system-ui, sans-serif`;
    lines.forEach((l, i) => ctx.fillText(l.toUpperCase().split("").join(" "), w / 2, h * 0.72 + i * size * 1.35));
  }, [name, initials, displayFont, light]);
}

// ------------------------------------------------------------ nail polish
function Bottle({ color, position, rotation, scale = 1, label, primary = false }) {
  const liquid = useRef();
  useFrame(() => { if (liquid.current) liquid.current.rotation.z = Math.sin(performance.now() / 1200) * 0.02; });
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <RoundedBox args={[1.0, 1.15, 0.72]} radius={0.16} smoothness={6}><Glass primary={primary} thickness={1.1} chroma={0.05} /></RoundedBox>
      <RoundedBox ref={liquid} args={[0.84, 0.92, 0.56]} radius={0.12} smoothness={5} position={[0, -0.07, 0]}>
        <meshPhysicalMaterial color={color} roughness={0.12} clearcoat={1} clearcoatRoughness={0.05} sheen={0.6} sheenColor={mixHex(color, "#ffffff", 0.5)} envMapIntensity={1.2} />
      </RoundedBox>
      {label && <mesh position={[0, -0.06, 0.365]}><planeGeometry args={[0.8, 0.78]} /><meshBasicMaterial map={label} transparent depthWrite={false} toneMapped={false} /></mesh>}
      <mesh position={[0, 0.66, 0]}><cylinderGeometry args={[0.16, 0.18, 0.16, 48]} /><Glass thickness={0.3} /></mesh>
      <mesh position={[0, 1.22, 0]}><cylinderGeometry args={[0.21, 0.25, 0.98, 64]} /><meshPhysicalMaterial color="#141414" roughness={0.18} clearcoat={1} clearcoatRoughness={0.04} /></mesh>
      <mesh position={[0, 1.72, 0]}><cylinderGeometry args={[0.19, 0.21, 0.04, 64]} /><meshPhysicalMaterial color="#141414" roughness={0.18} clearcoat={1} /></mesh>
    </group>
  );
}

export function PolishBottle() {
  const { accent } = useCfg();
  const label = useBottleLabel(512, 512);
  const spin = useRef(), turn = useRef(0);
  useFrame((_, dt) => {
    turn.current += dt * (0.25 + input.tap * 4);
    if (spin.current) spin.current.rotation.y = Math.sin(turn.current) * 0.45;
  });
  return (
    <group position={[0, -0.25, 0]}>
      <group ref={spin}><Bottle primary color={accent} label={label} position={[0, 0, 0]} /></group>
      <Bottle color={mixHex(accent, "#ffffff", 0.45)} position={[-1.15, -0.32, -1.1]} rotation={[0, 0.5, 0.08]} scale={0.72} />
      <Bottle color={mixHex(accent, "#000000", 0.35)} position={[1.05, -0.4, -0.8]} rotation={[0, -0.6, -0.05]} scale={0.6} />
      <Drift count={14} spread={[6, 4, 2.5]} speed={0.12} rise make={(p) => (
        <mesh scale={0.05 + (p.i % 4) * 0.025}><sphereGeometry args={[1, 24, 16]} /><Gloss color={p.i % 3 ? accent : mixHex(accent, "#ffffff", 0.5)} roughness={0.1} /></mesh>
      )} />
      <Shadow y={-0.9} scale={2.6} />
    </group>
  );
}

// ------------------------------------------------------------ serum / spa
export function Serum() {
  const { accent } = useCfg();
  const label = useBottleLabel(512, 512);
  const body = useMemo(() => {
    const pts = [];
    for (let i = 0; i <= 24; i++) { const t = i / 24, a = -Math.PI / 2 + t * Math.PI; pts.push(new THREE.Vector2(Math.cos(a) * 0.62 + 0.001, Math.sin(a) * 0.72)); }
    return new THREE.LatheGeometry(pts, 64);
  }, []);
  const drop = useRef();
  useFrame(() => {
    const t = (performance.now() / 1000) % 3;
    if (drop.current) { drop.current.position.y = 1.35 - Math.max(0, t - 1.5) ** 2 * 1.6; drop.current.visible = t > 0.6; drop.current.scale.setScalar(Math.min(1, t / 1.2) * 0.07); }
  });
  return (
    <group position={[0, -0.4, 0]}>
      <mesh geometry={body}><Glass primary thickness={1.2} tint={mixHex(accent, "#ffffff", 0.7)} /></mesh>
      <mesh scale={[0.52, 0.5, 0.52]} position={[0, -0.2, 0]}><sphereGeometry args={[1, 48, 32]} /><meshPhysicalMaterial color={accent} roughness={0.08} transmission={0.4} thickness={1} clearcoat={1} /></mesh>
      <mesh position={[0, -0.05, 0.63]}><planeGeometry args={[0.7, 0.7]} /><meshBasicMaterial map={label} transparent depthWrite={false} toneMapped={false} /></mesh>
      <mesh position={[0, 0.82, 0]}><cylinderGeometry args={[0.2, 0.2, 0.22, 48]} /><Metal color="#d8c7a0" roughness={0.25} /></mesh>
      <mesh position={[0, 1.12, 0]}><capsuleGeometry args={[0.16, 0.32, 12, 32]} /><Gloss color={mixHex(accent, "#000000", 0.25)} roughness={0.45} /></mesh>
      <mesh ref={drop}><sphereGeometry args={[1, 24, 16]} /><Glass thickness={0.2} /></mesh>
      <Drift count={10} spread={[5.5, 4, 2]} speed={0.1} rise make={(p) => (
        <mesh scale={0.04 + (p.i % 3) * 0.03}><sphereGeometry args={[1, 20, 14]} /><meshPhysicalMaterial transmission={1} thickness={0.3} roughness={0.02} iridescence={1} iridescenceIOR={1.3} /></mesh>
      )} />
      <Shadow y={-0.78} scale={2} />
    </group>
  );
}

// ------------------------------------------------------------ tattoo flash
const ROSE = (() => {
  // A rose in fine line, as strokes of points on a 0..1 square; drawn in order.
  const S = [];
  let p = []; for (let t = 0; t <= 1; t += 0.012) { const th = t * Math.PI * 4.4, r = 0.015 + 0.15 * t; p.push([0.5 + Math.cos(th) * r, 0.36 + Math.sin(th) * r * 0.85]); } S.push(p);
  [[-0.25, 1.15], [1.85, 3.25], [3.55, 5.0], [0.9, 2.2]].forEach(([a0, a1], k) => {
    p = []; for (let t = 0; t <= 1; t += 0.04) { const a = a0 + (a1 - a0) * t, r = (k === 3 ? 0.27 : 0.21) + Math.sin(t * Math.PI) * 0.05; p.push([0.5 + Math.cos(a) * r, 0.36 + Math.sin(a) * r * 0.85]); } S.push(p);
  });
  p = []; for (let t = 0; t <= 1; t += 0.04) p.push([0.5 + Math.sin(t * 2.6) * 0.05, 0.6 + t * 0.3]); S.push(p);
  [[1, 0.35], [-1, 0.62]].forEach(([dir, at]) => {
    const bx = 0.5 + Math.sin(at * 2.6) * 0.05, by = 0.6 + at * 0.3;
    p = []; for (let t = 0; t <= 1; t += 0.06) p.push([bx + dir * t * 0.16, by - Math.sin(t * Math.PI) * 0.05 - t * 0.05]);
    for (let t = 1; t >= 0; t -= 0.06) p.push([bx + dir * t * 0.16, by + Math.sin(t * Math.PI) * 0.03 - t * 0.05]);
    S.push(p);
  });
  return S;
})();
const ROSE_POINTS = ROSE.reduce((n, s) => n + s.length, 0);

export function TattooFlash() {
  const { accent, name, displayFont, suburb } = useCfg();
  const W = 768, H = 960;
  const progress = useRef(0);
  const tip = useRef([0.5, 0.36]);
  const art = useCanvasTexture(W, H, () => {}, []);
  const paper = useRef();
  const pen = useRef();
  const drawArt = (amount) => {
    const ctx = art.image.getContext("2d");
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#f3ede1"; ctx.fillRect(0, 0, W, H);
    ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#151515"; ctx.lineWidth = 5;
    let budget = Math.floor(ROSE_POINTS * amount);
    ROSE.forEach((st) => {
      if (budget <= 1) return;
      const n = Math.min(st.length, budget); budget -= n;
      ctx.beginPath(); ctx.moveTo(st[0][0] * W, st[0][1] * H * 0.82);
      for (let i = 1; i < n; i++) ctx.lineTo(st[i][0] * W, st[i][1] * H * 0.82);
      ctx.stroke(); tip.current = st[n - 1];
    });
    if (amount >= 1) {   // shading dots in the accent once the line work is done
      ctx.fillStyle = accent;
      for (let i = 0; i < 90; i++) { const a = i * 2.399, r = Math.sqrt(i) * 0.012; ctx.globalAlpha = 0.6; ctx.beginPath(); ctx.arc((0.5 + Math.cos(a) * r) * W, (0.36 + Math.sin(a) * r * 0.85) * H * 0.82, 3.2, 0, 7); ctx.fill(); }
      ctx.globalAlpha = 1;
    }
    // the banner with their name, as on a flash sheet
    const by = H * 0.83;
    ctx.fillStyle = accent; ctx.beginPath();
    ctx.moveTo(W * 0.08, by - 50); ctx.quadraticCurveTo(W * 0.5, by - 96, W * 0.92, by - 50); ctx.lineTo(W * 0.92, by + 44); ctx.quadraticCurveTo(W * 0.5, by, W * 0.08, by + 44); ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    fitText(ctx, name, displayFont, 700, 68, W * 0.76); ctx.fillText(name, W / 2, by - 14);
    ctx.fillStyle = "#151515"; ctx.font = "600 26px Geist, system-ui, sans-serif"; ctx.globalAlpha = 0.7;
    ctx.fillText((suburb || "").toUpperCase(), W / 2, H - 40); ctx.globalAlpha = 1;
    art.needsUpdate = true;
  };
  useFrame((_, dt) => {
    const before = progress.current;
    progress.current += dt / (input.tap > 0.9 ? 0.0001 : 7);
    if (progress.current > 1.45) progress.current = 0;
    const amount = Math.min(1, progress.current);
    if (Math.floor(before * 60) !== Math.floor(progress.current * 60) || progress.current < 0.02) drawArt(amount);
    if (pen.current) {
      const [u, v] = tip.current;
      pen.current.position.set((u - 0.5) * 1.6, (0.5 - v * 0.82) * 2.0, 0.26);
      pen.current.visible = amount < 1;
    }
    if (paper.current) paper.current.rotation.y = Math.sin(performance.now() / 2400) * 0.12;
  });
  return (
    <group rotation={[0, -0.25, 0.04]}>
      <group ref={paper}>
        {/* the flash sheet sits in front of a thick glass back, so the line work stays crisp */}
        <mesh position={[0, 0, 0.05]}><planeGeometry args={[1.6, 2.0]} /><meshStandardMaterial map={art} roughness={0.85} /></mesh>
        <RoundedBox args={[1.82, 2.22, 0.1]} radius={0.06} position={[0, 0, -0.03]}><Glass primary thickness={0.3} chroma={0.06} /></RoundedBox>
        <group ref={pen} rotation={[0, 0, -0.75]}>
          <mesh position={[0.22, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.05, 0.012, 0.3, 24]} /><Metal /></mesh>
          <mesh position={[0.55, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.075, 0.07, 0.4, 32]} /><Gloss color={accent} /></mesh>
          <mesh position={[0.95, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.085, 0.08, 0.42, 32]} /><meshPhysicalMaterial color="#1a1a1c" roughness={0.3} clearcoat={1} /></mesh>
        </group>
      </group>
      <Shadow y={-1.3} scale={2.4} opacity={0.25} />
    </group>
  );
}
