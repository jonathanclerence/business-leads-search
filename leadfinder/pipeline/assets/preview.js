/* Preview websites only: the colour/style panel, the "Make it mine" /
   "Request changes" sheet and the demo enquiry form. Requests post to
   /api/preview-request, which emails DuNous (with the client's chosen look). */
(function () {
  "use strict";
  var sheet = document.getElementById("pv-sheet");
  var form = document.getElementById("pv-form");
  var status = form && form.querySelector(".pv-status");
  var submit = form && form.querySelector(".pv-submit");
  var openedAt = Date.now();
  var siteKey = (document.querySelector('meta[name="pv-ts"]') || {}).content || "";
  var tsToken = null, tsWidget = null, tsWaiters = [];

  // form.elements, not form.name etc.: those collide with built-in properties.
  function el(name) { return form.elements.namedItem(name); }

  function setIntent(intent) {
    el("intent").value = intent;
    form.querySelectorAll("[data-intent]").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.dataset.intent === intent));
    });
    form.querySelectorAll("[data-for]").forEach(function (el) {
      el.hidden = el.dataset.for !== intent;
    });
    submit.textContent = intent === "buy" ? "Yes — I want this website" : "Send my changes";
    status.textContent = "";
    status.className = "pv-status";
  }

  function loadTurnstile() {
    if (!siteKey || siteKey.indexOf("%%") === 0 || tsWidget !== null) return;
    tsWidget = "loading";
    window.pvTsReady = function () {
      tsWidget = window.turnstile.render(form.querySelector(".pv-ts"), {
        sitekey: siteKey,
        appearance: "interaction-only",
        callback: function (t) { tsToken = t; tsWaiters.splice(0).forEach(function (w) { w(t); }); },
        "expired-callback": function () { tsToken = null; },
        "error-callback": function () { tsToken = null; }
      });
    };
    var s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=pvTsReady";
    s.async = true;
    document.head.appendChild(s);
  }

  function token() {
    if (tsToken) return Promise.resolve(tsToken);
    return new Promise(function (resolve) {
      tsWaiters.push(resolve);
      setTimeout(function () { resolve(null); }, 15000);
    });
  }

  function open(intent) {
    setIntent(intent || "buy");
    if (typeof sheet.showModal === "function") sheet.showModal(); else sheet.setAttribute("open", "");
    loadTurnstile();
    setTimeout(function () { el("name").focus(); }, 60);
  }

  if (sheet && form) {
    document.querySelectorAll("[data-open]").forEach(function (b) {
      b.addEventListener("click", function () { open(b.dataset.open); });
    });
    form.querySelectorAll("[data-intent]").forEach(function (b) {
      b.addEventListener("click", function () { setIntent(b.dataset.intent); });
    });
    sheet.querySelector("[data-close]").addEventListener("click", function () { sheet.close(); });
    sheet.addEventListener("click", function (e) { if (e.target === sheet) sheet.close(); });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var intent = el("intent").value;
      var msg = el("message").value.trim();
      if (!el("name").value.trim()) return fail("Please enter your name.");
      if (!/^\S+@\S+\.\S+$/.test(el("email").value.trim())) return fail("Please enter a valid email so we can reply.");
      if (intent === "changes" && msg.length < 3) return fail("Tell us what you'd like changed.");

      submit.disabled = true;
      status.className = "pv-status";
      status.textContent = "Sending…";
      token().then(function (t) {
        return fetch("/api/preview-request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            intent: intent, slug: el("slug").value, business: el("business").value,
            name: el("name").value, email: el("email").value, phone: el("phone").value,
            domain: el("domain").value, message: msg + lookNote(), hp: el("hp").value, t: openedAt, token: t
          })
        });
      }).then(function (r) {
        return r.json().catch(function () { return { ok: false }; });
      }).then(function (res) {
        if (!res.ok) {
          var first = res.errors && Object.keys(res.errors)[0];
          throw new Error((first && res.errors[first]) || res.error || "Something went wrong.");
        }
        status.className = "pv-status ok";
        status.textContent = intent === "buy"
          ? "Thanks " + el("name").value.trim().split(" ")[0] + "! We'll email you within one business day."
          : "Thanks! We'll update your preview and email you the new link.";
        el("message").value = "";
        submit.textContent = "Sent ✓";
      }).catch(function (err) {
        fail(err.message || "Couldn't send — please try WhatsApp instead.");
        submit.disabled = false;
      }).then(function () {
        tsToken = null;
        if (window.turnstile && tsWidget && tsWidget !== "loading") window.turnstile.reset(tsWidget);
      });
    });
  }

  /* ---- colour / style panel -------------------------------------------- */
  var root = document.documentElement;
  var panel = document.getElementById("pv-panel");
  var slug = (document.querySelector('meta[name="pv-slug"]') || {}).content || "";
  var ORIGINAL = { accent: root.style.getPropertyValue("--accent").trim(), type: root.dataset.type, paper: root.dataset.paper };
  var look = Object.assign({}, ORIGINAL);
  var KEY = "pv-look:" + slug;

  function inkFor(hex) {
    var c = [1, 3, 5].map(function (i) {
      var v = parseInt(hex.substr(i, 2), 16) / 255;
      return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.36 ? "#141414" : "#ffffff";
  }
  function apply(next, save) {
    look = Object.assign(look, next);
    root.style.setProperty("--accent", look.accent);
    root.style.setProperty("--accent-ink", inkFor(look.accent));
    root.dataset.type = look.type;
    root.dataset.paper = look.paper;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = look.accent;
    if (panel) {
      panel.querySelectorAll("[data-accent]").forEach(function (b) {
        b.setAttribute("aria-checked", String(b.dataset.accent.toLowerCase() === look.accent.toLowerCase()));
      });
      panel.querySelectorAll(".seg").forEach(function (seg) {
        var v = seg.dataset.seg === "type" ? look.type : look.paper;
        seg.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.value === v)); });
      });
      var input = panel.querySelector("[data-accent-input]");
      if (input) input.value = look.accent;
    }
    if (save) { try { localStorage.setItem(KEY, JSON.stringify(look)); } catch (e) {} }
  }
  function lookNote() {
    var changed = ["accent", "type", "paper"].filter(function (k) { return look[k] !== ORIGINAL[k]; });
    if (!changed.length) return "";
    return "\n\n[Chosen look: colour " + look.accent + ", " + (look.type === "serif" ? "Classic" : "Modern") +
      " type, " + look.paper + " background]";
  }
  try { var saved = JSON.parse(localStorage.getItem(KEY) || "null"); if (saved && /^#[0-9a-f]{6}$/i.test(saved.accent)) apply(saved, false); } catch (e) {}
  apply({}, false);
  if (panel) {
    document.querySelectorAll("[data-panel]").forEach(function (b) {
      b.addEventListener("click", function () { panel.hidden = !panel.hidden; });
    });
    panel.querySelector("[data-panel-close]").addEventListener("click", function () { panel.hidden = true; });
    panel.querySelectorAll("[data-accent]").forEach(function (b) {
      b.addEventListener("click", function () { apply({ accent: b.dataset.accent }, true); });
    });
    panel.querySelector("[data-accent-input]").addEventListener("input", function (e) { apply({ accent: e.target.value }, true); });
    panel.querySelectorAll(".seg button").forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.parentElement.dataset.seg === "type" ? "type" : "paper";
        var next = {}; next[k] = b.dataset.value; apply(next, true);
      });
    });
    panel.querySelector("[data-reset]").addEventListener("click", function () {
      try { localStorage.removeItem(KEY); } catch (e) {}
      apply(ORIGINAL, false);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") panel.hidden = true; });
  }

  function fail(text) {
    status.className = "pv-status err";
    status.textContent = text;
    return false;
  }

  var demo = document.getElementById("demo-form");
  if (demo) {
    demo.addEventListener("submit", function (e) {
      e.preventDefault();
      demo.querySelector(".demo-note").hidden = false;
    });
  }
})();
