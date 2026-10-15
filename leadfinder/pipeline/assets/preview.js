/* Preview websites only: the Customise panel (colour, font, background,
   corners, animation, business name, editing any wording) and the single
   "Make it mine" form. Everything the owner changes is remembered on their
   device and sent along with the request to /api/preview-request. */
(function () {
  "use strict";
  var root = document.documentElement;
  var slug = (document.querySelector('meta[name="pv-slug"]') || {}).content || "";
  var KEY = "pv-look:" + slug, EDITS = "pv-edits:" + slug;
  function store(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function load(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } }

  /* ---- look: colour, font, background, corners, animation, name -------- */
  var ORIGINAL = {
    accent: root.style.getPropertyValue("--accent").trim(), type: root.dataset.type, paper: root.dataset.paper,
    corners: root.dataset.corners, fx: "on",
    name: ((document.querySelector("[data-bizname]") || {}).textContent || "").trim()
  };
  var look = Object.assign({}, ORIGINAL);
  var panel = document.getElementById("pv-panel");

  function inkFor(hex) {
    var c = [1, 3, 5].map(function (i) {
      var v = parseInt(hex.substr(i, 2), 16) / 255;
      return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.36 ? "#141414" : "#ffffff";
  }
  function initials(name) {
    var w = (name.match(/[A-Za-z0-9]+/g) || []).filter(function (x) { return ["the", "and", "of", "pty", "ltd"].indexOf(x.toLowerCase()) < 0; });
    return (w.slice(0, 2).map(function (x) { return x[0]; }).join("") || name.slice(0, 1)).toUpperCase();
  }
  function setName(name) {
    document.querySelectorAll("[data-bizname]").forEach(function (el) { el.textContent = name; });
    document.querySelectorAll("[data-initials]").forEach(function (el) { el.textContent = initials(name); });
    var h1 = document.querySelector("[data-hero-name]");
    if (h1) {
      h1.setAttribute("aria-label", name);
      h1.innerHTML = name.split(/\s+/).filter(Boolean).map(function (w, i) {
        var s = document.createElement("span"); s.textContent = w;
        return '<span class="w" aria-hidden="true"><span style="--i:' + i + '">' + s.innerHTML + "</span></span>";
      }).join(" ");
      var n = name.length;
      h1.className = "hero-name hero-name--" + (n <= 14 ? "xl" : n <= 24 ? "l" : n <= 36 ? "m" : "s");
    }
    var biz = document.querySelector('#pv-form [name="business"]');
    if (biz) biz.value = name;
  }
  function apply(next, save) {
    look = Object.assign(look, next);
    if (!/^#[0-9a-f]{6}$/i.test(look.accent)) look.accent = ORIGINAL.accent;
    root.style.setProperty("--accent", look.accent);
    root.style.setProperty("--accent-ink", inkFor(look.accent));
    root.dataset.type = look.type; root.dataset.paper = look.paper; root.dataset.corners = look.corners; root.dataset.fx = look.fx;
    if ("name" in next) setName(look.name || ORIGINAL.name);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = look.accent;
    if (panel) {
      panel.querySelectorAll("[data-accent]").forEach(function (b) {
        b.setAttribute("aria-checked", String(b.dataset.accent.toLowerCase() === look.accent.toLowerCase()));
      });
      panel.querySelectorAll(".seg").forEach(function (seg) {
        var v = look[seg.dataset.seg];
        seg.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.value === v)); });
      });
      panel.querySelector("[data-accent-input]").value = look.accent;
      var ni = panel.querySelector("[data-name-input]");
      if (document.activeElement !== ni) ni.value = look.name;
    }
    if (save) store(KEY, look);
  }

  /* ---- editing the words on the page ----------------------------------- */
  var edits = load(EDITS) || {};
  var editables = Array.prototype.slice.call(document.querySelectorAll("[data-edit]"));
  var originals = {}, originalHtml = {};
  editables.forEach(function (el) {
    originals[el.dataset.edit] = el.textContent.trim();
    originalHtml[el.dataset.edit] = el.innerHTML;
    if (edits[el.dataset.edit]) el.textContent = edits[el.dataset.edit];
  });
  var editbar = document.querySelector(".pv-editbar");
  function setEditing(on) {
    root.classList.toggle("is-editing", on);
    editables.forEach(function (el) { if (on) el.setAttribute("contenteditable", "plaintext-only"); else el.removeAttribute("contenteditable"); });
    if (editbar) editbar.hidden = !on;
    if (on && panel) panel.hidden = true;
  }
  editables.forEach(function (el) {
    el.addEventListener("input", function () {
      var v = el.textContent.trim();
      if (v && v !== originals[el.dataset.edit]) edits[el.dataset.edit] = v; else delete edits[el.dataset.edit];
      store(EDITS, edits);
    });
    el.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
    el.addEventListener("paste", function (e) {
      e.preventDefault();
      document.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text/plain"));
    });
  });
  document.querySelectorAll("[data-edit-toggle]").forEach(function (b) {
    b.addEventListener("click", function () { setEditing(!root.classList.contains("is-editing")); });
  });

  /* ---- panel wiring ---------------------------------------------------- */
  var saved = load(KEY);
  if (saved) apply(Object.assign({}, saved, { name: saved.name || ORIGINAL.name }), false);
  else apply({}, false);
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
      b.addEventListener("click", function () { var n = {}; n[b.parentElement.dataset.seg] = b.dataset.value; apply(n, true); });
    });
    panel.querySelector("[data-name-input]").addEventListener("input", function (e) { apply({ name: e.target.value.trim() || ORIGINAL.name }, true); });
    panel.querySelector("[data-reset]").addEventListener("click", function () {
      store(KEY, null); store(EDITS, null); edits = {};
      editables.forEach(function (el) { el.innerHTML = originalHtml[el.dataset.edit]; });
      apply(Object.assign({}, ORIGINAL), false);
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (panel) panel.hidden = true;
    setEditing(false);
  });

  // Plain-English summary of everything they changed, sent with the request.
  var LABELS = { type: { serif: "Classic", grotesk: "Bold", sans: "Clean" }, paper: { light: "Light", warm: "Warm", dark: "Dark" },
                 corners: { sharp: "Sharp", soft: "Soft", round: "Round" }, fx: { on: "On", off: "Off" } };
  function changes() {
    var out = [];
    if (look.accent.toLowerCase() !== ORIGINAL.accent.toLowerCase()) out.push("Colour: " + look.accent);
    if (look.type !== ORIGINAL.type) out.push("Font: " + LABELS.type[look.type]);
    if (look.paper !== ORIGINAL.paper) out.push("Background: " + LABELS.paper[look.paper]);
    if (look.corners !== ORIGINAL.corners) out.push("Corners: " + LABELS.corners[look.corners]);
    if (look.fx !== ORIGINAL.fx) out.push("Animation: " + LABELS.fx[look.fx]);
    if (look.name && look.name !== ORIGINAL.name) out.push("Business name: " + look.name);
    Object.keys(edits).forEach(function (k) { out.push("Text (" + k + "): " + edits[k]); });
    return out;
  }

  /* ---- the "Make it mine" sheet --------------------------------------- */
  var sheet = document.getElementById("pv-sheet");
  var form = document.getElementById("pv-form");
  if (!sheet || !form) return;
  var status = form.querySelector(".pv-status");
  var submit = form.querySelector(".pv-submit");
  var lookNote = form.querySelector(".pv-look");
  var openedAt = Date.now();
  var siteKey = (document.querySelector('meta[name="pv-ts"]') || {}).content || "";
  var tsToken = null, tsWidget = null, tsWaiters = [];
  // form.elements, not form.name etc.: those collide with built-in properties.
  function el(name) { return form.elements.namedItem(name); }

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
  function open() {
    var list = changes();
    lookNote.hidden = !list.length;
    lookNote.textContent = list.length ? "We'll include your changes: " + list.slice(0, 4).join(" · ") + (list.length > 4 ? " · and " + (list.length - 4) + " more" : "") : "";
    if (panel) panel.hidden = true;
    setEditing(false);
    if (typeof sheet.showModal === "function") sheet.showModal(); else sheet.setAttribute("open", "");
    loadTurnstile();
    setTimeout(function () { el("name").focus(); }, 60);
  }
  document.querySelectorAll("[data-open]").forEach(function (b) { b.addEventListener("click", open); });
  sheet.querySelector("[data-close]").addEventListener("click", function () { sheet.close(); });
  sheet.addEventListener("click", function (e) { if (e.target === sheet) sheet.close(); });

  function fail(text) { status.className = "pv-status err"; status.textContent = text; return false; }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!el("name").value.trim()) return fail("Please enter your name.");
    if (!/^\S+@\S+\.\S+$/.test(el("email").value.trim())) return fail("Please enter a valid email so we can reply.");
    var list = changes();
    var message = el("message").value.trim();
    if (list.length) message += (message ? "\n\n" : "") + "Their customisations:\n- " + list.join("\n- ");
    submit.disabled = true;
    status.className = "pv-status";
    status.textContent = "Sending…";
    token().then(function (t) {
      return fetch("/api/preview-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intent: "buy", slug: el("slug").value, business: el("business").value,
          name: el("name").value, email: el("email").value, phone: el("phone").value,
          domain: el("domain").value, message: message.slice(0, 2900), hp: el("hp").value, t: openedAt, token: t
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
      status.textContent = "Thanks " + el("name").value.trim().split(" ")[0] + "! We'll be in touch within one business day.";
      submit.textContent = "Sent ✓";
    }).catch(function (err) {
      fail(err.message || "Couldn't send — please try WhatsApp instead.");
      submit.disabled = false;
    }).then(function () {
      tsToken = null;
      if (window.turnstile && tsWidget && tsWidget !== "loading") window.turnstile.reset(tsWidget);
    });
  });
})();
