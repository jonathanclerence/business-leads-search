/* Preview websites: the "Make it mine" / "Request changes" sheet and the
   demo enquiry form. Posts to /api/preview-request, which emails DuNous. */
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
            domain: el("domain").value, message: msg, hp: el("hp").value, t: openedAt, token: t
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
