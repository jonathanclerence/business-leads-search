// A liquid-glass lens (liquid-glass-js) resting on the "about" photo, carrying
// the business's real Google rating. It bends the photo underneath it like a
// thick drop of glass. Created only while the photo is on screen.
import LiquidGlass from "liquid-glass-js";

export function attach(media) {
  const img = media.querySelector("img");
  const rating = media.dataset.lensRating, reviews = media.dataset.lensReviews;
  if (!img || !rating) return null;
  let glass = null, label = null, raf = 0, timer = 0;

  const size = () => {
    const w = Math.round(Math.min(236, media.clientWidth * 0.64));
    return { w, h: Math.round(w * 0.42) };
  };
  function place() {
    raf = 0;
    if (!glass) return;
    const r = media.getBoundingClientRect(), { w, h } = size();
    const x = Math.round(r.left + Math.min(24, r.width * 0.06)), y = Math.round(r.bottom - h - Math.min(24, r.width * 0.06));
    glass.moveTo(x, y);
    label.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    label.style.width = `${w}px`; label.style.height = `${h}px`;
  }
  function on() {
    if (glass) return;
    const { w, h } = size();
    glass = new LiquidGlass({
      background: img, width: w, height: h, radius: h / 2,
      scale: 40, depth: Math.round(h * 0.3), curvature: 3.6, convexity: 1, chroma: 0.14,
      blur: 2, glow: 0.25, edge: 0.9, specAngle: 125, tint: 0.34, tintColor: "#15140f",
      draggable: false, zIndex: 40,
    });
    label = document.createElement("div");
    label.className = "lens-label";
    label.setAttribute("aria-hidden", "true");
    const b = document.createElement("b"); b.textContent = `${rating}★`;
    const s = document.createElement("span"); s.textContent = `${reviews} Google reviews`;
    label.append(b, s);
    document.body.appendChild(label);
    place();
    requestAnimationFrame(() => label && label.classList.add("is-on"));
  }
  function off() {
    clearTimeout(timer);
    if (!glass) return;
    glass.destroy(); glass = null;
    label.remove(); label = null;
  }
  const io = new IntersectionObserver((es) => {
    clearTimeout(timer);
    // wait for the photo's own reveal to finish before setting glass on it
    if (es[0].isIntersecting) timer = setTimeout(on, 1100); else off();
  }, { threshold: 0.3 });
  io.observe(media);
  const queue = () => { if (glass && !raf) raf = requestAnimationFrame(place); };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", () => { off(); queue(); });
  return { destroy() { io.disconnect(); off(); removeEventListener("scroll", queue); } };
}
