/* Sri Lanka tourism previews: glass nav with a sliding lens, the mobile
   sheet, the floating "Book" button, the booking forms (preview mode) and
   the surfing chameleon, whose eyes follow you, each on its own. */
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

  /* ---- a generated character clip, scrubbed by the pointer (or scroll) --- */
  var vid = document.querySelector("[data-scrub]");
  if (vid && !reduce) {
    var want = 0, seeking = false;
    function seek() {
      if (!vid.duration || seeking) return;
      if (Math.abs(vid.currentTime - want) < 0.02) return;
      seeking = true; vid.currentTime = want;
    }
    vid.addEventListener("seeked", function () { seeking = false; seek(); });
    vid.addEventListener("loadedmetadata", function () { want = vid.duration / 2; seek(); });
    var fine = window.matchMedia("(pointer: fine)").matches;
    if (fine) {
      window.addEventListener("pointermove", function (e) {
        var x = Math.min(1, Math.max(0, e.clientX / window.innerWidth));
        want = x * (vid.duration || 0) * 0.999; seek();
      }, { passive: true });
    } else {
      window.addEventListener("scroll", function () {
        var r = vid.getBoundingClientRect(), p = 1 - Math.min(1, Math.max(0, (r.top + r.height) / (window.innerHeight + r.height)));
        want = p * (vid.duration || 0) * 0.999; seek();
      }, { passive: true });
    }
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
