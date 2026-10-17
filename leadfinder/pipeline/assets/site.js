/* Shared by previews and finished client sites: scroll reveals, the hero
   name rising in, count-ups, parallax, scroll progress, the video further
   down, "Open now" from the business's hours, and the booking widget. */
(function () {
  "use strict";
  var doc = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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

  /* ---- liquid-glass rating lens on the about photo (glass.js) --------- */
  var lensMedia = document.querySelector("[data-lens]");
  if (lensMedia && !reduce && "IntersectionObserver" in window) {
    var lensIO = new IntersectionObserver(function (es) {
      if (!es[0].isIntersecting) return;
      lensIO.disconnect();
      import(new URL(lensMedia.dataset.lens, document.baseURI).href).then(function (m) { m.attach(lensMedia); }).catch(function () {});
    }, { rootMargin: "400px 0px" });
    lensIO.observe(lensMedia);
  }

  /* ---- the video: load and play only while it's on screen ------------- */
  document.querySelectorAll("video.cinema-video").forEach(function (video) {
    if (reduce || !("IntersectionObserver" in window)) return;
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) { video.preload = "auto"; video.play().catch(function () {}); } else video.pause();
      });
    }, { rootMargin: "200px 0px" }).observe(video);
  });

  /* ---- opening hours (Melbourne time) --------------------------------- */
  function melbourne() {
    var parts = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", year: "numeric", month: "numeric", day: "numeric", weekday: "long", hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date());
    var get = function (t) { return (parts.find(function (p) { return p.type === t; }) || {}).value; };
    return { y: +get("year"), m: +get("month") - 1, d: +get("day"), day: get("weekday"), mins: (+get("hour") % 24) * 60 + +get("minute") };
  }
  // "9 AM–5:30 PM", "9–11:30 am, 1–5 pm", "Open 24 hours", "Closed" → [[start, end] minutes]
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

  var byDay = null;
  var hoursEl = document.getElementById("site-hours");
  if (hoursEl) {
    try {
      byDay = {};
      JSON.parse(hoursEl.textContent).forEach(function (row) { byDay[row[0]] = ranges(row[1]); });
    } catch (e) { byDay = null; }
  }
  var now = melbourne();

  if (byDay && byDay[now.day]) {
    document.querySelectorAll('.hours tr[data-day="' + now.day + '"]').forEach(function (tr) { tr.classList.add("is-today"); });
    var today = byDay[now.day];
    var open = today.find(function (r) { return now.mins >= r[0] && now.mins < r[1]; });
    var text;
    if (open) text = open[1] >= 1440 && open[0] === 0 ? "Open 24 hours" : "Open now · closes " + fmt(open[1]);
    else {
      var later = today.find(function (r) { return r[0] > now.mins; });
      if (later) text = "Closed now · opens " + fmt(later[0]);
      else {
        var i = DAYS.indexOf(now.day);
        for (var k = 1; k <= 7 && !text; k++) {
          var d = DAYS[(i + k) % 7], rr = byDay[d];
          if (rr && rr.length) text = "Closed now · opens " + (k === 1 ? "tomorrow" : d.slice(0, 3)) + " " + fmt(rr[0][0]);
        }
      }
    }
    if (text) document.querySelectorAll("[data-open-status]").forEach(function (el) {
      el.hidden = false;
      el.classList.toggle("is-open", !!open);
      el.querySelector("b").textContent = text;
    });
  }

  /* ---- booking widget ------------------------------------------------- */
  var booker = document.getElementById("booker");
  if (booker) booking(booker);

  function booking(el) {
    var mode = el.dataset.mode, isFinal = el.dataset.final === "1";
    var form = el.querySelector(".bk-form");
    var steps = Array.prototype.slice.call(el.querySelectorAll(".bk-step"));
    var dots = Array.prototype.slice.call(el.querySelectorAll(".bk-progress li"));
    var next = el.querySelector(".bk-next"), back = el.querySelector(".bk-back"), err = el.querySelector(".bk-error");
    var done = el.querySelector(".bk-done"), daysEl = el.querySelector(".bk-days"), timesEl = el.querySelector(".bk-times");
    var nextLabel = next.innerHTML;
    var st = { step: 0, what: "", day: "", dayLabel: "", time: "" };

    // Days: the next 14 from today in Melbourne; closed days are shown but can't be picked.
    var html = "";
    for (var i = 0; i < 14; i++) {
      var dt = new Date(Date.UTC(now.y, now.m, now.d + i)), wd = DAYS[dt.getUTCDay()];
      var closed = byDay && byDay[wd] && byDay[wd].length === 0;
      if (i === 0 && byDay && byDay[wd]) closed = closed || !byDay[wd].some(function (r) { return r[1] - 60 > now.mins; });
      var iso = dt.toISOString().slice(0, 10);
      var label = (i === 0 ? "Today" : i === 1 ? "Tomorrow" : wd.slice(0, 3) + " " + dt.getUTCDate() + " " + MONTHS[dt.getUTCMonth()]);
      html += '<label class="bk-day' + (closed ? " is-closed" : "") + '"><input type="radio" name="day" value="' + iso + '" data-wd="' + wd + '" data-label="' + label + '"' + (closed ? " disabled" : "") + '>' +
        '<span><small>' + wd.slice(0, 3) + '</small><b>' + dt.getUTCDate() + '</b><em>' + (closed ? "Closed" : i === 0 ? "Today" : MONTHS[dt.getUTCMonth()]) + "</em></span></label>";
    }
    daysEl.innerHTML = html;

    function slots(wd, isToday) {
      if (mode === "quote") return null;
      var rs = byDay && byDay[wd] ? byDay[wd] : [[9 * 60, 17 * 60]];
      var out = [];
      rs.forEach(function (r) {
        for (var t = Math.ceil(r[0] / 30) * 30; t <= Math.min(r[1], 1440) - (mode === "table" ? 60 : 30); t += 30) {
          if (!isToday || t >= now.mins + 60) out.push(t);
        }
      });
      return out;
    }
    function renderTimes() {
      var input = form.querySelector('input[name="day"]:checked');
      if (!input) return;
      var list = slots(input.dataset.wd, input.value === daysEl.querySelector("input").value);
      timesEl.classList.toggle("is-windows", list === null);
      if (list === null) {
        timesEl.innerHTML = [["Morning", "7 – 10 am"], ["Midday", "10 am – 1 pm"], ["Afternoon", "1 – 5 pm"], ["Any time", "Whenever suits"]].map(function (w) {
          return '<label class="bk-time"><input type="radio" name="time" value="' + w[0] + '"><span>' + w[0] + "<small>" + w[1] + "</small></span></label>";
        }).join("");
      } else if (!list.length) {
        timesEl.innerHTML = '<p class="bk-empty">No times left that day — try another day.</p>';
      } else {
        timesEl.innerHTML = list.map(function (t) {
          return '<label class="bk-time"><input type="radio" name="time" value="' + fmt(t) + '"><span>' + fmt(t) + "</span></label>";
        }).join("");
      }
    }
    form.addEventListener("change", function (e) {
      err.textContent = "";
      if (e.target.name === "day") renderTimes();
      if (e.target.name === "what" || e.target.name === "day" || e.target.name === "time") setTimeout(function () { go(st.step + 1); }, 220);
    });

    function value(name) { var f = form.querySelector('[name="' + name + '"]:checked') || form.querySelector('[name="' + name + '"]'); return f ? f.value.trim() : ""; }
    function check(step) {
      if (step === 0 && !value("what")) return "Choose one to continue.";
      if (step === 1 && !form.querySelector('input[name="day"]:checked')) return "Pick a day.";
      if (step === 2 && !form.querySelector('input[name="time"]:checked')) return "Pick a time.";
      if (step === 3) {
        if (!value("name")) return "Please add your name.";
        if (value("phone").replace(/\D/g, "").length < 8) return "Please add a mobile number so we can confirm.";
      }
      return "";
    }
    function go(to) {
      if (to > st.step) for (var s = st.step; s < to; s++) { var problem = check(s); if (problem) { err.textContent = problem; return; } }
      if (to > 3) return finish();
      st.step = Math.max(0, to);
      steps.forEach(function (f, i) { f.classList.toggle("is-on", i === st.step); });
      dots.forEach(function (d, i) { d.classList.toggle("is-on", i === st.step); d.classList.toggle("is-done", i < st.step); });
      back.hidden = st.step === 0;
      next.innerHTML = st.step === 3 ? "Request booking" : nextLabel;
      err.textContent = "";
      var first = steps[st.step].querySelector("input:not([disabled])");
      if (st.step === 3 && first) setTimeout(function () { first.focus({ preventScroll: true }); }, 350);
    }
    function finish() {
      var day = form.querySelector('input[name="day"]:checked');
      var summary = value("what") + " · " + day.dataset.label + " · " + value("time");
      el.querySelector(".bk-summary").textContent = summary + " — for " + value("name") + ".";
      form.hidden = true;
      el.querySelector(".bk-progress").hidden = true;
      done.hidden = false;
      if (isFinal) {
        var body = "Booking request for " + el.dataset.biz + ": " + summary + ". Name: " + value("name") + ", mobile: " + value("phone") +
          (value("where") ? ", address: " + value("where") : "") + (value("note") ? ". " + value("note") : "");
        var link = el.dataset.mobile === "1" ? "sms:" + el.dataset.phone + "?&body=" + encodeURIComponent(body)
          : el.dataset.email ? "mailto:" + el.dataset.email + "?subject=" + encodeURIComponent("Booking request") + "&body=" + encodeURIComponent(body)
          : "tel:" + el.dataset.phone;
        window.location.href = link;
      }
    }
    next.addEventListener("click", function () { go(st.step + 1); });
    back.addEventListener("click", function () { go(st.step - 1); });
    dots.forEach(function (d, i) { d.addEventListener("click", function () { if (i < st.step) go(i); }); });
    form.addEventListener("submit", function (e) { e.preventDefault(); go(st.step + 1); });
    el.querySelector(".bk-again").addEventListener("click", function () {
      form.reset(); timesEl.innerHTML = ""; form.hidden = false; el.querySelector(".bk-progress").hidden = false; done.hidden = true; go(0);
    });
    // "Book this" arrows on the services list pre-pick the service.
    document.querySelectorAll("[data-pick]").forEach(function (a) {
      a.addEventListener("click", function () {
        var opt = Array.prototype.find.call(form.querySelectorAll('input[name="what"]'), function (o) { return o.value === a.dataset.pick; });
        if (opt) { opt.checked = true; setTimeout(function () { go(1); }, 500); }
      });
    });
  }
})();
