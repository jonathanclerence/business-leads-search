// Massage, wellness and health care.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, twoLines, useCanvasTexture, useCfg } from "../kit.jsx";

/** A standing glass plaque with the business name etched into it. */
export function NamePlaque({ position = [0, 0, 0], rotation = [0, 0, 0], width = 1.5, height = 0.62 }) {
  const { name, displayFont, suburb, dark } = useCfg();
  const etch = useCanvasTexture(1024, 420, (ctx, w, h) => {
    ctx.fillStyle = dark ? "rgba(255,255,255,0.92)" : "rgba(20,20,20,0.86)";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l, displayFont, 500, lines.length > 1 ? 120 : 150, w - 120)));
    ctx.font = `500 ${size}px ${displayFont}`;
    lines.forEach((l, i) => ctx.fillText(l, w / 2, h / 2 - (lines.length - 1) * size * 0.48 + i * size * 0.96 - 18));
    ctx.globalAlpha = 0.6; ctx.font = "500 32px Geist, system-ui, sans-serif";
    ctx.fillText((suburb || "").toUpperCase().split("").join(" "), w / 2, h - 46);
  }, [name, displayFont, suburb, dark]);
  return (
    <group position={position} rotation={rotation}>
      <RoundedBox args={[width, height, 0.06]} radius={0.03}><Glass thickness={0.12} chroma={0.04} /></RoundedBox>
      <mesh position={[0, 0, 0.035]}><planeGeometry args={[width * 0.94, height * 0.94]} /><meshBasicMaterial map={etch} transparent depthWrite={false} /></mesh>
    </group>
  );
}

// ------------------------------------------------------------ massage / spa
export function Stones() {
  const { accent } = useCfg();
  const tones = ["#8f8a80", "#a9a397", "#7a756c", "#bdb7ab"];
  const stones = [[1.25, 0.42, 0.95], [1.0, 0.36, 0.8], [0.78, 0.3, 0.62], [0.5, 0.22, 0.42]];
  const refs = stones.map(() => useRef()); // eslint-disable-line react-hooks/rules-of-hooks
  const ripples = [useRef(), useRef(), useRef()];
  const t0 = useRef(0);
  useFrame((_, dt) => {
    t0.current += dt;
    refs.forEach((r, i) => { if (r.current) { r.current.rotation.y = Math.sin(t0.current * 0.5 + i) * 0.15; r.current.position.x = Math.sin(t0.current * 0.7 + i * 1.3) * 0.02 * (i + 1); } });
    ripples.forEach((r, i) => {
      if (!r.current) return;
      const k = ((t0.current * 0.28 + i / 3 + input.tap * 0.2) % 1);
      r.current.scale.setScalar(0.6 + k * 2.2); r.current.material.opacity = 0.45 * (1 - k);
    });
  });
  let y = -0.9;
  return (
    <group position={[0, 0.1, 0]}>
      <mesh position={[0, -1.12, 0]}><cylinderGeometry args={[1.35, 1.35, 0.06, 96]} /><Glass thickness={0.2} tint="#f4fbfb" roughness={0.08} /></mesh>
      {ripples.map((r, i) => (
        <mesh key={i} ref={r} rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.07, 0]}><ringGeometry args={[0.7, 0.715, 96]} /><meshBasicMaterial color={accent} transparent opacity={0.3} depthWrite={false} /></mesh>
      ))}
      {stones.map(([w, h, d], i) => {
        const cy = y + h / 2; y += h * 0.86;
        return (
          <mesh key={i} ref={refs[i]} position={[0, cy, 0]} scale={[w, h, d]}>
            <sphereGeometry args={[0.5, 64, 32]} />
            <meshPhysicalMaterial color={tones[i]} roughness={0.55} clearcoat={0.35} clearcoatRoughness={0.4} />
          </mesh>
        );
      })}
      <NamePlaque position={[0.55, -1.05, 1.2]} rotation={[0, -0.25, 0]} width={1.3} />
      <Drift count={8} spread={[6, 4, 2]} speed={0.15} make={(p) => (
        <mesh scale={[0.16, 0.06, 0.02]}><sphereGeometry args={[1, 16, 8]} /><meshStandardMaterial color={p.i % 2 ? "#7f9a7b" : "#a8bf9f"} roughness={0.6} /></mesh>
      )} />
    </group>
  );
}

// ------------------------------------------------------------ health
export function HealthCross() {
  const { accent } = useCfg();
  const g = useRef(), pulse = useRef();
  useFrame((_, dt) => {
    if (g.current) g.current.rotation.y += dt * (0.25 + input.tap * 3);
    if (pulse.current) { const k = (performance.now() / 1300) % 1; pulse.current.scale.setScalar(1 + k * 1.2); pulse.current.material.opacity = 0.4 * (1 - k); }
  });
  return (
    <group>
      <group ref={g}>
        <RoundedBox args={[0.62, 1.9, 0.62]} radius={0.12} smoothness={5}><Glass thickness={0.9} tint="#ffffff" /></RoundedBox>
        <RoundedBox args={[1.9, 0.62, 0.62]} radius={0.12} smoothness={5}><Glass thickness={0.9} tint="#ffffff" /></RoundedBox>
        <RoundedBox args={[0.3, 1.2, 0.3]} radius={0.08}><Gloss color={accent} /></RoundedBox>
        <RoundedBox args={[1.2, 0.3, 0.3]} radius={0.08}><Gloss color={accent} /></RoundedBox>
      </group>
      <mesh ref={pulse} position={[0, 0, -0.6]}><ringGeometry args={[1.3, 1.33, 96]} /><meshBasicMaterial color={accent} transparent depthWrite={false} /></mesh>
      <NamePlaque position={[0, -1.55, 0.4]} width={1.7} />
      <Shadow y={-1.95} scale={2.2} opacity={0.2} />
    </group>
  );
}

export function Tooth() {
  const { accent } = useCfg();
  const geom = useMemo(() => {
    // A friendly molar: a rounded crown with two tapering roots, built from a lathe and merged parts.
    const pts = [];
    for (let i = 0; i <= 30; i++) { const t = i / 30, a = t * Math.PI; pts.push(new THREE.Vector2(Math.sin(a) * (0.62 + 0.08 * Math.sin(a * 3)), Math.cos(a) * 0.5)); }
    return new THREE.LatheGeometry(pts, 64);
  }, []);
  const g = useRef();
  useFrame((_, dt) => { if (g.current) g.current.rotation.y += dt * (0.3 + input.tap * 3); });
  const white = <meshPhysicalMaterial color="#fbfbf8" roughness={0.18} clearcoat={1} clearcoatRoughness={0.05} sheen={0.4} />;
  return (
    <group>
      <group ref={g} position={[0, 0.25, 0]}>
        <mesh geometry={geom} scale={[1, 1.05, 0.9]}>{white}</mesh>
        {[-0.3, 0.3].map((x) => (
          <mesh key={x} position={[x, -0.75, 0]} rotation={[0, 0, x * 0.35]}><coneGeometry args={[0.24, 0.9, 32]} />{white}</mesh>
        ))}
        <mesh position={[0.32, 0.25, 0.48]}><sphereGeometry args={[0.07, 16, 12]} /><meshBasicMaterial color="#ffffff" /></mesh>
      </group>
      <Drift count={10} spread={[6, 4, 2]} speed={0.12} rise make={() => (
        <mesh scale={0.07}><sphereGeometry args={[1, 20, 14]} /><meshPhysicalMaterial transmission={1} thickness={0.3} roughness={0.02} iridescence={1} /></mesh>
      )} />
      <NamePlaque position={[0, -1.65, 0.3]} width={1.7} />
      <mesh position={[0, 0.2, -0.8]}><circleGeometry args={[1.25, 64]} /><meshBasicMaterial color={accent} transparent opacity={0.12} depthWrite={false} /></mesh>
    </group>
  );
}

export function Glasses() {
  const { accent } = useCfg();
  const g = useRef();
  useFrame((_, dt) => {
    if (!g.current) return;
    g.current.rotation.y = Math.sin(performance.now() / 1800) * 0.45 + input.px * 0.3;
    g.current.rotation.x = Math.sin(performance.now() / 2500) * 0.1;
  });
  return (
    <group>
      <group ref={g} position={[0, 0.25, 0]}>
        {[-0.62, 0.62].map((x) => (
          <group key={x} position={[x, 0, 0]}>
            <mesh scale={[1.12, 0.92, 1]}><torusGeometry args={[0.48, 0.06, 20, 80]} /><Gloss color={accent} /></mesh>
            <mesh scale={[1.12, 0.92, 1]}><circleGeometry args={[0.47, 64]} /><Glass thickness={0.25} chroma={0.08} /></mesh>
          </group>
        ))}
        <mesh position={[0, 0.16, 0]}><torusGeometry args={[0.13, 0.04, 12, 32, Math.PI]} /><Gloss color={accent} /></mesh>
        {[-1, 1].map((s) => (
          <mesh key={s} position={[s * 1.18, 0.08, -0.6]} rotation={[0, s * 0.05, 0]}><boxGeometry args={[0.06, 0.07, 1.2]} /><Gloss color={accent} /></mesh>
        ))}
      </group>
      <NamePlaque position={[0, -1.25, 0.3]} width={1.8} />
    </group>
  );
}
