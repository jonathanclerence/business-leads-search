// Pets, food and drink, creative, professional, tech, and the fallback.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, rand, twoLines, useCanvasTexture, useCfg } from "../kit.jsx";
import { NamePlaque } from "./care.jsx";

const GOLD = "#d4af6a";

// ------------------------------------------------------------ pets
export function PetTag() {
  const { accent, name, displayFont } = useCfg();
  const bone = useMemo(() => {
    const s = new THREE.Shape();
    const L = 0.95, R = 0.3, w = 0.26;
    s.moveTo(-L, w);
    s.absarc(-L - 0.12, R * 0.75, R, -0.2, Math.PI * 1.35, false);
    s.absarc(-L - 0.12, -R * 0.75, R, Math.PI * 0.65, Math.PI * 2.2, false);
    s.lineTo(L, -w);
    s.absarc(L + 0.12, -R * 0.75, R, Math.PI * 1.2, Math.PI * 2.35 + Math.PI * 0.4, false);
    s.absarc(L + 0.12, R * 0.75, R, -Math.PI * 0.35, Math.PI * 1.2, false);
    s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.08, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.035, bevelSegments: 5, curveSegments: 40 });
  }, []);
  const engraving = useCanvasTexture(1024, 384, (ctx, w, h) => {
    ctx.fillStyle = "rgba(60,45,20,0.78)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l, displayFont, 600, lines.length > 1 ? 104 : 132, w * 0.6)));
    ctx.font = `600 ${size}px ${displayFont}`;
    lines.forEach((l, i) => ctx.fillText(l, w / 2, h / 2 + (i - (lines.length - 1) / 2) * size * 0.98));
  }, [name, displayFont]);
  const tag = useRef(), ball = useRef();
  useFrame((_, dt) => {
    const t = performance.now() / 1000;
    if (tag.current) { tag.current.rotation.y = Math.sin(t * 0.9) * 0.5 + input.px * 0.3; tag.current.rotation.z = Math.sin(t * 1.3) * 0.06; }
    if (ball.current) { const k = (t * 1.1) % 1, hgt = 4 * k * (1 - k); ball.current.position.y = -1.0 + hgt * 0.9; ball.current.rotation.z -= dt * 3; }
  });
  return (
    <group>
      <group ref={tag} position={[0, 0.35, 0]}>
        <mesh geometry={bone} position={[0, 0, -0.04]}><Metal color={GOLD} roughness={0.22} /></mesh>
        <mesh position={[0, 0, 0.085]}><planeGeometry args={[2.0, 0.75]} /><meshBasicMaterial map={engraving} transparent depthWrite={false} /></mesh>
        <mesh position={[-1.42, 0.62, 0]}><torusGeometry args={[0.12, 0.025, 12, 32]} /><Metal color={GOLD} /></mesh>
      </group>
      <group ref={ball} position={[1.05, -1.0, 0.5]}>
        <mesh><sphereGeometry args={[0.32, 48, 32]} /><Gloss color={accent} roughness={0.55} clearcoat={0.3} /></mesh>
        <mesh rotation={[0.6, 0, 0]}><torusGeometry args={[0.32, 0.012, 8, 64]} /><meshStandardMaterial color="#ffffff" /></mesh>
      </group>
      <Shadow y={-1.35} scale={2.6} opacity={0.22} />
      <Drift count={6} spread={[6, 4, 2]} speed={0.12} rise make={() => (<mesh scale={0.06}><sphereGeometry args={[1, 16, 12]} /><Gloss color={accent} /></mesh>)} />
    </group>
  );
}

// ------------------------------------------------------------ food & drink
export function Cup() {
  const { accent, name, displayFont } = useCfg();
  const cup = useMemo(() => {
    const pts = [new THREE.Vector2(0.001, -0.6), new THREE.Vector2(0.45, -0.6), new THREE.Vector2(0.55, -0.52)];
    for (let i = 0; i <= 12; i++) pts.push(new THREE.Vector2(0.55 + (i / 12) * 0.18, -0.52 + (i / 12) * 1.12));
    pts.push(new THREE.Vector2(0.7, 0.6), new THREE.Vector2(0.66, 0.58), new THREE.Vector2(0.52, -0.48), new THREE.Vector2(0.001, -0.48));
    return new THREE.LatheGeometry(pts, 72);
  }, []);
  const sleeve = useCanvasTexture(1024, 256, (ctx, w, h) => {
    ctx.fillStyle = accent; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    fitText(ctx, name, displayFont, 600, 110, w / 2 - 60); ctx.fillText(name, w / 4, h / 2 + 6); ctx.fillText(name, (w * 3) / 4, h / 2 + 6);
  }, [accent, name, displayFont]);
  const latte = useCanvasTexture(256, 256, (ctx, w) => {
    ctx.fillStyle = "#6b4630"; ctx.fillRect(0, 0, w, w);
    ctx.fillStyle = "#f3e6d4"; ctx.beginPath();
    const c = w / 2; ctx.moveTo(c, c + 60); ctx.bezierCurveTo(c - 110, c - 10, c - 40, c - 90, c, c - 30); ctx.bezierCurveTo(c + 40, c - 90, c + 110, c - 10, c, c + 60); ctx.fill();
  }, []);
  const puff = useCanvasTexture(128, 128, (ctx, w) => {
    const g = ctx.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    g.addColorStop(0, "rgba(255,255,255,0.9)"); g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, w);
  }, []);
  const steam = useRef();
  useFrame(() => { if (steam.current) steam.current.children.forEach((m, i) => { const k = ((performance.now() / 3200) + i / 5) % 1; m.position.y = 0.75 + k * 1.4; m.position.x = Math.sin(k * 5 + i) * 0.15; m.material.opacity = 0.55 * Math.sin(k * Math.PI); m.scale.setScalar(0.35 + k * 0.6); }); });
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2300) * 0.4 + input.px * 0.3; });
  return (
    <group position={[0, -0.25, 0]}>
      <group ref={g}>
        <mesh geometry={cup}><meshPhysicalMaterial color="#fbfaf7" roughness={0.25} clearcoat={0.8} side={THREE.DoubleSide} /></mesh>
        <mesh position={[0, 0.02, 0]}><cylinderGeometry args={[0.705, 0.665, 0.46, 72, 1, true]} /><meshStandardMaterial map={sleeve} roughness={0.7} side={THREE.DoubleSide} /></mesh>
        <mesh position={[0, 0.5, 0]} rotation={[-Math.PI / 2, 0, 0]}><circleGeometry args={[0.66, 64]} /><meshStandardMaterial map={latte} roughness={0.5} /></mesh>
        <mesh position={[0.78, 0.05, 0]}><torusGeometry args={[0.2, 0.055, 16, 40, Math.PI * 1.3]} /><meshPhysicalMaterial color="#fbfaf7" roughness={0.25} clearcoat={0.8} /></mesh>
        <mesh position={[0, -0.64, 0]}><cylinderGeometry args={[1.05, 0.9, 0.06, 72]} /><meshPhysicalMaterial color="#fbfaf7" roughness={0.3} clearcoat={0.6} /></mesh>
      </group>
      <group ref={steam}>{[0, 1, 2, 3, 4].map((i) => (<mesh key={i} position={[0, 1, 0.1]}><planeGeometry args={[1, 1]} /><meshBasicMaterial map={puff} transparent opacity={0.3} depthWrite={false} /></mesh>))}</group>
      <Drift count={12} spread={[6, 4, 2]} speed={0.15} make={() => (<mesh scale={[0.07, 0.1, 0.06]}><sphereGeometry args={[1, 16, 12]} /><meshPhysicalMaterial color="#4a2f20" roughness={0.4} clearcoat={0.6} /></mesh>)} />
      <Shadow y={-0.7} scale={2.6} />
    </group>
  );
}

export function Cloche() {
  const { accent } = useCfg();
  const dome = useRef();
  useFrame(() => { if (dome.current) dome.current.position.y = 0.05 + Math.max(0, Math.sin(performance.now() / 1400)) * 0.35 + input.tap * 0.6; });
  return (
    <group position={[0, -0.35, 0]} rotation={[0.18, 0, 0]}>
      <mesh position={[0, -0.55, 0]}><cylinderGeometry args={[1.45, 1.3, 0.08, 96]} /><meshPhysicalMaterial color="#fbfaf7" roughness={0.25} clearcoat={0.8} /></mesh>
      <mesh position={[0, -0.5, 0]}><cylinderGeometry args={[1.2, 1.2, 0.02, 96]} /><meshStandardMaterial color={accent} roughness={0.5} /></mesh>
      <group position={[0, -0.25, 0]}>
        <mesh><cylinderGeometry args={[0.55, 0.6, 0.45, 64]} /><meshPhysicalMaterial color="#f3e2c4" roughness={0.6} sheen={0.6} /></mesh>
        <mesh position={[0, 0.25, 0]}><cylinderGeometry args={[0.56, 0.56, 0.06, 64]} /><Gloss color={accent} roughness={0.3} /></mesh>
      </group>
      <group ref={dome}>
        <mesh><sphereGeometry args={[1.2, 64, 32, 0, Math.PI * 2, 0, Math.PI / 2]} /><Glass primary thickness={0.15} chroma={0.04} /></mesh>
        <mesh position={[0, 1.25, 0]}><sphereGeometry args={[0.1, 24, 16]} /><Metal color={GOLD} /></mesh>
      </group>
      <NamePlaque position={[1.45, -0.25, 0.7]} rotation={[0, -0.35, 0]} width={1.3} />
    </group>
  );
}

export function WineGlass() {
  const { accent } = useCfg();
  const glass = useMemo(() => {
    const pts = [new THREE.Vector2(0.55, -1.25), new THREE.Vector2(0.56, -1.22), new THREE.Vector2(0.05, -1.18), new THREE.Vector2(0.04, -0.2)];
    for (let i = 0; i <= 20; i++) { const t = i / 20; pts.push(new THREE.Vector2(0.04 + Math.sin(t * Math.PI * 0.62) * 0.62, -0.2 + t * 1.25)); }
    return new THREE.LatheGeometry(pts, 72);
  }, []);
  const wine = useRef();
  useFrame(() => { if (wine.current) { wine.current.rotation.z = Math.sin(performance.now() / 900) * 0.08 + input.px * 0.12; } });
  return (
    <group>
      <mesh geometry={glass}><Glass primary thickness={0.1} chroma={0.04} /></mesh>
      <mesh ref={wine} position={[0, 0.12, 0]}><sphereGeometry args={[0.52, 48, 32, 0, Math.PI * 2, Math.PI / 2.1, Math.PI / 2]} /><meshPhysicalMaterial color={accent} roughness={0.05} transmission={0.5} thickness={1} clearcoat={1} /></mesh>
      <Drift count={20} spread={[6, 4, 2]} speed={0.25} rise make={() => (<mesh scale={0.025}><sphereGeometry args={[1, 12, 8]} /><meshPhysicalMaterial transmission={1} roughness={0} thickness={0.1} /></mesh>)} />
      <NamePlaque position={[1.35, -0.85, 0.3]} rotation={[0, -0.4, 0]} width={1.35} />
      <Shadow y={-1.27} scale={1.8} />
    </group>
  );
}

// ------------------------------------------------------------ creative
export function Lens() {
  const { accent, name } = useCfg();
  const ring = useCanvasTexture(2048, 64, (ctx, w, h) => {
    ctx.fillStyle = "#151517"; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#e9e9e9"; ctx.font = "600 34px Geist, system-ui, sans-serif"; ctx.textBaseline = "middle";
    const text = `${name.toUpperCase()} · 50mm 1:1.4 · `; let x = 20; while (x < w) { ctx.fillText(text, x, h / 2 + 2); x += ctx.measureText(text).width; }
  }, [name]);
  const g = useRef();
  useFrame(() => { if (g.current) { g.current.rotation.y = Math.sin(performance.now() / 2200) * 0.5 - 0.3 + input.px * 0.3; g.current.rotation.x = Math.sin(performance.now() / 3000) * 0.15; } });
  const black = <meshPhysicalMaterial color="#141416" roughness={0.45} clearcoat={0.4} />;
  return (
    <group ref={g} rotation={[0, -0.3, 0]}>
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh position={[0, -0.4, 0]}><cylinderGeometry args={[0.95, 0.95, 0.9, 96]} />{black}</mesh>
        <mesh position={[0, 0.12, 0]}><cylinderGeometry args={[1.02, 1.02, 0.26, 96, 1, true]} /><meshStandardMaterial map={ring} roughness={0.5} /></mesh>
        <mesh position={[0, 0.3, 0]}><cylinderGeometry args={[1.0, 1.0, 0.12, 96]} /><Gloss color={accent} roughness={0.4} /></mesh>
        <mesh position={[0, -0.86, 0]}><cylinderGeometry args={[0.8, 0.8, 0.12, 96]} /><Metal /></mesh>
      </group>
      <mesh position={[0, 0, 0.37]}><sphereGeometry args={[0.85, 64, 32, 0, Math.PI * 2, 0, 0.6]} /><Glass primary thickness={0.4} chroma={0.1} tint="#e7f0ff" /></mesh>
      <mesh position={[0, 0, 0.25]}><circleGeometry args={[0.82, 64]} /><meshPhysicalMaterial color="#0d1120" roughness={0.1} clearcoat={1} iridescence={0.8} /></mesh>
    </group>
  );
}

export function Flowers() {
  const { accent } = useCfg();
  const heads = useMemo(() => [[0, 0.6, 0, 1], [-0.65, 0.2, -0.3, 0.75], [0.6, 0.3, -0.2, 0.8], [0.15, -0.1, 0.4, 0.6]], []);
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2400) * 0.4 + input.px * 0.3; });
  return (
    <group ref={g} position={[0, -0.1, 0]}>
      {heads.map(([x, y, z, s], k) => (
        <group key={k} position={[x, y, z]} scale={s}>
          {Array.from({ length: 10 }, (_, i) => { const a = (i / 10) * Math.PI * 2; return (
            <mesh key={i} position={[Math.cos(a) * 0.22, Math.sin(a) * 0.22, i % 2 * 0.04]} rotation={[0, 0, a]} scale={[0.32, 0.17, 0.08]}><sphereGeometry args={[1, 20, 12]} /><meshPhysicalMaterial color={k % 2 ? "#f6d6d6" : accent} roughness={0.5} sheen={1} sheenColor="#ffffff" /></mesh>
          ); })}
          <mesh position={[0, 0, 0.06]}><sphereGeometry args={[0.13, 20, 14]} /><meshStandardMaterial color="#e9c25a" roughness={0.6} /></mesh>
          <mesh position={[0, -0.75, -0.05]}><cylinderGeometry args={[0.02, 0.02, 1.3, 8]} /><meshStandardMaterial color="#5d8a46" /></mesh>
        </group>
      ))}
      <mesh position={[0, -1.15, 0]}><cylinderGeometry args={[0.42, 0.32, 0.8, 64]} /><Glass thickness={0.3} /></mesh>
      <Drift count={14} spread={[6, 4, 2]} speed={0.2} make={(p) => (<mesh scale={[0.1, 0.06, 0.02]}><sphereGeometry args={[1, 12, 8]} /><meshStandardMaterial color={p.i % 2 ? "#f6d6d6" : accent} /></mesh>)} />
      <NamePlaque position={[1.35, -1.1, 0.4]} rotation={[0, -0.4, 0]} width={1.3} />
    </group>
  );
}

export function Rings() {
  const g = useRef();
  useFrame((_, dt) => { if (g.current) { g.current.rotation.y += dt * (0.4 + input.tap * 3); } });
  return (
    <group>
      <group ref={g}>
        <mesh rotation={[0.3, 0, 0.5]} position={[-0.32, 0.1, 0]}><torusGeometry args={[0.62, 0.11, 32, 120]} /><Metal color={GOLD} roughness={0.15} /></mesh>
        <mesh rotation={[-0.4, 0.9, -0.3]} position={[0.32, -0.05, 0]}><torusGeometry args={[0.55, 0.09, 32, 120]} /><Metal color="#e8e8ea" roughness={0.12} /></mesh>
        <mesh position={[0.32, 0.5, 0.25]}><octahedronGeometry args={[0.16, 2]} /><Glass thickness={0.4} chroma={0.15} /></mesh>
      </group>
      <Drift count={14} spread={[6, 4, 2]} speed={0.2} make={(p) => (<mesh scale={[0.1, 0.06, 0.02]}><sphereGeometry args={[1, 12, 8]} /><meshStandardMaterial color={p.i % 2 ? "#f6e3e3" : "#ffffff"} /></mesh>)} />
      <NamePlaque position={[0, -1.4, 0.3]} width={1.8} />
    </group>
  );
}

// ------------------------------------------------------------ professional
export function Chart() {
  const { accent } = useCfg();
  const bars = useRef();
  const heights = useMemo(() => [0.6, 0.95, 0.8, 1.35, 1.8], []);
  useFrame(() => { if (bars.current) bars.current.children.forEach((m, i) => { const k = Math.min(1, Math.max(0, (performance.now() / 1000 - 0.3 - i * 0.15) / 1.2)); const e = 1 - Math.pow(1 - k, 3); m.scale.y = 0.02 + e * heights[i]; m.position.y = -1 + (m.scale.y * 1) / 2; }); });
  return (
    <group rotation={[0.1, -0.45, 0]}>
      <group ref={bars}>{heights.map((h, i) => (<mesh key={i} position={[-1 + i * 0.5, 0, 0]}><boxGeometry args={[0.36, 1, 0.36]} />{i === heights.length - 1 ? <Gloss color={accent} /> : <Glass thickness={0.4} />}</mesh>))}</group>
      {Array.from({ length: 6 }, (_, i) => (<mesh key={i} position={[1.0, -0.95 + i * 0.09, 0.6]} rotation={[0, 0, 0]}><cylinderGeometry args={[0.28, 0.28, 0.08, 48]} /><Metal color={GOLD} roughness={0.25} /></mesh>))}
      <NamePlaque position={[-0.2, -1.45, 0.5]} width={1.8} />
    </group>
  );
}

export function House() {
  const { accent } = useCfg();
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2300) * 0.5 + input.px * 0.3; });
  return (
    <group ref={g}>
      <RoundedBox args={[1.5, 1.1, 1.2]} radius={0.04} position={[0, -0.45, 0]}><Glass primary thickness={0.8} /></RoundedBox>
      <mesh position={[0, 0.45, 0]} rotation={[0, Math.PI / 4, 0]}><coneGeometry args={[1.2, 0.8, 4]} /><Gloss color={accent} /></mesh>
      <RoundedBox args={[0.3, 0.55, 0.05]} radius={0.02} position={[0, -0.72, 0.61]}><Gloss color={accent} /></RoundedBox>
      <group position={[1.1, -0.9, 0.6]} rotation={[0, 0, 0.6]} scale={0.35}>
        <mesh><torusGeometry args={[0.4, 0.12, 16, 40]} /><Metal color={GOLD} /></mesh>
        <mesh position={[1.0, 0, 0]}><boxGeometry args={[1.3, 0.16, 0.1]} /><Metal color={GOLD} /></mesh>
      </group>
      <NamePlaque position={[0, -1.55, 0.6]} width={1.8} />
    </group>
  );
}

// ------------------------------------------------------------ tech
function useScreen(w, h) {
  const { accent, name, displayFont, initials } = useCfg();
  return useCanvasTexture(w, h, (ctx) => {
    ctx.fillStyle = "#f7f5f1"; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = accent; ctx.beginPath(); ctx.arc(w / 2, h * 0.3, w * 0.16, 0, 7); ctx.fill();
    ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `600 ${w * 0.14}px ${displayFont}`; ctx.fillText(initials, w / 2, h * 0.3 + 4);
    ctx.fillStyle = "#161514"; const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l, displayFont, 600, w * 0.11, w * 0.84)));
    ctx.font = `600 ${size}px ${displayFont}`; lines.forEach((l, i) => ctx.fillText(l, w / 2, h * 0.5 + i * size * 1.05));
    ctx.fillStyle = accent; const bw = w * 0.7, bh = w * 0.13, by = h * 0.72; ctx.beginPath(); ctx.roundRect ? ctx.roundRect((w - bw) / 2, by, bw, bh, bh / 2) : ctx.rect((w - bw) / 2, by, bw, bh); ctx.fill();
    ctx.fillStyle = "#ffffff"; ctx.font = `600 ${w * 0.05}px Geist, system-ui, sans-serif`; ctx.fillText("Book a repair", w / 2, by + bh / 2 + 2);
  }, [accent, name, displayFont, initials]);
}

export function Phone() {
  const screen = useScreen(512, 1024);
  const g = useRef();
  useFrame(() => { if (g.current) { g.current.rotation.y = Math.sin(performance.now() / 2000) * 0.5 - 0.25 + input.px * 0.3; g.current.position.y = Math.sin(performance.now() / 900) * 0.05; } });
  return (
    <group ref={g} rotation={[0.1, 0, -0.08]}>
      <RoundedBox args={[1.15, 2.3, 0.1]} radius={0.14} smoothness={6}><Metal color="#2a2b2f" roughness={0.3} /></RoundedBox>
      <mesh position={[0, 0, 0.052]}><planeGeometry args={[1.04, 2.18]} /><meshBasicMaterial map={screen} toneMapped={false} /></mesh>
      <RoundedBox args={[1.08, 2.22, 0.02]} radius={0.12} position={[0, 0, 0.065]}><Glass thickness={0.05} chroma={0.04} /></RoundedBox>
      <Shadow y={-1.4} scale={1.8} />
    </group>
  );
}

export function Laptop() {
  const screen = useScreen(1024, 640);
  const lid = useRef();
  useFrame(() => { if (lid.current) lid.current.rotation.x = -1.85 + Math.sin(performance.now() / 2600) * 0.06; });
  return (
    <group rotation={[0.25, -0.5, 0]} position={[0, -0.4, 0]}>
      <RoundedBox args={[2.4, 0.08, 1.6]} radius={0.03}><Metal color="#c8ccd2" roughness={0.3} /></RoundedBox>
      <group ref={lid} position={[0, 0.04, -0.8]}>
        <group position={[0, 0, 0.78]}>
          <RoundedBox args={[2.4, 1.56, 0.05]} radius={0.03}><Metal color="#c8ccd2" roughness={0.3} /></RoundedBox>
          <mesh position={[0, 0, -0.027]} rotation={[0, Math.PI, 0]}><planeGeometry args={[2.25, 1.4]} /><meshBasicMaterial map={screen} toneMapped={false} /></mesh>
        </group>
      </group>
      <Shadow y={-0.1} scale={2.8} />
    </group>
  );
}

// ------------------------------------------------------------ everyone else
export function Plaque() {
  const { accent, initials, displayFont } = useCfg();
  const mono = useCanvasTexture(512, 512, (ctx, w) => {
    ctx.fillStyle = accent; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `600 ${w * 0.45}px ${displayFont}`; ctx.fillText(initials, w / 2, w / 2 + 10);
  }, [accent, initials, displayFont]);
  const g = useRef();
  useFrame(() => { if (g.current) g.current.rotation.y = Math.sin(performance.now() / 2100) * 0.5 + input.px * 0.3; });
  return (
    <group>
      <group ref={g}>
        <mesh position={[0, 0.2, -0.12]}><planeGeometry args={[1.6, 1.6]} /><meshBasicMaterial map={mono} transparent toneMapped={false} /></mesh>
        <RoundedBox args={[1.9, 1.9, 0.3]} radius={0.12} smoothness={6} position={[0, 0.2, 0.05]}><Glass primary thickness={0.6} chroma={0.06} /></RoundedBox>
      </group>
      <Drift count={12} spread={[6, 4, 2]} speed={0.12} rise make={(p) => (<mesh scale={0.06 + (p.i % 3) * 0.03}><sphereGeometry args={[1, 20, 14]} /><Glass thickness={0.2} /></mesh>)} />
      <NamePlaque position={[0, -1.3, 0.4]} width={1.8} />
    </group>
  );
}
