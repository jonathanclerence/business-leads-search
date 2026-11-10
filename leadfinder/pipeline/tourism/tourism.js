/* Sri Lanka tourism previews: glass nav with a sliding lens, the mobile
   sheet, the floating "Book" button, the booking forms (preview mode) and
   the surfing chameleon, each on its own. */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- nav: a lens that slides under the link you point at ------------- */
  var nav = document.querySelector("[data-nav]");
  if (nav) {
    var links = nav.querySelector(".nav-links");
    var lens = nav.querySelector(".nav-lens");
    var current = null;
    function moveLens(a) {
      if (!a || !lens) return;
      lens.style.width = a.offsetWidth + "px";
      lens.style.transform = "translateX(" + a.offsetLeft + "px)";
      lens.dataset.on = "true";
    }
    if (links) {
      links.querySelectorAll(".nav-link").forEach(function (a) {
        a.addEventListener("pointerenter", function () { moveLens(a); });
        a.addEventListener("focus", function () { moveLens(a); });
      });
      links.addEventListener("pointerleave", function () { if (current) moveLens(current); else lens.dataset.on = "false"; });
    }
    // Keep the lens on the section you are reading.
    var targets = Array.prototype.slice.call(nav.querySelectorAll(".nav-link")).map(function (a) {
      return { a: a, el: document.querySelector(a.getAttribute("href")) };
    }).filter(function (t) { return t.el; });
    if ("IntersectionObserver" in window && targets.length) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          var t = targets.filter(function (x) { return x.el === e.target; })[0];
          if (t) { current = t.a; moveLens(current); }
        });
      }, { rootMargin: "-45% 0px -50% 0px" });
      targets.forEach(function (t) { io.observe(t.el); });
    }
    var burger = nav.querySelector(".nav-burger"), sheet = nav.querySelector(".nav-sheet");
    if (burger && sheet) {
      burger.addEventListener("click", function () {
        var open = burger.getAttribute("aria-expanded") !== "true";
        burger.setAttribute("aria-expanded", String(open));
        sheet.dataset.open = String(open);
      });
      sheet.querySelectorAll("a").forEach(function (a) {
        a.addEventListener("click", function () { burger.setAttribute("aria-expanded", "false"); sheet.dataset.open = "false"; });
      });
    }
    var dock = document.querySelector("[data-dock]"), hero = document.querySelector(".hero");
    function onScroll() {
      var y = window.scrollY;
      nav.classList.toggle("is-scrolled", y > 40);
      if (dock && hero) dock.classList.toggle("is-on", y > hero.offsetHeight * 0.8 && y < document.body.scrollHeight - window.innerHeight * 1.6);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---- booking forms: preview mode -------------------------------------- */
  var today = new Date(), iso = function (d) { return d.toISOString().slice(0, 10); };
  document.querySelectorAll("[data-book]").forEach(function (form) {
    form.querySelectorAll('input[type="date"]').forEach(function (inp, i) {
      var d = new Date(today.getTime() + (14 + i * 3) * 864e5);
      inp.min = iso(today); if (!inp.value) inp.value = iso(d);
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var done = form.querySelector(".book-done");
      if (done) { done.hidden = false; }
      var btn = form.querySelector('button[type="submit"]');
      if (btn) btn.blur();
    });
  });

  /* ---- today's opening hours ------------------------------------------- */
  var days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var name = days[today.getDay()];
  document.querySelectorAll(".hours tr").forEach(function (tr) {
    var th = tr.querySelector("th");
    if (th && th.textContent.trim() === name) tr.setAttribute("data-today", "");
  });
  document.querySelectorAll("[data-today]").forEach(function (el) {
    try {
      var rows = JSON.parse(el.getAttribute("data-today") || "[]");
      rows.forEach(function (r) { if (r[0] === name) el.textContent = r[1]; });
    } catch (err) {}
  });

  /* ---- the filmed chameleon ---------------------------------------------
     The film is kept whole (sea and surfer together) and encoded twice, once
     forwards and once backwards. The pointer, or a sideways drag on a phone,
     takes him back up the wave or sends him on, and the film plays there at
     real video frame rate, forwards or backwards, quicker the further it has
     to go. Changing direction swaps to the other copy at the mirrored frame,
     so there is never a jump. Let go and he rides on down the wave to the
     end, and waits there. */
  var stage = document.querySelector("[data-surf-stage]");
  if (stage && !reduce && !(navigator.connection && navigator.connection.saveData)) {
    var vf = stage.querySelector(".ride-f"), vr = stage.querySelector(".ride-r");
    var big = stage.getBoundingClientRect().width > 600;          // phones get the light clips
    var src = stage.getAttribute(big ? "data-lg" : "data-sm");
    var D = 0, active = vf, flipping = false, revReady = false, running = false, seen = true;
    var input = null, drag = null;
    var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
    var noop = function () {};
    var pos = function () { return active === vf ? vf.currentTime : D - vr.currentTime; };

    vf.muted = vr.muted = true;
    vf.preload = "auto"; vf.src = src;
    vf.addEventListener("loadedmetadata", function () { D = vf.duration || 0; });
    vf.addEventListener("playing", function () { stage.classList.add("is-live"); }, { once: true });
    vf.addEventListener("canplay", start, { once: true });
    // The backwards copy follows once the first can play.
    function loadRev() {
      if (vr.src) return;
      vr.preload = "auto"; vr.src = src.replace(/\.mp4$/, "-rev.mp4");
      vr.addEventListener("loadeddata", function () { revReady = true; }, { once: true });
      var p = vr.play();                        // iOS only buffers what has played
      if (p && p.then) p.then(function () { if (active !== vr) vr.pause(); }, noop);
    }
    vf.addEventListener("canplaythrough", loadRev, { once: true });
    setTimeout(loadRev, 2500);

    function show(v) {
      (v === vf ? vr : vf).classList.remove("on"); v.classList.add("on");
    }
    // Turn round: hold this frame, put the other copy on the same frame, swap.
    function flip() {
      flipping = true;
      var next = active === vf ? vr : vf, done = false;
      active.pause();
      function swap() {
        if (done) return; done = true;
        show(next); active = next; flipping = false;
      }
      next.addEventListener("seeked", swap, { once: true });
      setTimeout(swap, 450);
      var p = pos();                            // the same moment, on the other copy's clock
      next.currentTime = clamp(next === vr ? D - p : p, 0, D - 0.001);
    }
    // A few fixed speeds: changing speed every frame makes some players stutter.
    var RATES = [0.35, 0.5, 0.7, 1, 1.4, 2, 2.6];
    function setRate(v, r) {
      for (var i = 0; i < RATES.length - 1 && RATES[i] < r * 0.92; i++);
      if (v.playbackRate !== RATES[i]) v.playbackRate = RATES[i];
    }

    var HOLD = 1400;                                  // pause after you let go, then ride on
    function tick(now) {
      if (!seen) { running = false; active.pause(); return; }
      requestAnimationFrame(tick);
      if (flipping || !D) return;
      var p = pos(), want, d, speed;
      var engaged = !!(input && ((drag && drag.live) || now - input.at < HOLD));
      if (engaged) {                                  // go to the moment you chose, and wait there
        want = input.t; d = want - p;
        if (Math.abs(d) < 0.02) { if (!active.paused) active.pause(); return; }
        speed = clamp(Math.abs(d) * 3.4, 0.3, 2.6);
      } else {                                        // ride on down the wave, and stop at the end
        want = D - 0.05; d = want - p;
        if (d < 0.02) { if (!active.paused) active.pause(); return; }
        speed = 1;
      }
      var dir = d > 0 ? 1 : -1;
      if (dir < 0 && !revReady) {                     // backwards copy not here yet
        if (active !== vf) { show(vf); active = vf; }
        if (!vf.paused) vf.pause();
        if (!vf.seeking) vf.currentTime = Math.max(want, p - speed / 24);
        return;
      }
      if (dir !== (active === vf ? 1 : -1)) { flip(); return; }
      setRate(active, speed);
      if (active.paused && !active.ended) active.play().catch(noop);
    }
    function start() {
      if (running || !seen) return;
      running = true;
      requestAnimationFrame(tick);
    }

    // Desktop: moving the mouse left takes him back up the wave, right sends
    // him on; across about half the window is the whole ride.
    var lastX = null;
    window.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse" || !D) return;
      var now = performance.now(), dx = lastX === null ? 0 : e.clientX - lastX;
      lastX = e.clientX;
      if (!dx) return;
      var from = input && now - input.at < HOLD ? input.t : pos();
      input = { t: clamp(from + dx / (window.innerWidth * 0.55) * D, 0.05, D - 0.05), at: now };
    }, { passive: true });
    // Phones and tablets: drag sideways on the film; up and down still scrolls.
    stage.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" || !D) return;
      drag = { x: e.clientX, y: e.clientY, t: pos(), w: stage.clientWidth, id: e.pointerId, live: false };
    });
    stage.addEventListener("pointermove", function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.live) {
        if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }
        if (Math.abs(dx) < 6) return;
        drag.live = true; stage.classList.remove("show-hint");
        try { stage.setPointerCapture(e.pointerId); } catch (err) {}
      }
      input = { t: clamp(drag.t + dx / drag.w * D * 1.2, 0.05, D - 0.05), at: performance.now() };
    });
    function endDrag() { if (drag && input) input.at = performance.now(); drag = null; }
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
    if (!window.matchMedia("(pointer: fine)").matches) {
      stage.classList.add("show-hint");
      setTimeout(function () { stage.classList.remove("show-hint"); }, 6000);
    }

    // Only run while he is on screen.
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        seen = es[0].isIntersecting && !document.hidden;
        if (seen && vf.readyState >= 2) start();
      }).observe(stage);
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) seen = false;
      else { var r = stage.getBoundingClientRect(); seen = r.bottom > 0 && r.top < window.innerHeight; }
      if (seen && vf.readyState >= 2) start();
    });
  }

  /* ---- the chameleon: two eyes, two minds ------------------------------ */
  var cham = document.querySelector("[data-chameleon]");
  if (cham && !reduce) {
    var eyes = Array.prototype.slice.call(cham.querySelectorAll(".cw-eye")).map(function (g, i) {
      return { g: g, pupil: g.querySelector(".cw-pupil"), reach: i === 0 ? 6 : 8, lag: i === 0 ? 0.08 : 0.2, x: 0, y: 0, tx: 0, ty: 0 };
    });
    var pointer = null, idleAt = Date.now();
    window.addEventListener("pointermove", function (e) { pointer = { x: e.clientX, y: e.clientY }; idleAt = Date.now(); }, { passive: true });
    var wander = { x: 0, y: 0, next: 0 };
    function frame(t) {
      var idle = !pointer || Date.now() - idleAt > 2600;
      if (idle && t > wander.next) { wander = { x: Math.random() * 2 - 1, y: Math.random() * 2 - 1, next: t + 900 + Math.random() * 1800 }; }
      eyes.forEach(function (eye, i) {
        var r = eye.g.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        var dx, dy;
        if (idle) {
          // Chameleons look in two directions at once: the far eye roams.
          dx = i === 0 ? wander.x : -wander.y; dy = i === 0 ? wander.y : wander.x * 0.6;
        } else {
          dx = pointer.x - cx; dy = pointer.y - cy;
          var len = Math.sqrt(dx * dx + dy * dy) || 1; dx /= len; dy /= len;
        }
        eye.tx = dx * eye.reach; eye.ty = dy * eye.reach;
        eye.x += (eye.tx - eye.x) * (1 - Math.pow(1 - eye.lag, 2));
        eye.y += (eye.ty - eye.y) * (1 - Math.pow(1 - eye.lag, 2));
        eye.pupil.setAttribute("transform", "translate(" + eye.x.toFixed(2) + " " + eye.y.toFixed(2) + ")");
      });
      requestAnimationFrame(frame);
    }
    if ("IntersectionObserver" in window) {
      var running = false;
      new IntersectionObserver(function (es) {
        if (es[0].isIntersecting && !running) { running = true; requestAnimationFrame(frame); }
      }).observe(cham);
    } else { requestAnimationFrame(frame); }
  }
})();
