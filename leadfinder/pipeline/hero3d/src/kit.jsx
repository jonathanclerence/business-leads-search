// Shared pieces for the hero scenes: quality settings, materials, printed
// labels (the business's own name in the page's fonts), shadows, particles.
import { createContext, useContext, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { MeshTransmissionMaterial } from "@react-three/drei";

export const Cfg = createContext(null);
export const useCfg = () => useContext(Cfg);

// Live input shared with every scene (written by the page, read in useFrame).
export const input = { px: 0, py: 0, scroll: 0, tap: 0 };

export function rand(a, b) { return a + Math.random() * (b - a); }

/** Glass. The scene's one `primary` piece gets drei's refracting transmission
 *  material (chromatic aberration, distortion), which re-renders the scene into
 *  its own buffer every frame, so everything else uses three's physical
 *  transmission, which shares a single pass. Phones and slow frames get the
 *  cheap one everywhere. */
export function Glass({ primary = false, thickness = 0.5, tint = "#ffffff", roughness = 0.04, ior = 1.45, chroma = 0.04, ...rest }) {
  const { quality } = useCfg();
  if (quality.lite || !primary) {
    return <meshPhysicalMaterial transmission={1} thickness={thickness} roughness={roughness} ior={ior}
      color={tint} metalness={0} clearcoat={1} clearcoatRoughness={0.05} envMapIntensity={1.2} {...rest} />;
  }
  return <MeshTransmissionMaterial samples={quality.samples} resolution={quality.res} thickness={thickness}
    roughness={roughness} ior={ior} chromaticAberration={chroma} anisotropicBlur={0.06} distortion={0.08}
    distortionScale={0.25} temporalDistortion={0.04} color={tint} backside={false} {...rest} />;
}

export function Metal({ color = "#d9dde2", roughness = 0.22 }) {
  return <meshStandardMaterial color={color} metalness={1} roughness={roughness} envMapIntensity={1.3} />;
}

/** Glossy painted surface in the page accent. */
export function Gloss({ color, roughness = 0.28, clearcoat = 1 }) {
  return <meshPhysicalMaterial color={color} roughness={roughness} clearcoat={clearcoat} clearcoatRoughness={0.08} envMapIntensity={1.1} />;
}

/** A canvas texture drawn with the page's own (already loaded) fonts.
 *  `draw(ctx, w, h)` runs once now and again when the web fonts are ready. */
export function useCanvasTexture(w, h, draw, deps) {
  const tex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [w, h]);
  useEffect(() => {
    let alive = true;
    const paint = () => {
      if (!alive) return;
      const ctx = tex.image.getContext("2d");
      ctx.clearRect(0, 0, w, h);
      draw(ctx, w, h);
      tex.needsUpdate = true;
    };
    paint();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(paint);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => () => tex.dispose(), [tex]);
  return tex;
}

/** Fit `text` on one line inside maxW, shrinking from `size`. */
export function fitText(ctx, text, family, weight, size, maxW, style = "") {
  let s = size;
  do { ctx.font = `${style} ${weight} ${s}px ${family}`.trim(); s -= 2; } while (ctx.measureText(text).width > maxW && s > 10);
  return s + 2;
}

/** Split a name over at most two balanced lines. */
export function twoLines(name) {
  const words = name.split(/\s+/);
  if (name.length < 14 || words.length < 2) return [name];
  let best = [name], diff = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" "), b = words.slice(i).join(" ");
    const d = Math.abs(a.length - b.length);
    if (d < diff) { diff = d; best = [a, b]; }
  }
  return best;
}

/** Soft round shadow on the "floor" (a texture, so it costs nothing per frame). */
export function Shadow({ y = -1.4, scale = 2.2, opacity = 0.32 }) {
  const tex = useCanvasTexture(128, 128, (ctx, w) => {
    const g = ctx.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    g.addColorStop(0, "rgba(0,0,0,1)"); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, w);
  }, []);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]} scale={[scale, scale * 0.55, 1]} renderOrder={-1}>
      <planeGeometry />
      <meshBasicMaterial map={tex} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  );
}

/** Things that fall (hair, petals, leaves) or rise (bubbles, steam), with depth. */
export function Drift({ count = 30, make, rise = false, spread = [6, 4, 3], speed = 0.35, children }) {
  const group = useRef();
  const items = useMemo(() => Array.from({ length: count }, (_, i) => ({
    x: rand(-spread[0] / 2, spread[0] / 2), y: rand(-spread[1] / 2, spread[1] / 2), z: rand(-spread[2], 0.8),
    rx: rand(0, 6.28), ry: rand(0, 6.28), vr: rand(-1, 1), v: rand(0.6, 1.4), ph: rand(0, 6.28), i,
  })), [count, spread]);
  useFrame((_, dt) => {
    const g = group.current; if (!g) return;
    g.children.forEach((m, i) => {
      const p = items[i]; if (!p) return;
      p.ph += dt;
      p.y += (rise ? 1 : -1) * speed * p.v * dt;
      p.x += Math.sin(p.ph * 0.9) * 0.12 * dt + input.px * 0.05 * dt;
      p.rx += p.vr * dt * 0.8; p.ry += p.vr * dt * 0.5;
      if (!rise && p.y < -spread[1] / 2 - 0.5) { p.y = spread[1] / 2 + 0.5; p.x = rand(-spread[0] / 2, spread[0] / 2); }
      if (rise && p.y > spread[1] / 2 + 0.5) { p.y = -spread[1] / 2 - 0.5; p.x = rand(-spread[0] / 2, spread[0] / 2); }
      m.position.set(p.x, p.y, p.z);
      m.rotation.set(p.rx, p.ry, 0);
    });
  });
  return <group ref={group}>{items.map((p) => <group key={p.i}>{make ? make(p) : children}</group>)}</group>;
}

/** A thin curved strand of hair (shared geometry per shape). */
const strandGeoms = [];
export function strandGeometry(i) {
  if (!strandGeoms.length) {
    for (let k = 0; k < 6; k++) {
      const len = rand(0.22, 0.5), bend = rand(-0.12, 0.12);
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(0, -len / 2, 0), new THREE.Vector3(bend, 0, bend * 0.5), new THREE.Vector3(0, len / 2, 0));
      strandGeoms.push(new THREE.TubeGeometry(curve, 12, 0.0055, 4, false));
    }
  }
  return strandGeoms[i % strandGeoms.length];
}

/** Ease towards a target every frame (frame-rate independent). */
export function damp(current, target, lambda, dt) { return THREE.MathUtils.damp(current, target, lambda, dt); }
