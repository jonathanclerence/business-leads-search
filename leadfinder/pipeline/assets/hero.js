/* Hero scenes: a small, hand-built canvas animation per kind of business,
   drawn behind the hero text — scissors snipping falling hair for a salon,
   bubbles for a cleaner, meshing gears for a mechanic, and so on.

   Depth comes from layering: every particle has a z (0.3 far … 1.3 near)
   that scales its size, opacity, parallax and speed, and the scene's main
   object is drawn between the far and near layers. It follows the pointer a
   little, drifts on scroll, reacts to taps, recolours with the page accent,
   pauses off-screen, and draws one still frame for reduced-motion users. */
(function () {
  "use strict";
  var canvas = document.querySelector("canvas.hero-fx");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var root = document.documentElement;
  var hero = canvas.parentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TAU = Math.PI * 2;

  var W = 0, H = 0, DPR = 1, mobile = false;
  var P = { x: 0, y: 0, tx: 0, ty: 0, px: -999, py: -999, down: false };   // pointer, eased -1..1 and px
  var scrollP = 0, time = 0, last = 0, raf = 0, inView = true;
  var C = {};

  /* ---- helpers ------------------------------------------------------- */
  function rand(a, b) { return a + Math.random() * (b - a); }
  function pick(a) { return a[(Math.random() * a.length) | 0]; }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function hexRgb(hex) {
    hex = (hex || "#000").trim().replace("#", "");
    if (hex.length === 3) hex = hex.replace(/./g, "$&$&");
    var n = parseInt(hex, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgba(hex, a) { var c = hexRgb(hex); return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a + ")"; }
  function mix(h1, h2, t) {
    var a = hexRgb(h1), b = hexRgb(h2);
    return "#" + [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * t).toString(16).padStart(2, "0"); }).join("");
  }
  function readColours() {
    var cs = getComputedStyle(root);
    C.accent = cs.getPropertyValue("--accent").trim() || "#2f6f62";
    C.ink = cs.getPropertyValue("--ink").trim() || "#161514";
    C.paper = cs.getPropertyValue("--paper").trim() || "#f6f3ee";
    C.dark = root.dataset.paper === "dark";
    C.soft = mix(C.accent, C.paper, 0.55);
    C.metal = C.dark ? ["#d9dde3", "#7d838c", "#f2f4f6"] : ["#f3f4f6", "#9aa1aa", "#e3e6ea"];
  }
  // Where the scene's main object sits: right of the text on wide screens,
  // in the stage under the buttons on phones.
  function focal() {
    return mobile ? { x: W * 0.66, y: H - 132, s: 0.62 } : { x: W * 0.76, y: H * 0.5, s: Math.min(1.15, W / 1300) };
  }
  // Screen position of a particle with depth z (parallax with pointer + scroll).
  function sx(p) { return p.x + P.x * 22 * p.z; }
  function sy(p) { return p.y - scrollP * 160 * p.z + P.y * 10 * p.z; }
  function count(desktop) { return Math.round(mobile ? desktop * 0.5 : desktop); }
  function metalGrad(x0, y0, x1, y1) {
    var g = ctx.createLinearGradient(x0, y0, x1, y1);
    g.addColorStop(0, C.metal[0]); g.addColorStop(0.55, C.metal[1]); g.addColorStop(1, C.metal[2]);
    return g;
  }
  function shadow(on, blur) {
    ctx.shadowColor = on ? (C.dark ? "rgba(0,0,0,.55)" : "rgba(40,30,20,.18)") : "transparent";
    ctx.shadowBlur = on ? blur || 28 : 0;
    ctx.shadowOffsetY = on ? 14 : 0;
  }
  function sparkle(x, y, r, a, col) {
    ctx.save(); ctx.translate(x, y); ctx.globalAlpha = a; ctx.fillStyle = col;
    ctx.beginPath();
    for (var i = 0; i < 4; i++) {
      var ang = i * TAU / 4;
      ctx.quadraticCurveTo(Math.cos(ang + 0.4) * r * 0.18, Math.sin(ang + 0.4) * r * 0.18, Math.cos(ang + Math.PI / 4) * r, Math.sin(ang + Math.PI / 4) * r);
    }
    ctx.closePath(); ctx.fill(); ctx.restore();
  }
  function depthSort(list) { return list.sort(function (a, b) { return a.z - b.z; }); }

  /* ---- scenes -------------------------------------------------------- */
  var S = {};

  // Salon / barber: scissors snipping, strands of hair falling in depth.
  S.hair = function () {
    var strands = [], cycle = 1.9, prevPhase = 0, burstNow = false;
    var HAIR = ["#2a1c14", "#3b2719", "#5a3a25", "#83563a", "#b98b5c", "#1c1a19", "#6b4a33"];
    function strand(x, y, z, burst) {
      return { x: x, y: y, z: z, len: rand(34, 92) * z, a: rand(0, TAU), va: rand(-1.4, 1.4),
               vx: burst ? rand(-70, 50) : rand(-8, 8), vy: burst ? rand(-50, 10) : rand(8, 24),
               curl: rand(-1, 1), w: rand(0.9, 2.1) * z, col: pick(HAIR), ph: rand(0, TAU), twin: Math.random() < 0.55 };
    }
    function bladeTip() {
      var f = focal(), ang = -2.45 + P.x * 0.12;
      return { x: f.x + Math.cos(ang) * 210 * f.s, y: f.y + Math.sin(ang) * 210 * f.s - scrollP * 120 };
    }
    return {
      init: function () { for (var i = 0; i < count(46); i++) strands.push(strand(rand(0, W), rand(-H, H), rand(0.35, 1.25))); },
      tap: function () { burstNow = true; },
      update: function (dt) {
        var phase = (time % cycle) / cycle;
        if ((prevPhase < 0.62 && phase >= 0.62) || burstNow) {
          var tip = bladeTip();
          for (var i = 0; i < count(14); i++) strands.push(strand(tip.x + rand(-40, 70), tip.y + rand(-30, 30), rand(0.75, 1.3), true));
          burstNow = false;
        }
        prevPhase = phase;
        strands.forEach(function (s) {
          s.vy = Math.min(s.vy + 42 * s.z * dt, 64 * s.z);
          s.vx = s.vx * 0.985 + (P.x * 14) * dt;
          s.ph += dt * 1.6;
          s.x += (s.vx + Math.sin(s.ph) * 10) * dt;
          s.y += s.vy * dt;
          s.a += s.va * dt * 0.6;
        });
        strands = strands.filter(function (s) { return s.y < H + 120 && s.x > -120 && s.x < W + 120; });
        while (strands.length < count(46)) strands.push(strand(rand(0, W), rand(-160, -20), rand(0.35, 1.25)));
        if (strands.length > count(140)) strands.splice(0, strands.length - count(140));
      },
      draw: function () {
        depthSort(strands);
        var drawStrand = function (s) {
          var x = sx(s), y = sy(s), dx = Math.cos(s.a) * s.len, dy = Math.sin(s.a) * s.len;
          var nx = -dy * 0.35 * s.curl, ny = dx * 0.35 * s.curl;
          ctx.strokeStyle = C.dark ? mix(s.col, "#e8d8c4", 0.55) : s.col;
          ctx.globalAlpha = 0.18 + 0.6 * clamp(s.z - 0.3, 0, 1);
          ctx.lineWidth = s.w;
          ctx.beginPath(); ctx.moveTo(x, y);
          ctx.quadraticCurveTo(x + dx * 0.5 + nx, y + dy * 0.5 + ny, x + dx, y + dy);
          if (s.twin) {   // hair falls in little clumps, not single lines
            ctx.moveTo(x + 3 * s.z, y + 2 * s.z);
            ctx.quadraticCurveTo(x + dx * 0.5 + nx * 1.3 + 3, y + dy * 0.5 + ny * 1.3 + 2, x + dx * 0.9 + 3, y + dy * 0.9 + 2);
          }
          ctx.stroke();
        };
        ctx.lineCap = "round";
        strands.forEach(function (s) { if (s.z < 0.95) drawStrand(s); });
        ctx.globalAlpha = 1;
        // scissors
        var f = focal(), phase = (time % cycle) / cycle;
        var open = phase < 0.45 ? 0.5 : phase < 0.62 ? 0.5 - 0.42 * (phase - 0.45) / 0.17 : phase < 0.8 ? 0.08 : 0.08 + 0.42 * ((phase - 0.8) / 0.2);
        var base = -2.45 + P.x * 0.12 - scrollP * 0.5, s = f.s * 1.12;
        ctx.save();
        ctx.translate(f.x + P.x * 18, f.y + P.y * 10 - scrollP * 120);
        [-1, 1].forEach(function (side) {
          ctx.save();
          ctx.rotate(base + side * open / 2);
          // blade: a long, slightly curved wedge from the pivot to a fine point
          shadow(true, 30);
          ctx.beginPath();
          ctx.moveTo(-10 * s, -side * 11 * s);
          ctx.bezierCurveTo(60 * s, -side * 20 * s, 170 * s, -side * 12 * s, 236 * s, -side * 1 * s);
          ctx.quadraticCurveTo(240 * s, 0, 236 * s, side * 2 * s);
          ctx.bezierCurveTo(170 * s, side * 6 * s, 70 * s, side * 9 * s, -10 * s, side * 9 * s);
          ctx.closePath();
          ctx.fillStyle = metalGrad(0, -side * 20 * s, 0, side * 10 * s); ctx.fill();
          shadow(false);
          ctx.strokeStyle = side < 0 ? "rgba(0,0,0,.28)" : "rgba(0,0,0,.14)"; ctx.lineWidth = 1; ctx.stroke();
          // bevel highlight along the cutting edge
          ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = 1.4 * s;
          ctx.beginPath(); ctx.moveTo(20 * s, side * 7 * s); ctx.bezierCurveTo(90 * s, side * 7 * s, 170 * s, side * 4 * s, 228 * s, side * 1.5 * s); ctx.stroke();
          // shank + finger ring in the accent colour
          ctx.beginPath(); ctx.moveTo(-8 * s, side * 2 * s); ctx.quadraticCurveTo(-46 * s, side * 10 * s, -74 * s, side * 26 * s);
          ctx.strokeStyle = C.accent; ctx.lineWidth = 13 * s; ctx.lineCap = "round"; ctx.stroke();
          ctx.beginPath(); ctx.ellipse(-104 * s, side * 40 * s, 32 * s, 25 * s, side * 0.5, 0, TAU);
          ctx.lineWidth = 11 * s; ctx.stroke();
          ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 2.5 * s;
          ctx.beginPath(); ctx.ellipse(-104 * s, side * 40 * s, 32 * s, 25 * s, side * 0.5, Math.PI * 1.1, Math.PI * 1.6); ctx.stroke();
          ctx.restore();
        });
        ctx.beginPath(); ctx.arc(0, 0, 8 * s, 0, TAU); ctx.fillStyle = metalGrad(-8 * s, -8 * s, 8 * s, 8 * s); ctx.fill();
        ctx.beginPath(); ctx.arc(0, 0, 3 * s, 0, TAU); ctx.fillStyle = "rgba(0,0,0,.35)"; ctx.fill();
        ctx.restore();
        strands.forEach(function (s) { if (s.z >= 0.95) drawStrand(s); });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Nails / beauty: a glossy liquid drop that breathes, polish droplets, glints.
  S.beauty = function () {
    var drops = [], glints = [];
    function drop(z) { return { x: rand(0, W), y: rand(0, H), z: z, r: rand(5, 16) * z, vy: rand(-14, -5) * z, ph: rand(0, TAU), hue: Math.random() }; }
    return {
      init: function () { for (var i = 0; i < count(26); i++) drops.push(drop(rand(0.35, 1.25))); },
      tap: function (x, y) { for (var i = 0; i < 14; i++) glints.push({ x: x + rand(-50, 50), y: y + rand(-50, 50), life: 1, r: rand(6, 16) }); },
      update: function (dt) {
        drops.forEach(function (d) {
          d.ph += dt; d.y += d.vy * dt; d.x += Math.sin(d.ph * 0.8) * 6 * dt;
          var dx = sx(d) - P.px, dy = sy(d) - P.py, dist = Math.hypot(dx, dy);
          if (dist < 120) { d.x += dx / dist * 60 * dt; d.y += dy / dist * 60 * dt; }
          if (d.y < -40) { d.y = H + 30; d.x = rand(0, W); }
        });
        if (Math.random() < dt * 3) glints.push({ x: rand(0, W), y: rand(0, H), life: 1, r: rand(5, 11) });
        glints.forEach(function (g) { g.life -= dt * 0.9; });
        glints = glints.filter(function (g) { return g.life > 0; });
      },
      draw: function () {
        depthSort(drops);
        var paint = function (d) {
          var x = sx(d), y = sy(d), col = d.hue < 0.5 ? C.accent : d.hue < 0.8 ? C.soft : "#f3d6cf";
          var g = ctx.createRadialGradient(x - d.r * 0.35, y - d.r * 0.4, d.r * 0.1, x, y, d.r);
          g.addColorStop(0, "rgba(255,255,255,.95)"); g.addColorStop(0.25, col); g.addColorStop(1, mix(col, "#000", 0.25));
          ctx.globalAlpha = 0.25 + 0.6 * clamp(d.z - 0.3, 0, 1);
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, d.r, 0, TAU); ctx.fill();
        };
        drops.forEach(function (d) { if (d.z < 0.9) paint(d); });
        ctx.globalAlpha = 1;
        // the hero drop: a glossy teardrop of polish, gently wobbling
        var f = focal(), R = 104 * f.s, cx = f.x + P.x * 20, cy = f.y + 30 * f.s + P.y * 12 - scrollP * 110;
        var wob = Math.sin(time * 1.6) * 0.035, tipY = cy - R * (2.05 + Math.sin(time * 1.1) * 0.06);
        ctx.save(); shadow(true, 44);
        ctx.beginPath();
        ctx.moveTo(cx, tipY);
        ctx.bezierCurveTo(cx + R * 0.18, cy - R * 1.25, cx + R * (1.02 + wob), cy - R * 0.62, cx + R * (1 + wob), cy);
        ctx.bezierCurveTo(cx + R * (1 + wob), cy + R * 0.62, cx + R * 0.58, cy + R * 1.02, cx, cy + R * (1.02 - wob));
        ctx.bezierCurveTo(cx - R * 0.58, cy + R * 1.02, cx - R * (1 - wob), cy + R * 0.62, cx - R * (1 - wob), cy);
        ctx.bezierCurveTo(cx - R * (1.02 - wob), cy - R * 0.62, cx - R * 0.18, cy - R * 1.25, cx, tipY);
        var g = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.3, R * 0.05, cx, cy, R * 1.25);
        g.addColorStop(0, mix(C.accent, "#fff", 0.55)); g.addColorStop(0.35, C.accent); g.addColorStop(1, mix(C.accent, "#000", 0.42));
        ctx.fillStyle = g; ctx.fill(); shadow(false);
        ctx.globalAlpha = 0.75; ctx.fillStyle = "#fff";
        ctx.beginPath(); ctx.ellipse(cx - R * 0.42, cy - R * 0.28, R * 0.12, R * 0.3, 0.45, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.35; ctx.beginPath(); ctx.ellipse(cx + R * 0.5, cy + R * 0.5, R * 0.16, R * 0.06, -0.7, 0, TAU); ctx.fill();
        ctx.restore();
        drops.forEach(function (d) { if (d.z >= 0.9) paint(d); });
        glints.forEach(function (gl) { sparkle(gl.x, gl.y - scrollP * 80, gl.r * (0.6 + gl.life * 0.6), Math.sin(gl.life * Math.PI), C.dark ? "#fff" : mix(C.accent, "#fff", 0.2)); });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Tattoo: a rose drawing itself in fine line, the pen following the ink.
  S.tattoo = function () {
    var strokes = [], total = 0, flecks = [], cycle = 9;
    function build() {
      strokes = []; var f = focal(), s = f.s * 1.1, cx = f.x, cy = f.y - 30 * s, pts, i, t;
      pts = []; for (t = 0; t <= 1; t += 0.01) { var th = t * Math.PI * 4.2, r = (5 + 44 * t) * s; pts.push([cx + Math.cos(th) * r, cy + Math.sin(th) * r * 0.86]); } strokes.push(pts);
      [[-0.2, 1.2], [1.9, 3.3], [3.6, 5.1]].forEach(function (a) {
        pts = []; for (t = 0; t <= 1; t += 0.03) { var ang = a[0] + (a[1] - a[0]) * t, rr = (64 + Math.sin(t * Math.PI) * 18) * s; pts.push([cx + Math.cos(ang) * rr, cy + Math.sin(ang) * rr * 0.86]); } strokes.push(pts);
      });
      pts = []; for (t = 0; t <= 1; t += 0.03) pts.push([cx + Math.sin(t * 2.6) * 22 * s - 6 * s, cy + 70 * s + t * 150 * s]); strokes.push(pts);
      [[1, 0.35], [-1, 0.65]].forEach(function (lf) {
        var bx = cx + Math.sin(lf[1] * 2.6) * 22 * s - 6 * s, by = cy + 70 * s + lf[1] * 150 * s;
        pts = []; for (t = 0; t <= 1; t += 0.05) pts.push([bx + lf[0] * t * 58 * s, by - Math.sin(t * Math.PI) * 18 * s - t * 20 * s]);
        for (t = 1; t >= 0; t -= 0.05) pts.push([bx + lf[0] * t * 58 * s, by + Math.sin(t * Math.PI) * 10 * s - t * 20 * s]);
        strokes.push(pts);
      });
      total = 0; strokes.forEach(function (st) { total += st.length; });
    }
    return {
      init: function () { build(); for (var i = 0; i < count(30); i++) flecks.push({ x: rand(0, W), y: rand(0, H), z: rand(0.3, 1.2), ph: rand(0, TAU) }); },
      resize: build,
      tap: function () { time = Math.floor(time / cycle) * cycle; },
      update: function (dt) { flecks.forEach(function (f) { f.ph += dt; f.y -= 6 * f.z * dt; if (f.y < -10) { f.y = H + 10; f.x = rand(0, W); } }); },
      draw: function () {
        flecks.forEach(function (f) { sparkle(sx(f), sy(f), 5 * f.z, (0.3 + 0.35 * Math.sin(f.ph * 2)) * f.z, C.accent); });
        var ph = (time % cycle) / cycle, prog = Math.min(1, ph / 0.72), fade = ph > 0.86 ? 1 - (ph - 0.86) / 0.14 : 1;
        var budget = Math.floor(total * prog), oy = -scrollP * 110 + P.y * 8, ox = P.x * 16, tip = null;
        ctx.save(); ctx.translate(ox, oy);
        ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.globalAlpha = fade;
        ctx.strokeStyle = C.dark ? "#f1ece4" : C.ink; ctx.lineWidth = 2.2 * focal().s;
        strokes.forEach(function (st) {
          if (budget <= 1) return;
          var n = Math.min(st.length, budget); budget -= n;
          ctx.beginPath(); ctx.moveTo(st[0][0], st[0][1]);
          for (var i = 1; i < n; i++) ctx.lineTo(st[i][0], st[i][1]);
          ctx.stroke(); tip = st[n - 1];
        });
        if (tip && prog < 1) {
          var g = ctx.createRadialGradient(tip[0], tip[1], 0, tip[0], tip[1], 26);
          g.addColorStop(0, rgba(C.accent, 0.55)); g.addColorStop(1, rgba(C.accent, 0));
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(tip[0], tip[1], 26, 0, TAU); ctx.fill();
          // the pen
          var s = focal().s;
          ctx.translate(tip[0], tip[1]); ctx.rotate(-0.75); shadow(true, 22);
          ctx.fillStyle = metalGrad(0, -9 * s, 0, 9 * s); ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(26 * s, -7 * s); ctx.lineTo(26 * s, 7 * s); ctx.closePath(); ctx.fill();
          ctx.fillStyle = C.accent; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(26 * s, -12 * s, 70 * s, 24 * s, 8 * s) : ctx.rect(26 * s, -12 * s, 70 * s, 24 * s); ctx.fill();
          ctx.fillStyle = C.dark ? "#2a2a2e" : "#26262a"; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(94 * s, -14 * s, 90 * s, 28 * s, 10 * s) : ctx.rect(94 * s, -14 * s, 90 * s, 28 * s); ctx.fill();
        }
        ctx.restore();
      }
    };
  };

  // Massage / spa: balanced stones over a still pond, ripples where you touch.
  S.wellness = function () {
    var ripples = [], leaves = [], lastRipple = 0;
    return {
      init: function () { for (var i = 0; i < count(8); i++) leaves.push({ x: rand(0, W), y: rand(0, H), z: rand(0.4, 1.1), a: rand(0, TAU), ph: rand(0, TAU) }); },
      tap: function (x, y) { ripples.push({ x: x, y: y, r: 0, life: 1 }); },
      update: function (dt) {
        var f = focal();
        if (time - lastRipple > 2.2) { ripples.push({ x: f.x + rand(-60, 60) * f.s, y: f.y + 120 * f.s, r: 0, life: 1, pond: true }); lastRipple = time; }
        if (P.px > 0 && Math.random() < dt * 2.5) ripples.push({ x: P.px, y: P.py, r: 0, life: 0.6 });
        ripples.forEach(function (r) { r.r += 48 * dt; r.life -= dt * 0.28; });
        ripples = ripples.filter(function (r) { return r.life > 0; });
        leaves.forEach(function (l) { l.ph += dt; l.y += 9 * l.z * dt; l.x += Math.sin(l.ph) * 12 * dt; l.a += dt * 0.4; if (l.y > H + 30) { l.y = -30; l.x = rand(0, W); } });
      },
      draw: function () {
        ripples.forEach(function (r) {
          ctx.globalAlpha = 0.35 * r.life; ctx.strokeStyle = C.accent; ctx.lineWidth = 1.4;
          ctx.beginPath(); ctx.ellipse(r.x, r.y - scrollP * 100, r.r, r.r * 0.34, 0, 0, TAU); ctx.stroke();
        });
        leaves.forEach(function (l) {
          ctx.save(); ctx.translate(sx(l), sy(l)); ctx.rotate(l.a); ctx.scale(1, Math.cos(l.ph * 0.8));
          ctx.globalAlpha = 0.25 + 0.4 * l.z; ctx.fillStyle = C.soft;
          ctx.beginPath(); ctx.moveTo(-14 * l.z, 0); ctx.quadraticCurveTo(0, -9 * l.z, 14 * l.z, 0); ctx.quadraticCurveTo(0, 9 * l.z, -14 * l.z, 0); ctx.fill();
          ctx.restore();
        });
        ctx.globalAlpha = 1;
        var f = focal(), s = f.s, cx = f.x + P.x * 14, base = f.y + 92 * s - scrollP * 100;
        var stones = [[150, 52, "#8f8a80"], [118, 44, "#a8a297"], [86, 36, "#7e796f"], [56, 28, "#b9b3a8"]];
        var y = base;
        stones.forEach(function (st, i) {
          var w = st[0] * s, h = st[1] * s, bob = Math.sin(time * 0.9 + i * 0.7) * 2.5 * s, x = cx + Math.sin(time * 0.6 + i) * 3 * s;
          y -= h * 0.82;
          ctx.save(); shadow(true, 24);
          var g = ctx.createRadialGradient(x - w * 0.25, y + bob - h * 0.35, 2, x, y + bob, w * 0.75);
          var tone = C.dark ? mix(st[2], "#000", 0.25) : st[2];
          g.addColorStop(0, mix(tone, "#fff", 0.45)); g.addColorStop(1, mix(tone, "#000", 0.2));
          ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(x, y + bob, w / 2, h / 2, 0, 0, TAU); ctx.fill(); ctx.restore();
        });
      }
    };
  };

  // Health: a calm pulse line and soft floating crosses.
  S.health = function () {
    var crosses = [];
    return {
      init: function () { for (var i = 0; i < count(18); i++) crosses.push({ x: rand(0, W), y: rand(0, H), z: rand(0.35, 1.2), a: rand(0, TAU), va: rand(-0.4, 0.4), vy: rand(-10, -4) }); },
      update: function (dt) { crosses.forEach(function (c) { c.y += c.vy * c.z * dt; c.a += c.va * dt; if (c.y < -20) { c.y = H + 20; c.x = rand(0, W); } }); },
      draw: function () {
        crosses.forEach(function (c) {
          ctx.save(); ctx.translate(sx(c), sy(c)); ctx.rotate(c.a); ctx.globalAlpha = 0.15 + 0.35 * c.z; ctx.fillStyle = c.z > 0.9 ? C.accent : C.soft;
          var s = 7 * c.z; ctx.fillRect(-s, -s / 3, s * 2, s * 2 / 3); ctx.fillRect(-s / 3, -s, s * 2 / 3, s * 2); ctx.restore();
        });
        var f = focal(), y0 = f.y - scrollP * 100, x0 = mobile ? W * 0.08 : W * 0.5, x1 = W + 20, head = ((time * 0.22) % 1);
        ctx.globalAlpha = 1; ctx.lineWidth = 2.5 * f.s + 0.5; ctx.strokeStyle = C.accent; ctx.lineJoin = "round"; ctx.lineCap = "round";
        ctx.beginPath();
        var hx = x0 + (x1 - x0) * head, hy = y0;
        for (var x = x0; x <= x1; x += 3) {
          var t = (x - x0) / (x1 - x0), local = ((t * 3) % 1), yv = 0;
          if (local > 0.42 && local < 0.6) {
            var k = (local - 0.42) / 0.18;
            yv = k < 0.25 ? -k * 4 * 24 : k < 0.5 ? -24 + (k - 0.25) * 4 * 110 : k < 0.75 ? 86 - (k - 0.5) * 4 * 120 : -34 + (k - 0.75) * 4 * 34;
          }
          var yy = y0 + yv * f.s;
          var fade = clamp((head - t) * 6, 0, 1) * clamp(1 - (head - t) * 1.6, 0, 1);
          if (t > head) break;
          ctx.globalAlpha = 0.15 + 0.85 * fade;
          if (x === x0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy);
          hx = x; hy = yy;
        }
        ctx.stroke();
        var g = ctx.createRadialGradient(hx, hy, 0, hx, hy, 26);
        g.addColorStop(0, rgba(C.accent, 0.9)); g.addColorStop(1, rgba(C.accent, 0));
        ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(hx, hy, 26, 0, TAU); ctx.fill();
      }
    };
  };

  // Fitness: a dumbbell turning in 3D, speed streaks, pulses on the beat.
  S.fitness = function () {
    var streaks = [], pulses = [], rot = 0, spin = 1;
    return {
      init: function () { for (var i = 0; i < count(26); i++) streaks.push({ x: rand(0, W), y: rand(0, H), z: rand(0.3, 1.2), len: rand(40, 140) }); },
      tap: function () { spin = 6; },
      update: function (dt) {
        spin += (1 + Math.abs(P.x) * 2 - spin) * dt * 1.5;
        rot += dt * 0.9 * spin;
        streaks.forEach(function (s) { s.x += 260 * s.z * dt; s.y -= 110 * s.z * dt; if (s.x > W + 150 || s.y < -150) { s.x = rand(-200, W * 0.6); s.y = rand(H * 0.4, H + 150); } });
        if ((time % 1.2) < dt) pulses.push({ r: 0, life: 1 });
        pulses.forEach(function (p) { p.r += 150 * dt; p.life -= dt * 0.8; });
        pulses = pulses.filter(function (p) { return p.life > 0; });
      },
      draw: function () {
        ctx.lineCap = "round";
        streaks.forEach(function (s) {
          ctx.globalAlpha = 0.08 + 0.3 * s.z; ctx.strokeStyle = s.z > 0.9 ? C.accent : C.ink; ctx.lineWidth = 1.5 * s.z;
          ctx.beginPath(); ctx.moveTo(sx(s), sy(s)); ctx.lineTo(sx(s) - s.len * 0.92, sy(s) + s.len * 0.39); ctx.stroke();
        });
        var f = focal(), cx = f.x + P.x * 16, cy = f.y - scrollP * 110, s = f.s;
        pulses.forEach(function (p) { ctx.globalAlpha = 0.3 * p.life; ctx.strokeStyle = C.accent; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, p.r * s, 0, TAU); ctx.stroke(); });
        ctx.globalAlpha = 1;
        var c = Math.cos(rot), half = 150 * s, tilt = -0.42 + P.y * 0.1;
        ctx.save(); ctx.translate(cx, cy); ctx.rotate(tilt);
        var ends = [-1, 1].map(function (side) { return { side: side, x: side * half * c, depth: side * Math.sin(rot) }; }).sort(function (a, b) { return a.depth - b.depth; });
        function plate(e) {
          [0, 1, 2].forEach(function (k) {
            var px = e.x - e.side * k * 18 * s * c, r = (78 - k * 12) * s, w = Math.max(6 * s, Math.abs(Math.sin(rot)) * r * 0.42 + 10 * s);
            ctx.save(); shadow(k === 0, 26);
            var g = ctx.createLinearGradient(px - w, -r, px + w, r);
            g.addColorStop(0, mix(C.ink, "#666", C.dark ? 0.2 : 0.3)); g.addColorStop(0.5, mix(C.ink, "#999", 0.45)); g.addColorStop(1, C.ink);
            ctx.fillStyle = k === 1 ? C.accent : g;
            ctx.beginPath(); ctx.ellipse(px, 0, w, r, 0, 0, TAU); ctx.fill(); ctx.restore();
          });
        }
        plate(ends[0]);
        ctx.fillStyle = metalGrad(0, -8 * s, 0, 8 * s); ctx.fillRect(-half * Math.abs(c), -7 * s, half * 2 * Math.abs(c), 14 * s);
        plate(ends[1]);
        ctx.restore();
      }
    };
  };

  // Lessons / tutoring / dance: glyphs and notes drifting up, a paper plane looping.
  S.learning = function () {
    var glyphs = [], trail = [];
    var G = ["♪", "♫", "A", "b", "c", "1", "2", "3", "+", "÷", "✎", "★", "Aa", "♩"];
    return {
      init: function () { for (var i = 0; i < count(28); i++) glyphs.push({ x: rand(0, W), y: rand(0, H), z: rand(0.35, 1.25), g: pick(G), a: rand(-0.5, 0.5), va: rand(-0.4, 0.4), vy: rand(-18, -6) }); },
      update: function (dt) {
        glyphs.forEach(function (g) { g.y += g.vy * g.z * dt; g.a += g.va * dt; if (g.y < -30) { g.y = H + 30; g.x = rand(0, W); } });
        var p = plane(); trail.push([p.x, p.y]); if (trail.length > 70) trail.shift();
      },
      draw: function () {
        glyphs.forEach(function (g) {
          ctx.save(); ctx.translate(sx(g), sy(g)); ctx.rotate(g.a); ctx.globalAlpha = 0.14 + 0.45 * g.z;
          ctx.fillStyle = g.z > 0.95 ? C.accent : C.ink; ctx.font = (16 + 26 * g.z) + "px " + getComputedStyle(root).getPropertyValue("--display");
          ctx.textAlign = "center"; ctx.fillText(g.g, 0, 0); ctx.restore();
        });
        ctx.globalAlpha = 0.5; ctx.strokeStyle = C.accent; ctx.setLineDash([4, 7]); ctx.lineWidth = 1.5;
        ctx.beginPath(); trail.forEach(function (t, i) { if (i) ctx.lineTo(t[0], t[1]); else ctx.moveTo(t[0], t[1]); }); ctx.stroke(); ctx.setLineDash([]);
        var p = plane(), q = plane(0.02), ang = Math.atan2(q.y - p.y, q.x - p.x), s = focal().s;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(ang); ctx.globalAlpha = 1; shadow(true, 20);
        ctx.fillStyle = C.dark ? "#f1eee9" : "#ffffff"; ctx.beginPath(); ctx.moveTo(34 * s, 0); ctx.lineTo(-26 * s, -20 * s); ctx.lineTo(-14 * s, 0); ctx.lineTo(-26 * s, 20 * s); ctx.closePath(); ctx.fill();
        shadow(false); ctx.fillStyle = mix(C.accent, "#fff", 0.2); ctx.beginPath(); ctx.moveTo(34 * s, 0); ctx.lineTo(-14 * s, 0); ctx.lineTo(-26 * s, 20 * s); ctx.closePath(); ctx.fill();
        ctx.restore();
      }
    };
    function plane(ahead) {
      var f = focal(), t = time * 0.35 + (ahead || 0) * 6, r = 130 * f.s;
      return { x: f.x + Math.sin(t) * r * 1.4 + P.x * 20, y: f.y + Math.sin(t * 2) * r * 0.5 - scrollP * 110 };
    }
  };

  // Mechanic / auto: two meshing gears, sparks where they meet.
  S.auto = function () {
    var rot = 0, sparks = [], boost = 0;
    function gear(cx, cy, r, teeth, a, col) {
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(a); shadow(true, 30);
      ctx.beginPath();
      for (var i = 0; i < teeth; i++) {
        var a0 = i / teeth * TAU, a1 = a0 + TAU / teeth * 0.25, a2 = a0 + TAU / teeth * 0.5, a3 = a0 + TAU / teeth * 0.75, ro = r * 1.12;
        ctx.lineTo(Math.cos(a0) * r, Math.sin(a0) * r); ctx.lineTo(Math.cos(a1) * ro, Math.sin(a1) * ro);
        ctx.lineTo(Math.cos(a2) * ro, Math.sin(a2) * ro); ctx.lineTo(Math.cos(a3) * r, Math.sin(a3) * r);
      }
      ctx.closePath();
      ctx.fillStyle = col || metalGrad(-r, -r, r, r); ctx.fill(); shadow(false);
      ctx.globalCompositeOperation = "destination-out";
      for (var k = 0; k < 5; k++) { var ka = k / 5 * TAU; ctx.beginPath(); ctx.arc(Math.cos(ka) * r * 0.55, Math.sin(ka) * r * 0.55, r * 0.16, 0, TAU); ctx.fill(); }
      ctx.beginPath(); ctx.arc(0, 0, r * 0.14, 0, TAU); ctx.fill();
      ctx.globalCompositeOperation = "source-over";
      ctx.strokeStyle = "rgba(0,0,0,.12)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(0, 0, r * 0.8, 0, TAU); ctx.stroke();
      ctx.restore();
    }
    return {
      tap: function () { boost = 4; },
      update: function (dt) {
        boost *= Math.pow(0.4, dt);
        rot += dt * (0.35 + boost + scrollP * 2);
        var f = focal(), mx = f.x - 18 * f.s, my = f.y + 20 * f.s - scrollP * 110;
        if (Math.random() < dt * (6 + boost * 10)) for (var i = 0; i < 3; i++) sparks.push({ x: mx, y: my, vx: rand(-160, 40), vy: rand(-160, -20), life: 1 });
        sparks.forEach(function (s) { s.vy += 380 * dt; s.x += s.vx * dt; s.y += s.vy * dt; s.life -= dt * 1.4; });
        sparks = sparks.filter(function (s) { return s.life > 0; });
      },
      draw: function () {
        var f = focal(), s = f.s, cx = f.x + P.x * 16, cy = f.y - scrollP * 110 + P.y * 8;
        gear(cx + 70 * s, cy - 30 * s, 96 * s, 16, rot, null);
        gear(cx - 92 * s, cy + 58 * s, 64 * s, 11, -rot * 16 / 11 + 0.15, C.accent);
        ctx.lineCap = "round";
        sparks.forEach(function (sp) {
          ctx.globalAlpha = sp.life; ctx.strokeStyle = sp.life > 0.5 ? "#ffd27a" : C.accent; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(sp.x, sp.y); ctx.lineTo(sp.x - sp.vx * 0.03, sp.y - sp.vy * 0.03); ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Trades: a spanner turning a nut, bolts and nuts tumbling, blueprint grid.
  S.trades = function () {
    var nuts = [], rot = 0;
    function hex(x, y, r, a, col) {
      ctx.save(); ctx.translate(x, y); ctx.rotate(a); ctx.beginPath();
      for (var i = 0; i < 6; i++) ctx.lineTo(Math.cos(i / 6 * TAU) * r, Math.sin(i / 6 * TAU) * r);
      ctx.closePath(); ctx.fillStyle = col; ctx.fill();
      ctx.globalCompositeOperation = "destination-out"; ctx.beginPath(); ctx.arc(0, 0, r * 0.45, 0, TAU); ctx.fill(); ctx.globalCompositeOperation = "source-over";
      ctx.restore();
    }
    return {
      init: function () { for (var i = 0; i < count(18); i++) nuts.push({ x: rand(0, W), y: rand(-H, H), z: rand(0.35, 1.25), a: rand(0, TAU), va: rand(-1.5, 1.5), vy: rand(14, 40) }); },
      tap: function (x, y) { for (var i = 0; i < 6; i++) nuts.push({ x: x + rand(-30, 30), y: y, z: rand(0.8, 1.25), a: rand(0, TAU), va: rand(-4, 4), vy: rand(-60, 0) }); },
      update: function (dt) {
        rot = Math.sin(time * 0.8) * 0.5 + time * 0.15;
        nuts.forEach(function (n) { n.vy = Math.min(n.vy + 30 * dt, 60); n.y += n.vy * n.z * dt; n.a += n.va * dt; if (n.y > H + 30) { n.y = -30; n.x = rand(0, W); n.vy = rand(14, 40); } });
        if (nuts.length > count(40)) nuts.splice(0, nuts.length - count(40));
      },
      draw: function () {
        ctx.globalAlpha = C.dark ? 0.1 : 0.07; ctx.strokeStyle = C.accent; ctx.lineWidth = 1;
        var step = 48, off = (-scrollP * 60) % step;
        ctx.beginPath();
        for (var x = (W * 0.45 | 0) - ((W * 0.45 | 0) % step); x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
        for (var y = off; y < H; y += step) { ctx.moveTo(W * 0.45, y); ctx.lineTo(W, y); }
        ctx.stroke(); ctx.globalAlpha = 1;
        depthSort(nuts);
        nuts.forEach(function (n) { if (n.z < 0.95) { ctx.globalAlpha = 0.2 + 0.5 * n.z; hex(sx(n), sy(n), 9 * n.z, n.a, metalGrad(-9, -9, 9, 9)); } });
        ctx.globalAlpha = 1;
        var f = focal(), s = f.s, cx = f.x + P.x * 16, cy = f.y - scrollP * 110;
        var swing = Math.sin(time * 0.9) * 0.55;
        ctx.save(); shadow(true, 26); hex(cx, cy, 30 * s, swing + Math.PI / 6, metalGrad(cx - 30, cy - 30, cx + 30, cy + 30)); ctx.restore();
        ctx.save(); ctx.translate(cx, cy); ctx.rotate(-0.55 + swing);
        shadow(true, 32);
        ctx.beginPath();
        ctx.arc(0, 0, 50 * s, 0.62, TAU - 0.62);                               // open jaw around the nut
        ctx.lineTo(Math.cos(-0.62) * 50 * s - 22 * s, Math.sin(-0.62) * 50 * s);
        ctx.lineTo(28 * s, -26 * s); ctx.lineTo(28 * s, 26 * s);
        ctx.lineTo(Math.cos(0.62) * 50 * s - 22 * s, Math.sin(0.62) * 50 * s);
        ctx.closePath();
        ctx.moveTo(-40 * s, -20 * s);                                          // handle
        ctx.lineTo(-300 * s, -16 * s); ctx.quadraticCurveTo(-326 * s, 0, -300 * s, 16 * s); ctx.lineTo(-40 * s, 20 * s); ctx.closePath();
        ctx.fillStyle = metalGrad(-300 * s, -50 * s, 50 * s, 50 * s); ctx.fill('nonzero');
        shadow(false);
        ctx.fillStyle = C.accent;                                               // grip
        ctx.beginPath(); ctx.roundRect ? ctx.roundRect(-290 * s, -19 * s, 150 * s, 38 * s, 18 * s) : ctx.rect(-290 * s, -19 * s, 150 * s, 38 * s); ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 2 * s; ctx.beginPath(); ctx.moveTo(-130 * s, -12 * s); ctx.lineTo(-44 * s, -14 * s); ctx.stroke();
        ctx.restore();
        nuts.forEach(function (n) { if (n.z >= 0.95) { ctx.globalAlpha = 0.85; hex(sx(n), sy(n), 9 * n.z, n.a, metalGrad(-9, -9, 9, 9)); } });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Cleaning: iridescent soap bubbles that pop when you touch them.
  S.cleaning = function () {
    var bubbles = [], pops = [];
    function bubble(z) { return { x: rand(0, W), y: rand(H * 0.2, H + 60), z: z, r: rand(10, 40) * z, vy: rand(-22, -8), ph: rand(0, TAU) }; }
    function pop(b) { for (var i = 0; i < 10; i++) { var a = rand(0, TAU); pops.push({ x: sx(b), y: sy(b), vx: Math.cos(a) * 90, vy: Math.sin(a) * 90, life: 1 }); } b.y = H + 80; b.x = rand(0, W); }
    return {
      init: function () { for (var i = 0; i < count(26); i++) bubbles.push(bubble(rand(0.4, 1.25))); var f = focal(); bubbles.push({ x: f.x, y: f.y, z: 1, r: 110 * f.s, vy: -2, ph: 0, hero: true }); },
      tap: function (x, y) { bubbles.forEach(function (b) { if (!b.hero && Math.hypot(sx(b) - x, sy(b) - y) < b.r + 24) pop(b); }); },
      update: function (dt) {
        bubbles.forEach(function (b) {
          b.ph += dt;
          if (b.hero) { var f = focal(); b.x = f.x + Math.sin(time * 0.5) * 10; b.y = f.y + Math.sin(time * 0.7) * 12; return; }
          b.y += b.vy * b.z * dt; b.x += Math.sin(b.ph * 1.2) * 8 * dt;
          if (Math.hypot(sx(b) - P.px, sy(b) - P.py) < b.r) pop(b);
          if (b.y < -60) { b.y = H + 60; b.x = rand(0, W); }
        });
        pops.forEach(function (p) { p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt * 2.2; });
        pops = pops.filter(function (p) { return p.life > 0; });
      },
      draw: function () {
        depthSort(bubbles).forEach(function (b) {
          var x = sx(b), y = sy(b), r = b.r * (1 + Math.sin(b.ph * 2) * 0.02);
          var g = ctx.createRadialGradient(x - r * 0.3, y - r * 0.35, r * 0.05, x, y, r);
          g.addColorStop(0, "rgba(255,255,255,0.0)"); g.addColorStop(0.75, rgba(C.accent, 0.08)); g.addColorStop(0.92, "rgba(170,140,255,.22)"); g.addColorStop(1, "rgba(120,220,255,.35)");
          ctx.globalAlpha = 0.5 + 0.5 * clamp(b.z, 0, 1);
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = Math.max(1, r * 0.05);
          ctx.beginPath(); ctx.arc(x, y, r * 0.72, Math.PI * 1.1, Math.PI * 1.45); ctx.stroke();
          ctx.strokeStyle = rgba(C.accent, 0.25); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.stroke();
        });
        pops.forEach(function (p) { ctx.globalAlpha = p.life; ctx.fillStyle = C.accent; ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, TAU); ctx.fill(); });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Removalists / skip bins: cardboard boxes tumbling in depth, a stack that sways.
  S.boxes = function () {
    var boxes = [];
    function box(x, y, w, h, a, z) {
      ctx.save(); ctx.translate(x, y); ctx.rotate(a);
      ctx.fillStyle = C.dark ? "#9c7a55" : "#c9a273"; ctx.fillRect(-w / 2, -h / 2, w, h);
      ctx.fillStyle = "rgba(255,255,255,.12)"; ctx.fillRect(-w / 2, -h / 2, w, h * 0.18);
      ctx.fillStyle = mix(C.accent, "#fff", 0.1); ctx.fillRect(-w * 0.08, -h / 2, w * 0.16, h);            // tape
      ctx.strokeStyle = "rgba(60,40,20,.25)"; ctx.lineWidth = 1; ctx.strokeRect(-w / 2, -h / 2, w, h);
      ctx.restore();
    }
    return {
      init: function () { for (var i = 0; i < count(14); i++) boxes.push({ x: rand(0, W), y: rand(-H, H), z: rand(0.35, 1.2), a: rand(0, TAU), va: rand(-0.6, 0.6), vy: rand(10, 26) }); },
      tap: function (x, y) { for (var i = 0; i < 4; i++) boxes.push({ x: x + rand(-40, 40), y: y, z: rand(0.8, 1.2), a: rand(0, TAU), va: rand(-2, 2), vy: rand(-40, 0) }); },
      update: function (dt) {
        boxes.forEach(function (b) { b.vy = Math.min(b.vy + 20 * dt, 30); b.y += b.vy * b.z * dt; b.a += b.va * dt; if (b.y > H + 60) { b.y = -60; b.x = rand(0, W); b.vy = rand(10, 26); } });
        if (boxes.length > count(30)) boxes.splice(0, boxes.length - count(30));
      },
      draw: function () {
        depthSort(boxes).forEach(function (b) { ctx.globalAlpha = 0.25 + 0.55 * clamp(b.z - 0.3, 0, 1); box(sx(b), sy(b), 34 * b.z, 26 * b.z, b.a, b.z); });
        ctx.globalAlpha = 1;
        var f = focal(), s = f.s, cx = f.x + P.x * 16, base = f.y + 110 * s - scrollP * 110;
        ctx.save(); shadow(true, 30);
        [[0, 0, 170, 120], [8, -118, 140, 104], [-6, -214, 110, 86]].forEach(function (b, i) {
          var sway = Math.sin(time * 1.1 + i * 0.6) * 0.02 * (i + 1);
          box(cx + b[0] * s + Math.sin(time + i) * 2, base + b[1] * s - b[3] * s / 2, b[2] * s, b[3] * s, sway, 1);
        });
        ctx.restore();
      }
    };
  };

  // Gardens: leaves fluttering down, grass that bends away from the pointer.
  S.garden = function () {
    var leaves = [], blades = [];
    var GREENS = ["#4c7a3a", "#6c9a4a", "#8bb35f", "#3c6230", "#a9c46f"];
    return {
      init: function () {
        for (var i = 0; i < count(26); i++) leaves.push({ x: rand(0, W), y: rand(-H, H), z: rand(0.35, 1.25), a: rand(0, TAU), flip: rand(0, TAU), vy: rand(16, 34), col: pick(GREENS) });
        for (var x = mobile ? 0 : W * 0.42; x < W; x += mobile ? 7 : 6) blades.push({ x: x + rand(-3, 3), h: rand(30, 90), col: pick(GREENS), ph: rand(0, TAU) });
      },
      update: function (dt) {
        leaves.forEach(function (l) { l.y += l.vy * l.z * dt; l.x += (Math.sin(l.flip) * 18 + P.x * 10) * dt; l.flip += dt * 1.8; l.a += dt * 0.6; if (l.y > H + 40) { l.y = -40; l.x = rand(0, W); } });
      },
      draw: function () {
        depthSort(leaves).forEach(function (l) {
          ctx.save(); ctx.translate(sx(l), sy(l)); ctx.rotate(l.a); ctx.scale(Math.cos(l.flip), 1);
          ctx.globalAlpha = 0.3 + 0.6 * clamp(l.z - 0.3, 0, 1); var s = 16 * l.z;
          ctx.fillStyle = l.z > 1.05 ? C.accent : l.col;
          ctx.beginPath(); ctx.moveTo(0, -s); ctx.quadraticCurveTo(s * 0.8, 0, 0, s); ctx.quadraticCurveTo(-s * 0.8, 0, 0, -s); ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 0.8; ctx.beginPath(); ctx.moveTo(0, -s); ctx.lineTo(0, s); ctx.stroke();
          ctx.restore();
        });
        ctx.globalAlpha = 0.85;
        var ground = H + 4 - scrollP * 60;
        blades.forEach(function (b) {
          var away = P.px > -500 ? clamp((b.x - P.px) / 120, -1, 1) * clamp(1 - Math.abs(ground - b.h - P.py) / 220, 0, 1) : 0;
          var bend = Math.sin(time * 1.3 + b.ph) * 6 + away * 26;
          ctx.strokeStyle = C.dark ? mix(b.col, "#000", 0.3) : b.col; ctx.lineWidth = 2.2;
          ctx.beginPath(); ctx.moveTo(b.x, ground); ctx.quadraticCurveTo(b.x + bend * 0.3, ground - b.h * 0.5, b.x + bend, ground - b.h); ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Pets: a bouncing ball with squash and stretch, paw prints padding across.
  S.pets = function () {
    var prints = [], step = 0, hearts = [];
    return {
      init: function () { for (var i = 0; i < count(10); i++) hearts.push({ x: rand(0, W), y: rand(0, H), z: rand(0.4, 1.2), ph: rand(0, TAU) }); },
      tap: function (x, y) { for (var i = 0; i < 5; i++) hearts.push({ x: x + rand(-20, 20), y: y + rand(-10, 10), z: rand(0.9, 1.3), ph: 0, burst: 1 }); },
      update: function (dt) {
        step += dt;
        if (step > 0.42) {
          step = 0; var n = prints.length, base = mobile ? H - 60 : H * 0.84;
          var x = ((time * 70) % (W + 200)) - 100;
          prints.push({ x: x, y: base + (n % 2 ? -18 : 18) + Math.sin(time * 0.6) * 20, a: 0.15, life: 1 });
        }
        prints.forEach(function (p) { p.life -= dt * 0.28; });
        prints = prints.filter(function (p) { return p.life > 0; });
        hearts.forEach(function (h) { h.ph += dt; h.y -= 12 * h.z * dt; if (h.burst) h.burst -= dt * 0.5; if (h.y < -20) { h.y = H + 20; h.x = rand(0, W); } });
        hearts = hearts.filter(function (h) { return !h.burst || h.burst > 0; });
      },
      draw: function () {
        prints.forEach(function (p) {
          ctx.save(); ctx.translate(p.x, p.y - scrollP * 80); ctx.rotate(Math.PI / 2 + p.a); ctx.globalAlpha = 0.28 * p.life; ctx.fillStyle = C.accent;
          ctx.beginPath(); ctx.ellipse(0, 4, 8, 7, 0, 0, TAU); ctx.fill();
          [[-9, -6], [-3, -11], [3, -11], [9, -6]].forEach(function (t) { ctx.beginPath(); ctx.ellipse(t[0], t[1], 2.6, 3.4, 0, 0, TAU); ctx.fill(); });
          ctx.restore();
        });
        hearts.forEach(function (h) {
          var x = sx(h), y = sy(h), s = 6 * h.z;
          ctx.globalAlpha = (h.burst !== undefined ? clamp(h.burst, 0, 1) : 0.35) * h.z; ctx.fillStyle = C.accent;
          ctx.beginPath(); ctx.moveTo(x, y + s); ctx.bezierCurveTo(x - s * 2, y - s * 0.5, x - s, y - s * 1.8, x, y - s * 0.6); ctx.bezierCurveTo(x + s, y - s * 1.8, x + s * 2, y - s * 0.5, x, y + s); ctx.fill();
        });
        var f = focal(), s = f.s, t = (time * 1.1) % 1, hgt = 4 * t * (1 - t);
        var cx = f.x + P.x * 16, floor = f.y + 110 * s - scrollP * 110, r = 52 * s;
        var squash = t < 0.06 || t > 0.94 ? 0.82 : 1, cy = floor - r * squash - hgt * 190 * s;
        ctx.globalAlpha = 0.18 * (1 - hgt * 0.6); ctx.fillStyle = "#000"; ctx.beginPath(); ctx.ellipse(cx, floor + 4, r * (1 - hgt * 0.4), 9 * s, 0, 0, TAU); ctx.fill();
        ctx.globalAlpha = 1;
        var g = ctx.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r);
        g.addColorStop(0, mix(C.accent, "#fff", 0.5)); g.addColorStop(1, mix(C.accent, "#000", 0.2));
        ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(cx, cy, r / squash, r * squash, 0, 0, TAU); ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.75)"; ctx.lineWidth = 3 * s;
        ctx.beginPath(); ctx.ellipse(cx, cy, r / squash * 0.98, r * squash * 0.4, time * 2, 0, Math.PI); ctx.stroke();
      }
    };
  };

  // Food / cafes: a cup with curling steam, coffee beans turning in space.
  S.food = function () {
    var beans = [];
    return {
      init: function () { for (var i = 0; i < count(18); i++) beans.push({ x: rand(0, W), y: rand(0, H), z: rand(0.35, 1.25), a: rand(0, TAU), va: rand(-0.8, 0.8), roll: rand(0, TAU), vy: rand(-12, -4) }); },
      update: function (dt) { beans.forEach(function (b) { b.y += b.vy * b.z * dt; b.a += b.va * dt; b.roll += dt * 1.2; if (b.y < -30) { b.y = H + 30; b.x = rand(0, W); } }); },
      draw: function () {
        var bean = function (b) {
          ctx.save(); ctx.translate(sx(b), sy(b)); ctx.rotate(b.a); var s = 10 * b.z, k = Math.abs(Math.cos(b.roll)) * 0.5 + 0.5;
          ctx.globalAlpha = 0.25 + 0.6 * clamp(b.z - 0.3, 0, 1);
          ctx.fillStyle = C.dark ? "#6b4a35" : "#4a2f20"; ctx.beginPath(); ctx.ellipse(0, 0, s * k, s * 1.35, 0, 0, TAU); ctx.fill();
          ctx.strokeStyle = "rgba(255,230,200,.35)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(0, -s * 1.2); ctx.quadraticCurveTo(s * 0.4 * k, 0, 0, s * 1.2); ctx.stroke();
          ctx.restore();
        };
        depthSort(beans); beans.forEach(function (b) { if (b.z < 0.95) bean(b); });
        var f = focal(), s = f.s, cx = f.x + P.x * 14, cy = f.y + 30 * s - scrollP * 110;
        // steam
        ctx.lineCap = "round";
        for (var k = 0; k < 3; k++) {
          ctx.beginPath();
          for (var i = 0; i <= 40; i++) {
            var t = i / 40, y = cy - 60 * s - t * 210 * s, x = cx + (k - 1) * 26 * s + Math.sin(t * 6 + time * 1.6 + k * 2) * 18 * s * t + P.x * 30 * t;
            if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
          }
          ctx.strokeStyle = C.dark ? "rgba(255,255,255,.35)" : rgba(C.ink, 0.16); ctx.lineWidth = 6 * s; ctx.stroke();
        }
        // cup
        ctx.save(); shadow(true, 30);
        ctx.fillStyle = C.dark ? "#f1ede6" : "#ffffff";
        ctx.beginPath(); ctx.moveTo(cx - 80 * s, cy - 48 * s); ctx.lineTo(cx + 80 * s, cy - 48 * s); ctx.quadraticCurveTo(cx + 74 * s, cy + 70 * s, cx, cy + 74 * s); ctx.quadraticCurveTo(cx - 74 * s, cy + 70 * s, cx - 80 * s, cy - 48 * s); ctx.fill();
        ctx.restore();
        ctx.strokeStyle = C.dark ? "#f1ede6" : "#ffffff"; ctx.lineWidth = 12 * s; ctx.beginPath(); ctx.arc(cx + 88 * s, cy + 2 * s, 26 * s, -1.2, 1.3); ctx.stroke();
        ctx.fillStyle = C.accent; ctx.fillRect(cx - 78 * s, cy - 10 * s, 156 * s, 16 * s);
        ctx.fillStyle = "#5a3826"; ctx.beginPath(); ctx.ellipse(cx, cy - 48 * s, 80 * s, 14 * s, 0, 0, TAU); ctx.fill();
        ctx.strokeStyle = "rgba(255,240,220,.85)"; ctx.lineWidth = 2.5 * s;
        ctx.beginPath(); ctx.moveTo(cx - 20 * s, cy - 50 * s); ctx.quadraticCurveTo(cx, cy - 58 * s + Math.sin(time) * 2, cx + 20 * s, cy - 50 * s); ctx.stroke();
        ctx.beginPath(); ctx.ellipse(cx, cy - 48 * s, 12 * s, 5 * s, 0, 0, TAU); ctx.stroke();
        beans.forEach(function (b) { if (b.z >= 0.95) bean(b); });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Wineries / breweries: a glass whose wine tilts with the pointer, bubbles rising.
  S.winery = function () {
    var bubbles = [], tilt = 0;
    return {
      init: function () { for (var i = 0; i < count(40); i++) bubbles.push({ x: rand(0, W), y: rand(0, H), z: rand(0.3, 1.2), r: rand(1.5, 4.5), vy: rand(-30, -12), ph: rand(0, TAU) }); },
      update: function (dt) {
        tilt += ((P.x * 0.35 + Math.sin(time * 0.8) * 0.06) - tilt) * dt * 2.5;
        bubbles.forEach(function (b) { b.ph += dt * 3; b.y += b.vy * b.z * dt; b.x += Math.sin(b.ph) * 4 * dt; if (b.y < -10) { b.y = H + 10; b.x = rand(0, W); } });
      },
      draw: function () {
        bubbles.forEach(function (b) { ctx.globalAlpha = 0.18 + 0.4 * b.z; ctx.strokeStyle = C.accent; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(sx(b), sy(b), b.r * b.z, 0, TAU); ctx.stroke(); });
        ctx.globalAlpha = 1;
        var f = focal(), s = f.s, cx = f.x + P.x * 10, cy = f.y - 40 * s - scrollP * 110, R = 92 * s;
        ctx.save();
        ctx.beginPath(); ctx.moveTo(cx - R, cy - 90 * s); ctx.bezierCurveTo(cx - R * 1.05, cy + 40 * s, cx - R * 0.5, cy + 110 * s, cx, cy + 112 * s); ctx.bezierCurveTo(cx + R * 0.5, cy + 110 * s, cx + R * 1.05, cy + 40 * s, cx + R, cy - 90 * s);
        ctx.closePath(); ctx.save(); ctx.clip();
        var lvl = cy + 10 * s;
        ctx.beginPath(); ctx.moveTo(cx - R * 1.2, lvl + Math.tan(tilt) * R * 1.2);
        for (var x = -R * 1.2; x <= R * 1.2; x += 6) ctx.lineTo(cx + x, lvl - Math.tan(tilt) * x + Math.sin(x * 0.05 + time * 2) * 3 * s);
        ctx.lineTo(cx + R * 1.2, cy + 200 * s); ctx.lineTo(cx - R * 1.2, cy + 200 * s); ctx.closePath();
        var g = ctx.createLinearGradient(0, lvl, 0, cy + 112 * s);
        g.addColorStop(0, mix(C.accent, "#fff", 0.15)); g.addColorStop(1, mix(C.accent, "#000", 0.35));
        ctx.fillStyle = g; ctx.fill(); ctx.restore();
        ctx.strokeStyle = C.dark ? "rgba(255,255,255,.55)" : rgba(C.ink, 0.35); ctx.lineWidth = 2; ctx.stroke();
        ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = 3 * s; ctx.beginPath(); ctx.moveTo(cx - R * 0.72, cy - 60 * s); ctx.quadraticCurveTo(cx - R * 0.8, cy + 20 * s, cx - R * 0.45, cy + 70 * s); ctx.stroke();
        ctx.strokeStyle = C.dark ? "rgba(255,255,255,.55)" : rgba(C.ink, 0.35); ctx.lineWidth = 5 * s;
        ctx.beginPath(); ctx.moveTo(cx, cy + 112 * s); ctx.lineTo(cx, cy + 210 * s); ctx.moveTo(cx - 52 * s, cy + 214 * s); ctx.lineTo(cx + 52 * s, cy + 214 * s); ctx.stroke();
        ctx.restore();
      }
    };
  };

  // Florists / photographers / celebrants: petals fluttering, a camera iris breathing.
  S.creative = function () {
    var petals = [];
    var TONES = ["#f6d6d6", "#f2c4c9", "#fbeee6", "#e8b4bc"];
    return {
      init: function () { for (var i = 0; i < count(30); i++) petals.push({ x: rand(0, W), y: rand(-H, H), z: rand(0.35, 1.25), a: rand(0, TAU), flip: rand(0, TAU), vy: rand(14, 30), col: Math.random() < 0.25 ? null : pick(TONES) }); },
      update: function (dt) { petals.forEach(function (p) { p.y += p.vy * p.z * dt; p.x += (Math.sin(p.flip * 0.7) * 22 + P.x * 12) * dt; p.flip += dt * 2; p.a += dt * 0.5; if (p.y > H + 30) { p.y = -30; p.x = rand(0, W); } }); },
      draw: function () {
        var petal = function (p) {
          ctx.save(); ctx.translate(sx(p), sy(p)); ctx.rotate(p.a); ctx.scale(1, Math.cos(p.flip)); var s = 11 * p.z;
          ctx.globalAlpha = 0.35 + 0.55 * clamp(p.z - 0.3, 0, 1); ctx.fillStyle = p.col || C.soft;
          ctx.beginPath(); ctx.moveTo(0, -s); ctx.bezierCurveTo(s, -s * 0.6, s * 0.8, s * 0.8, 0, s); ctx.bezierCurveTo(-s * 0.8, s * 0.8, -s, -s * 0.6, 0, -s); ctx.fill(); ctx.restore();
        };
        depthSort(petals); petals.forEach(function (p) { if (p.z < 0.95) petal(p); });
        var f = focal(), s = f.s, cx = f.x + P.x * 14, cy = f.y - scrollP * 110, R = 118 * s;
        var open = 0.35 + 0.3 * (Math.sin(time * 0.7) * 0.5 + 0.5) + scrollP * 0.3;
        ctx.save(); ctx.globalAlpha = 1; shadow(true, 36);
        ctx.fillStyle = C.dark ? "#1d1d20" : "#232326"; ctx.beginPath(); ctx.arc(cx, cy, R * 1.12, 0, TAU); ctx.fill(); shadow(false);
        ctx.fillStyle = mix(C.accent, "#000", 0.2); ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.fill();
        ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.clip();
        for (var i = 0; i < 7; i++) {
          var a = i / 7 * TAU + time * 0.15;
          ctx.save(); ctx.translate(cx, cy); ctx.rotate(a);
          ctx.fillStyle = i % 2 ? "#2c2c30" : "#36363b";
          ctx.beginPath(); ctx.moveTo(R * open, -R * 0.1); ctx.lineTo(R * 1.6, -R * 0.5); ctx.lineTo(R * 1.6, R * 1.2); ctx.lineTo(R * open * 0.6, R * 0.55); ctx.closePath(); ctx.fill();
          ctx.restore();
        }
        ctx.restore();
        ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, R * 1.06, 0, TAU); ctx.stroke();
        ctx.restore();
        petals.forEach(function (p) { if (p.z >= 0.95) petal(p); });
        ctx.globalAlpha = 1;
      }
    };
  };

  // Accountants / brokers: a growth line drawing itself over a quiet grid.
  S.professional = function () {
    var figures = [], pts = [];
    var F = ["%", "$", "+", "✓", "↗"];
    return {
      init: function () {
        for (var i = 0; i < count(16); i++) figures.push({ x: rand(0, W), y: rand(0, H), z: rand(0.35, 1.2), g: pick(F), vy: rand(-10, -4) });
        for (var k = 0; k <= 8; k++) pts.push(k === 0 ? 0.15 : clamp(pts[k - 1] + rand(-0.05, 0.16), 0.1, 0.95));
      },
      update: function (dt) { figures.forEach(function (fg) { fg.y += fg.vy * fg.z * dt; if (fg.y < -20) { fg.y = H + 20; fg.x = rand(0, W); } }); },
      draw: function () {
        figures.forEach(function (fg) { ctx.globalAlpha = 0.12 + 0.3 * fg.z; ctx.fillStyle = fg.z > 0.95 ? C.accent : C.ink; ctx.font = (14 + 18 * fg.z) + "px system-ui"; ctx.fillText(fg.g, sx(fg), sy(fg)); });
        var f = focal(), s = f.s, w = 320 * s, h = 210 * s, x0 = f.x - w / 2 + P.x * 14, y0 = f.y + h / 2 - scrollP * 110;
        ctx.globalAlpha = 1; ctx.save(); shadow(true, 34);
        ctx.fillStyle = C.dark ? "#1b1b1e" : "#ffffff"; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x0 - 24 * s, y0 - h - 30 * s, w + 48 * s, h + 54 * s, 18 * s) : ctx.rect(x0 - 24 * s, y0 - h - 30 * s, w + 48 * s, h + 54 * s); ctx.fill();
        ctx.restore();
        ctx.strokeStyle = rgba(C.ink, 0.08); ctx.lineWidth = 1;
        for (var gy = 0; gy <= 4; gy++) { ctx.beginPath(); ctx.moveTo(x0, y0 - gy * h / 4); ctx.lineTo(x0 + w, y0 - gy * h / 4); ctx.stroke(); }
        var prog = clamp(((time * 0.25) % 1.4), 0, 1), n = pts.length - 1, endIdx = prog * n;
        ctx.beginPath(); ctx.moveTo(x0, y0 - pts[0] * h);
        var lastX = x0, lastY = y0 - pts[0] * h;
        for (var i = 1; i <= Math.ceil(endIdx); i++) {
          var t = Math.min(1, endIdx - (i - 1)), xa = x0 + (i - 1) / n * w, ya = y0 - pts[i - 1] * h, xb = x0 + i / n * w, yb = y0 - pts[i] * h;
          lastX = xa + (xb - xa) * t; lastY = ya + (yb - ya) * t; ctx.lineTo(lastX, lastY);
        }
        ctx.lineTo(lastX, y0); ctx.lineTo(x0, y0); ctx.closePath();
        var g = ctx.createLinearGradient(0, y0 - h, 0, y0); g.addColorStop(0, rgba(C.accent, 0.25)); g.addColorStop(1, rgba(C.accent, 0));
        ctx.fillStyle = g; ctx.fill();
        ctx.beginPath(); ctx.moveTo(x0, y0 - pts[0] * h);
        for (var j = 1; j <= Math.ceil(endIdx); j++) { var tt = Math.min(1, endIdx - (j - 1)); ctx.lineTo(x0 + (j - 1 + tt) / n * w, y0 - (pts[j - 1] + (pts[j] - pts[j - 1]) * tt) * h); }
        ctx.strokeStyle = C.accent; ctx.lineWidth = 3 * s; ctx.lineJoin = "round"; ctx.stroke();
        ctx.fillStyle = C.accent; ctx.beginPath(); ctx.arc(lastX, lastY, 5 * s, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(lastX, lastY, 12 * s * (1 + Math.sin(time * 4) * 0.2), 0, TAU); ctx.fill(); ctx.globalAlpha = 1;
      }
    };
  };

  // Phone / computer repair: circuit traces with pulses travelling to a chip.
  S.tech = function () {
    var traces = [], pulses = [];
    function build() {
      traces = []; var f = focal(), n = count(16);
      for (var i = 0; i < n; i++) {
        var side = i % 4, pts = [], x, y;
        if (side === 0) { x = f.x - 46 * f.s; y = f.y + rand(-40, 40) * f.s; } else if (side === 1) { x = f.x + 46 * f.s; y = f.y + rand(-40, 40) * f.s; } else if (side === 2) { x = f.x + rand(-40, 40) * f.s; y = f.y - 46 * f.s; } else { x = f.x + rand(-40, 40) * f.s; y = f.y + 46 * f.s; }
        pts.push([x, y]);
        var dir = side === 0 ? [-1, 0] : side === 1 ? [1, 0] : side === 2 ? [0, -1] : [0, 1];
        for (var k = 0; k < 4; k++) {
          var len = rand(30, 110) * f.s; x += dir[0] * len; y += dir[1] * len; pts.push([x, y]);
          dir = dir[0] ? [0, Math.random() < 0.5 ? -1 : 1] : [Math.random() < 0.5 ? -1 : 1, 0];
          if (side < 2) dir = k % 2 ? [side === 0 ? -1 : 1, 0] : dir;
        }
        traces.push(pts);
      }
    }
    function lengthOf(pts) { var L = 0; for (var i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); return L; }
    function at(pts, d) { for (var i = 1; i < pts.length; i++) { var l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); if (d <= l) { var t = d / l; return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t]; } d -= l; } return pts[pts.length - 1]; }
    return {
      init: build, resize: build,
      tap: function () { traces.forEach(function (t, i) { pulses.push({ t: i, d: 0 }); }); },
      update: function (dt) {
        if (Math.random() < dt * 4) pulses.push({ t: (Math.random() * traces.length) | 0, d: 0 });
        pulses.forEach(function (p) { p.d += 160 * dt; });
        pulses = pulses.filter(function (p) { return traces[p.t] && p.d < lengthOf(traces[p.t]); });
      },
      draw: function () {
        var oy = -scrollP * 110, ox = P.x * 14;
        ctx.save(); ctx.translate(ox, oy);
        ctx.lineWidth = 1.5; ctx.strokeStyle = rgba(C.ink, C.dark ? 0.22 : 0.14); ctx.lineJoin = "round";
        traces.forEach(function (pts) {
          ctx.beginPath(); pts.forEach(function (p, i) { if (i) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]); }); ctx.stroke();
          var e = pts[pts.length - 1], near = Math.hypot(e[0] + ox - P.px, e[1] + oy - P.py) < 90;
          ctx.fillStyle = near ? C.accent : rgba(C.ink, 0.25); ctx.beginPath(); ctx.arc(e[0], e[1], near ? 5 : 3, 0, TAU); ctx.fill();
        });
        pulses.forEach(function (p) {
          var q = at(traces[p.t], p.d), g = ctx.createRadialGradient(q[0], q[1], 0, q[0], q[1], 14);
          g.addColorStop(0, rgba(C.accent, 1)); g.addColorStop(1, rgba(C.accent, 0)); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q[0], q[1], 14, 0, TAU); ctx.fill();
        });
        var f = focal(), s = f.s;
        shadow(true, 30); ctx.fillStyle = C.dark ? "#202024" : "#1f2024";
        ctx.beginPath(); ctx.roundRect ? ctx.roundRect(f.x - 52 * s, f.y - 52 * s, 104 * s, 104 * s, 12 * s) : ctx.rect(f.x - 52 * s, f.y - 52 * s, 104 * s, 104 * s); ctx.fill(); shadow(false);
        ctx.strokeStyle = C.accent; ctx.lineWidth = 2; ctx.strokeRect(f.x - 34 * s, f.y - 34 * s, 68 * s, 68 * s);
        ctx.fillStyle = rgba(C.accent, 0.35 + 0.25 * Math.sin(time * 3)); ctx.fillRect(f.x - 20 * s, f.y - 20 * s, 40 * s, 40 * s);
        ctx.restore();
      }
    };
  };

  // Everyone else: warm bokeh lights drifting, a few glints.
  S.local = function () {
    var orbs = [];
    return {
      init: function () { for (var i = 0; i < count(22); i++) orbs.push({ x: rand(0, W), y: rand(0, H), z: rand(0.35, 1.3), r: rand(18, 70), ph: rand(0, TAU), warm: Math.random() < 0.5 }); },
      update: function (dt) { orbs.forEach(function (o) { o.ph += dt * 0.5; o.y -= 6 * o.z * dt; o.x += Math.sin(o.ph) * 5 * dt; if (o.y < -80) { o.y = H + 80; o.x = rand(0, W); } }); },
      draw: function () {
        depthSort(orbs).forEach(function (o) {
          var x = sx(o), y = sy(o), r = o.r * o.z, col = o.warm ? "#f2b45a" : C.accent;
          var g = ctx.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, rgba(col, 0.35)); g.addColorStop(0.7, rgba(col, 0.12)); g.addColorStop(1, rgba(col, 0));
          ctx.globalAlpha = 0.5 + 0.5 * Math.sin(o.ph * 2) * 0.3; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
        });
        ctx.globalAlpha = 1;
      }
    };
  };

  /* ---- engine -------------------------------------------------------- */
  var scene = (S[hero.dataset.scene] || S.local)();

  function resize() {
    var r = hero.getBoundingClientRect();
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height; mobile = W < 760;
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    if (scene.resize) scene.resize();
  }
  function frame(now) {
    raf = 0;
    var dt = Math.min(0.05, (now - (last || now)) / 1000); last = now;
    time += dt;
    P.x += (P.tx - P.x) * Math.min(1, dt * 3); P.y += (P.ty - P.y) * Math.min(1, dt * 3);
    var r = hero.getBoundingClientRect();
    scrollP = clamp(-r.top / Math.max(1, r.height), 0, 1);
    if (scene.update) scene.update(dt);
    ctx.clearRect(0, 0, W, H);
    scene.draw();
    ctx.globalAlpha = 1; shadow(false);
    loop();
  }
  function loop() {
    if (!raf && inView && !document.hidden && !reduce && root.dataset.fx !== "off" && !hero.classList.contains("has-3d")) raf = requestAnimationFrame(frame);
  }
  function still() {   // one composed frame for reduced motion
    time = 2.3;
    for (var i = 0; i < 90; i++) if (scene.update) scene.update(1 / 30);
    ctx.clearRect(0, 0, W, H); scene.draw(); ctx.globalAlpha = 1; shadow(false);
  }

  readColours(); resize();
  if (scene.init) scene.init();
  if (reduce) still(); else loop();

  new ResizeObserver(function () { resize(); if (reduce) still(); }).observe(hero);
  if ("IntersectionObserver" in window) new IntersectionObserver(function (es) { inView = es[0].isIntersecting; loop(); }).observe(hero);
  document.addEventListener("visibilitychange", loop);
  // The colour panel changes the accent / paper / effects switch on <html>.
  new MutationObserver(function () {
    readColours();
    canvas.hidden = root.dataset.fx === "off";
    if (three) three.setActive(inView && !document.hidden && root.dataset.fx !== "off");
    if (reduce) still(); else loop();
  }).observe(root, { attributes: true, attributeFilter: ["style", "data-paper", "data-fx"] });

  function setPointer(e) {
    var r = hero.getBoundingClientRect();
    P.px = e.clientX - r.left; P.py = e.clientY - r.top;
    P.tx = clamp(P.px / r.width * 2 - 1, -1, 1); P.ty = clamp(P.py / r.height * 2 - 1, -1, 1);
    if (three) three.pointer(P.tx, P.ty);
  }
  hero.addEventListener("pointermove", setPointer, { passive: true });
  hero.addEventListener("pointerleave", function () { P.tx = 0; P.ty = 0; P.px = P.py = -999; });
  hero.addEventListener("pointerdown", function (e) {
    if (e.target.closest("a, button, input, label")) return;
    setPointer(e);
    if (scene.tap) scene.tap(P.px, P.py);
    if (three) three.tap();
  });
  hero.addEventListener("pointerleave", function () { if (three) three.pointer(0, 0); });

  /* ---- the 3D upgrade (React Three Fiber, hero3d.js) ------------------
     This 2D scene paints instantly; on devices that can afford it, the 3D
     scene downloads once the page has finished loading and is idle, then
     cross-fades in. Skipped for reduced motion, data saver, slow networks,
     low-memory devices and browsers without WebGL 2. */
  var three = null;
  function canDo3D() {
    if (reduce || !hero.dataset.hero3d) return false;
    var c = navigator.connection || {};
    if (c.saveData || /(^|-)2g|3g/.test(c.effectiveType || "")) return false;
    if (navigator.deviceMemory && navigator.deviceMemory < 3) return false;
    try { if (!document.createElement("canvas").getContext("webgl2")) return false; } catch (e) { return false; }
    return true;
  }
  function start3D() {
    var holder = document.createElement("div");
    holder.className = "hero-3d"; holder.setAttribute("aria-hidden", "true");
    hero.insertBefore(holder, canvas.nextSibling);
    var cs = getComputedStyle(root);
    var weak = (navigator.hardwareConcurrency || 4) < 6;
    import(new URL(hero.dataset.hero3d, document.baseURI).href).then(function (m) {
      three = m.mount(holder, {
        kind: hero.dataset.kind, theme: hero.dataset.scene, name: hero.dataset.name, initials: hero.dataset.initials,
        suburb: hero.dataset.suburb, accent: cs.getPropertyValue("--accent").trim(), dark: root.dataset.paper === "dark",
        paper: cs.getPropertyValue("--paper").trim(),
        displayFont: cs.getPropertyValue("--display").trim(), mobile: mobile, lite: mobile && weak,
        onReady: function () { setTimeout(function () { hero.classList.add("has-3d"); if (raf) { cancelAnimationFrame(raf); raf = 0; } }, 450); }
      });
      three.setActive(inView && !document.hidden && root.dataset.fx !== "off");
      scroll3D();
    }).catch(function () { holder.remove(); });
  }
  var scrollTick = false;
  function scroll3D() {
    scrollTick = false;
    if (!three) return;
    var r = hero.getBoundingClientRect();
    three.scroll(clamp(-r.top / Math.max(1, r.height), 0, 1));
  }
  window.addEventListener("scroll", function () { if (three && !scrollTick) { scrollTick = true; requestAnimationFrame(scroll3D); } }, { passive: true });
  if ("IntersectionObserver" in window) new IntersectionObserver(function (es) {
    if (three) three.setActive(es[0].isIntersecting && !document.hidden && root.dataset.fx !== "off");
  }).observe(hero);
  document.addEventListener("visibilitychange", function () { if (three) three.setActive(inView && !document.hidden && root.dataset.fx !== "off"); });
  if (canDo3D()) {
    var idle = window.requestIdleCallback || function (fn) { return setTimeout(fn, 200); };
    var go = function () { idle(start3D, { timeout: 2500 }); };
    if (document.readyState === "complete") go(); else window.addEventListener("load", go, { once: true });
  }
})();
