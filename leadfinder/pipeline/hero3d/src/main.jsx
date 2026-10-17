// 3D hero for the preview websites, built with React Three Fiber.
// Loaded lazily by hero.js (only after the page is usable, only on devices
// that can afford it). Everything is drawn in code: no models, no HDRs, no
// network, no eval, no workers (the site's CSP allows none of those).
import { StrictMode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { Cfg, damp, input } from "./kit.jsx";
import { BarberPole, Scissors } from "./scenes/hair.jsx";
import { PolishBottle, Serum, TattooFlash } from "./scenes/beauty.jsx";
import { Glasses, HealthCross, Stones, Tooth } from "./scenes/care.jsx";
import { Books, Kettlebell, MusicNotes, PilatesRing, SteeringWheel, Tyre } from "./scenes/active.jsx";
import { Boxes, Bubbles, Bulb, Fan, Key, Pipes, Roller, Terrarium, Tools } from "./scenes/trades.jsx";
import { Chart, Cloche, Cup, Flowers, House, Laptop, Lens, PetTag, Phone, Plaque, Rings, WineGlass } from "./scenes/life.jsx";

const BY_KIND = {
  barber: BarberPole, "hair-salon": Scissors,
  "nail-salon": PolishBottle, "beauty-salon": Serum, "day-spa": Serum, tattoo: TattooFlash,
  massage: Stones, acupuncture: Stones, naturopath: Stones,
  physio: HealthCross, chiropractor: HealthCross, podiatrist: HealthCross, psychologist: HealthCross,
  "speech-pathologist": HealthCross, medical: HealthCross, dentist: Tooth, optometrist: Glasses,
  "personal-trainer": Kettlebell, gym: Kettlebell, pilates: PilatesRing, yoga: PilatesRing,
  "dance-school": MusicNotes, "music-teacher": MusicNotes, tutoring: Books, childcare: Books, "swim-school": Bubbles,
  "driving-school": SteeringWheel, mechanic: Tyre, "mobile-mechanic": Tyre, "auto-electrician": Tyre,
  "panel-beater": Tyre, tyres: Tyre, windscreen: Tyre, "car-detailing": Bubbles, "car-wash": Bubbles,
  plumber: Pipes, electrician: Bulb, painter: Roller, locksmith: Key, "air-conditioning": Fan, "appliance-repair": Fan,
  handyman: Tools, "pest-control": Tools, cleaning: Bubbles, "carpet-cleaning": Bubbles, removalist: Boxes, "skip-bin": Boxes,
  "lawn-mowing": Terrarium, gardening: Terrarium, landscaping: Terrarium, "tree-removal": Terrarium,
  "pet-grooming": PetTag, "dog-walker": PetTag, "pet-sitter": PetTag, vet: PetTag,
  cafe: Cup, restaurant: Cloche, bakery: Cloche, butcher: Cloche, "fish-and-chips": Cloche, pizza: Cloche, caterer: Cloche,
  winery: WineGlass, brewery: WineGlass,
  photographer: Lens, florist: Flowers, celebrant: Rings,
  bookkeeper: Chart, accountant: Chart, "mortgage-broker": House,
  "computer-repair": Laptop, "phone-repair": Phone, local: Plaque,
};

function Environment() {
  const { gl, scene } = useThree();
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    return () => { scene.environment = null; env.dispose(); pmrem.dispose(); };
  }, [gl, scene]);
  return null;
}

/** Places the object beside the text (desktop) or in the stage under it (phone),
 *  rises it in, tilts it towards the pointer and drifts it with the scroll. */
function Rig({ children }) {
  const ref = useRef();
  const { viewport, size } = useThree();
  const mobile = size.width < 900;
  const born = useRef(performance.now());
  useFrame((_, dt) => {
    const g = ref.current; if (!g) return;
    const k = Math.min(1, (performance.now() - born.current) / 1400), e = 1 - Math.pow(1 - k, 3);
    const s = (mobile ? Math.min(0.66, viewport.width / 4.8) : Math.min(0.84, viewport.width / 7.4)) * (0.86 + 0.14 * e);
    const x = mobile ? viewport.width * 0.08 : viewport.width * 0.23;
    const y = (mobile ? -viewport.height * 0.31 : 0) + (1 - e) * -0.4 + input.scroll * 1.6;
    g.scale.setScalar(s);
    g.position.x = damp(g.position.x, x + input.px * 0.12, 4, dt);
    g.position.y = damp(g.position.y, y, 6, dt);
    g.rotation.y = damp(g.rotation.y, input.px * 0.35 + input.scroll * 0.6, 3, dt);
    g.rotation.x = damp(g.rotation.x, -input.py * 0.18, 3, dt);
    input.tap = Math.max(0, input.tap - dt * 1.4);
  });
  return <group ref={ref}>{children}</group>;
}

function App({ cfg, active }) {
  const [accent, setAccent] = useState(cfg.accent);
  const [dark, setDark] = useState(cfg.dark);
  const [paper, setPaper] = useState(cfg.paper || "#f1efeb");
  const [lite, setLite] = useState(cfg.lite);
  useEffect(() => {
    const root = document.documentElement;
    const read = () => {
      const a = getComputedStyle(root).getPropertyValue("--accent").trim();
      if (/^#[0-9a-f]{6}$/i.test(a)) setAccent(a);
      const p = getComputedStyle(root).getPropertyValue("--paper").trim();
      if (/^#[0-9a-f]{3,8}$/i.test(p)) setPaper(p);
      setDark(root.dataset.paper === "dark");
    };
    const mo = new MutationObserver(read);
    mo.observe(root, { attributes: true, attributeFilter: ["style", "data-paper"] });
    read();
    return () => mo.disconnect();
  }, []);
  const Scene = BY_KIND[cfg.kind] || Plaque;
  const value = useMemo(() => ({
    ...cfg, accent, dark,
    quality: lite ? { lite: true } : { lite: false, samples: cfg.mobile ? 4 : 6, res: cfg.mobile ? 256 : 512 },
  }), [cfg, accent, dark, lite]);
  return (
    <Canvas
      dpr={cfg.mobile ? [1, 1.5] : [1, 1.75]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ position: [0, 0, 7.2], fov: 30 }}
      frameloop={active ? "always" : "never"}
      onCreated={({ gl }) => { gl.toneMapping = THREE.ACESFilmicToneMapping; gl.toneMappingExposure = 1.05; cfg.onReady && cfg.onReady(); }}
    >
      <PerformanceMonitor onDecline={() => setLite(true)} flipflops={2} />
      {/* The hero is a plain field of the page colour, so the scene paints the
          same colour: glass then refracts the page instead of black. */}
      <color attach="background" args={[paper]} />
      <Cfg.Provider value={value}>
        <Environment />
        <ambientLight intensity={0.35} />
        <directionalLight position={[3, 5, 4]} intensity={1.6} />
        <directionalLight position={[-4, 2, -2]} intensity={0.5} color="#dfe7ff" />
        <Suspense fallback={null}>
          <Rig><Scene /></Rig>
        </Suspense>
      </Cfg.Provider>
    </Canvas>
  );
}

/** Called by hero.js: mount(container, config). Returns { setActive, dispose }. */
export function mount(el, cfg) {
  const root = createRoot(el);
  let active = true;
  const render = () => root.render(<StrictMode><App cfg={cfg} active={active} /></StrictMode>);
  render();
  return {
    setActive(on) { if (on !== active) { active = on; render(); } },
    pointer(x, y) { input.px = x; input.py = y; },
    scroll(p) { input.scroll = p; },
    tap() { input.tap = 1; },
    dispose() { root.unmount(); },
  };
}
