// Barbers and hair salons.
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Drift, Glass, Gloss, Metal, Shadow, fitText, input, strandGeometry, twoLines, useCanvasTexture, useCfg } from "../kit.jsx";

const HAIR = ["#2a1c14", "#3b2719", "#5a3a25", "#83563a", "#1c1a19"];

export function FallingHair({ count = 34 }) {
  return (
    <Drift count={count} spread={[7, 5, 3]} speed={0.32} make={(p) => (
      <mesh geometry={strandGeometry(p.i)}>
        <meshStandardMaterial color={HAIR[p.i % HAIR.length]} roughness={0.6} />
      </mesh>
    )} />
  );
}

/** A name plate: the business name in the page's display face. */
function useNamePlate(w = 1024, h = 360, { bg = "#f4efe6", ink = "#1b1b1b", sub } = {}) {
  const { name, displayFont, suburb } = useCfg();
  return useCanvasTexture(w, h, (ctx) => {
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = ink; ctx.globalAlpha = 0.85; ctx.lineWidth = 6; ctx.strokeRect(22, 22, w - 44, h - 44);
    ctx.globalAlpha = 1; ctx.fillStyle = ink; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const lines = twoLines(name);
    const size = Math.min(...lines.map((l) => fitText(ctx, l, displayFont, 600, lines.length > 1 ? 130 : 160, w - 130)));
    ctx.font = `600 ${size}px ${displayFont}`;
    const top = h / 2 - (lines.length - 1) * size * 0.5 - (sub !== false ? 26 : 0);
    lines.forEach((l, i) => ctx.fillText(l, w / 2, top + i * size * 1.0));
    if (sub !== false) {
      ctx.font = `500 34px Geist, system-ui, sans-serif`;
      ctx.globalAlpha = 0.7; ctx.fillText((sub || suburb || "").toUpperCase().split("").join(" "), w / 2, h - 66);
    }
  }, [name, displayFont, bg, ink, sub]);
}

// ---------------------------------------------------------------- barber
export function BarberPole() {
  const { accent } = useCfg();
  const stripes = useCanvasTexture(256, 256, (ctx, w) => {
    const cols = [accent, "#ffffff", "#c8102e", "#ffffff"];
    const P = w / 4;
    for (let k = -8; k < 8; k++) {
      ctx.fillStyle = cols[((k % 4) + 4) % 4];
      ctx.beginPath();
      ctx.moveTo(k * P, 0); ctx.lineTo(k * P + P, 0); ctx.lineTo(k * P + P + w, w); ctx.lineTo(k * P + w, w);
      ctx.closePath(); ctx.fill();
    }
  }, [accent]);
  useMemo(() => { stripes.wrapS = stripes.wrapT = THREE.RepeatWrapping; stripes.repeat.set(1, 2.4); }, [stripes]);
  const plate = useNamePlate(1024, 400, { bg: "#f6f1e7", ink: "#111111" });
  const spin = useRef(0), sign = useRef();
  useFrame((_, dt) => {
    spin.current += dt * (0.22 + input.tap * 1.5);
    stripes.offset.y = -spin.current;
    if (sign.current) sign.current.rotation.z = Math.sin(performance.now() / 900) * 0.035 + input.px * 0.04;
  });
  return (
    <group rotation={[0, 0, 0.06]}>
      {/* striped core + glass tube */}
      <mesh><cylinderGeometry args={[0.34, 0.34, 2.05, 64, 1, true]} /><meshStandardMaterial map={stripes} roughness={0.35} /></mesh>
      <mesh><cylinderGeometry args={[0.42, 0.42, 2.15, 64, 1, true]} /><Glass primary thickness={0.25} chroma={0.03} /></mesh>
      {/* chrome caps */}
      <mesh position={[0, 1.13, 0]}><cylinderGeometry args={[0.48, 0.48, 0.14, 64]} /><Metal /></mesh>
      <mesh position={[0, 1.2, 0]}><sphereGeometry args={[0.42, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2]} /><Metal /></mesh>
      <mesh position={[0, 1.66, 0]}><sphereGeometry args={[0.07, 24, 16]} /><Metal /></mesh>
      <mesh position={[0, -1.13, 0]}><cylinderGeometry args={[0.48, 0.48, 0.14, 64]} /><Metal /></mesh>
      <mesh position={[0, -1.2, 0]} rotation={[Math.PI, 0, 0]}><sphereGeometry args={[0.42, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2]} /><Metal /></mesh>
      {/* the shop sign hanging off a bracket, with their name on it */}
      <mesh position={[0.86, 0.86, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.025, 0.025, 1.1, 16]} /><Metal color="#2b2b2b" /></mesh>
      <group ref={sign} position={[1.3, 0.84, 0]}>
        <mesh position={[-0.3, -0.12, 0]}><cylinderGeometry args={[0.008, 0.008, 0.24, 8]} /><Metal color="#2b2b2b" /></mesh>
        <mesh position={[0.3, -0.12, 0]}><cylinderGeometry args={[0.008, 0.008, 0.24, 8]} /><Metal color="#2b2b2b" /></mesh>
        <RoundedBox args={[1.18, 0.48, 0.04]} radius={0.02} position={[0, -0.48, 0]}>
          <meshStandardMaterial color="#efe9de" roughness={0.6} />
        </RoundedBox>
        <mesh position={[0, -0.48, 0.022]}><planeGeometry args={[1.15, 0.45]} /><meshStandardMaterial map={plate} roughness={0.5} /></mesh>
        <mesh position={[0, -0.48, -0.022]} rotation={[0, Math.PI, 0]}><planeGeometry args={[1.15, 0.45]} /><meshStandardMaterial map={plate} roughness={0.5} /></mesh>
      </group>
      <Shadow y={-1.75} scale={1.6} />
      <FallingHair count={18} />
    </group>
  );
}

// ---------------------------------------------------------------- scissors
function bladeGeometry(len) {
  const s = new THREE.Shape();
  s.moveTo(-0.08, -0.07);
  s.bezierCurveTo(len * 0.3, -0.13, len * 0.75, -0.08, len, -0.005);
  s.quadraticCurveTo(len + 0.02, 0.01, len, 0.02);
  s.bezierCurveTo(len * 0.7, 0.045, len * 0.3, 0.06, -0.08, 0.055);
  s.closePath();
  return new THREE.ExtrudeGeometry(s, { depth: 0.025, bevelEnabled: true, bevelThickness: 0.01, bevelSize: 0.008, bevelSegments: 3, curveSegments: 32 });
}

export function Scissors() {
  const { accent, name, displayFont } = useCfg();
  const blade = useMemo(() => bladeGeometry(1.75), []);
  const shank = useMemo(() => new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(-0.05, 0, 0), new THREE.Vector3(-0.35, 0.02, 0), new THREE.Vector3(-0.6, 0.16, 0)), 24, 0.04, 12, false), []);
  const halves = [useRef(), useRef()];
  const t = useRef(0);
  useFrame((_, dt) => {
    t.current += dt * (1 + input.tap * 3);
    const ph = (t.current % 1.8) / 1.8;
    const open = ph < 0.45 ? 0.5 : ph < 0.62 ? 0.5 - 0.44 * (ph - 0.45) / 0.17 : ph < 0.8 ? 0.06 : 0.06 + 0.44 * (ph - 0.8) / 0.2;
    if (halves[0].current) halves[0].current.rotation.z = open / 2;
    if (halves[1].current) halves[1].current.rotation.z = -open / 2;
  });
  // A clear acrylic comb with the salon's name printed along the spine.
  const comb = useMemo(() => {
    const s = new THREE.Shape();
    s.moveTo(-1.1, 0); s.lineTo(1.1, 0); s.lineTo(1.1, 0.22);
    for (let i = 0; i < 30; i++) { const x = 1.1 - i * 0.0733; s.lineTo(x, 0.22); s.lineTo(x - 0.012, 0.62); s.lineTo(x - 0.045, 0.62); s.lineTo(x - 0.05, 0.22); }
    s.lineTo(-1.1, 0.22); s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.05, bevelEnabled: true, bevelThickness: 0.012, bevelSize: 0.01, bevelSegments: 2 });
  }, []);
  const print = useCanvasTexture(1024, 128, (ctx, w, h) => {
    ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    fitText(ctx, name, displayFont, 500, 84, w - 80); ctx.fillText(name, w / 2, h / 2 + 4);
  }, [name, displayFont]);
  return (
    <group rotation={[0.15, -0.35, 0]}>
      <group rotation={[0, 0, 2.55]} position={[0.25, 0.25, 0.3]}>
        {[1, -1].map((side, k) => (
          <group key={side} ref={halves[k]}>
            <mesh geometry={blade} scale={[1, side, 1]} position={[0, 0, side > 0 ? 0.03 : -0.03]}><Metal roughness={0.16} /></mesh>
            <mesh geometry={shank} scale={[1, side, 1]}><Gloss color={accent} /></mesh>
            <mesh position={[-0.86, side * 0.3, 0]} rotation={[0, 0, side * 0.5]} scale={[1, 0.78, 1]}>
              <torusGeometry args={[0.27, 0.055, 20, 64]} /><Gloss color={accent} />
            </mesh>
          </group>
        ))}
        <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.06, 0.06, 0.13, 32]} /><Metal /></mesh>
      </group>
      <group position={[-0.1, -1.0, -0.25]} rotation={[0, 0, -0.18]}>
        <mesh geometry={comb}><Glass primary thickness={0.1} tint={accent} chroma={0.06} /></mesh>
        <mesh position={[0, 0.11, 0.066]}><planeGeometry args={[2.1, 0.2]} /><meshBasicMaterial map={print} transparent depthWrite={false} /></mesh>
      </group>
      <Shadow y={-1.6} scale={2.4} opacity={0.22} />
      <FallingHair count={34} />
    </group>
  );
}
