/* Motion and live details for the generated sites (previews and finished
   client sites): scroll reveals, the hero name rising in, count-ups, gentle
   parallax, scroll progress, and "Open now" from the business's hours. */
(function () {
  "use strict";
  var doc = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  requestAnimationFrame(function () { document.body.classList.add("is-ready"); });

  /* ---- reveal on scroll + count-ups ---------------------------------- */
  function countUp(scope) {
    scope.querySelectorAll("[data-count]").forEach(function (el) {
      var target = parseFloat(el.dataset.count), dec = +(el.dataset.decimals || 0);
      if (!isFinite(target) || reduce) return;
      var start = performance.now(), dur = 1600;
      (function tick(now) {
        var t = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - t, 4);
        el.textContent = (target * e).toLocaleString("en-AU", { minimumFractionDigits: dec, maximumFractionDigits: dec });
        if (t < 1) requestAnimationFrame(tick);
      })(start);
    });
  }
  var reveal = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add("is-in");
      countUp(e.target);
      reveal.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }) : null;
  document.querySelectorAll("[data-reveal]").forEach(function (el) {
    if (reveal) reveal.observe(el); else el.classList.add("is-in");
  });

  /* ---- scroll-linked: progress bar, nav, dock, parallax --------------- */
  var bar = document.querySelector(".progress i");
  var nav = document.querySelector(".nav");
  var dock = document.querySelector(".dock");
  var para = Array.prototype.slice.call(document.querySelectorAll("[data-parallax]"));
  var ticking = false;
  function onScroll() {
    ticking = false;
    var y = window.scrollY, h = doc.scrollHeight - window.innerHeight;
    if (bar) bar.style.setProperty("--p", h > 0 ? (y / h).toFixed(4) : 0);
    if (nav) nav.classList.toggle("is-scrolled", y > 24);
    if (dock) dock.classList.toggle("is-shown", y > window.innerHeight * 0.5);
    if (!reduce) para.forEach(function (img) {
      var r = img.parentElement.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) return;
      var progress = (r.top + r.height / 2 - window.innerHeight / 2) / window.innerHeight;
      img.style.transform = "translate3d(0," + (progress * -8 - 6).toFixed(2) + "%,0)";
    });
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(onScroll); }
  }, { passive: true });
  onScroll();

  /* ---- hero video: only play while visible ---------------------------- */
  var video = document.querySelector(".hero-media video");
  if (video) {
    if (reduce) { video.removeAttribute("autoplay"); video.pause(); }
    else if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) video.play().catch(function () {}); else video.pause(); });
      }).observe(video);
    }
  }

  /* ---- opening hours: today + open now (Melbourne time) --------------- */
  var hoursEl = document.getElementById("site-hours");
  if (!hoursEl) return;
  var hours;
  try { hours = JSON.parse(hoursEl.textContent); } catch (e) { return; }
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  function nowInMelbourne() {
    var parts = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", weekday: "long", hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date());
    var get = function (t) { return (parts.find(function (p) { return p.type === t; }) || {}).value; };
    return { day: get("weekday"), mins: (+get("hour") % 24) * 60 + +get("minute") };
  }
  // "9 am–5:30 pm", "9–11:30 am, 1–5 pm", "Open 24 hours", "Closed" → [[start, end] minutes]
  function parseTime(s, fallbackMer) {
    var m = /(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?/i.exec(s);
    if (!m) return null;
    var h = +m[1] % 12, mer = (m[3] || fallbackMer || "").toLowerCase().charAt(0);
    return { mins: (mer === "p" ? h + 12 : h) * 60 + +(m[2] || 0), mer: mer, explicit: !!m[3] };
  }
  function ranges(text) {
    text = (text || "").replace(/ | /g, " ");
    if (/24 hours/i.test(text)) return [[0, 1440]];
    if (/closed/i.test(text)) return [];
    return text.split(/,|;/).map(function (part) {
      var bits = part.split(/[–—-]|\bto\b/);
      if (bits.length < 2) return null;
      var end = parseTime(bits[1]);
      var start = parseTime(bits[0], end && end.mer);
      if (!start || !end) return null;
      if (!start.explicit && start.mins > end.mins) start.mins -= 12 * 60;   // "11–2 pm" = 11 am
      var e = end.mins === 0 ? 1440 : end.mins;                                // "12 am" closing = midnight
      return e > start.mins ? [start.mins, e] : [start.mins, e + 1440];
    }).filter(Boolean);
  }
  function fmt(mins) {
    mins = mins % 1440;
    var h = Math.floor(mins / 60), m = mins % 60, mer = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return h + (m ? ":" + String(m).padStart(2, "0") : "") + " " + mer;
  }
  var byDay = {};
  hours.forEach(function (row) { byDay[row[0]] = ranges(row[1]); });
  var now = nowInMelbourne();
  document.querySelectorAll('.hours tr[data-day="' + now.day + '"]').forEach(function (tr) { tr.classList.add("is-today"); });

  var today = byDay[now.day] || [];
  var open = today.find(function (r) { return now.mins >= r[0] && now.mins < r[1]; });
  var text;
  if (open) {
    text = open[1] >= 1440 && open[0] === 0 ? "Open 24 hours" : "Open now · closes " + fmt(open[1]);
  } else {
    var later = today.find(function (r) { return r[0] > now.mins; });
    if (later) text = "Closed now · opens " + fmt(later[0]);
    else {
      var i = DAYS.indexOf(now.day);
      for (var k = 1; k <= 7 && !text; k++) {
        var d = DAYS[(i + k) % 7], r = byDay[d];
        if (r && r.length) text = "Closed now · opens " + (k === 1 ? "tomorrow" : d.slice(0, 3)) + " " + fmt(r[0][0]);
      }
    }
  }
  if (!text || !byDay[now.day]) return;
  document.querySelectorAll("[data-open-status]").forEach(function (el) {
    el.hidden = false;
    el.classList.toggle("is-open", !!open);
    el.querySelector("b").textContent = text;
  });
})();
