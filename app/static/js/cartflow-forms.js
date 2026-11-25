/* Shared form helpers for the organization/signup pages.
 * Small, dependency-free utilities used by signup, directory, and request
 * pages. Kept separate from base.html's inline theme/toast script. */

/* Debounce: delay `fn` until `wait` ms after the last call. */
function debounce(fn, wait = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

/* HTML-escape a string before injecting it into innerHTML. */
function esc(value) {
  const s = value == null ? "" : String(value);
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* GET JSON. Throws on non-2xx with the parsed error envelope attached. */
async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error("Request failed"), { status: res.status, body });
  return body;
}

/* Send JSON with any mutating verb. Throws on non-2xx with the parsed error
 * envelope attached so callers can surface {error:{message}} or a 422 field
 * list. Profiles needs PATCH (/api/users/me) and DELETE (…/follow); routing
 * them through here keeps errorMessage() working for every verb instead of
 * each page hand-rolling a fetch and its own error handling.
 *
 * A body is omitted entirely when `payload` is undefined — a DELETE with a
 * Content-Type header and no body is a request some proxies reject. */
async function sendJSON(method, url, payload) {
  const init = { method, headers: { Accept: "application/json" } };
  if (payload !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  const res = await fetch(url, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error("Request failed"), { status: res.status, body });
  return body;
}

/* POST/PATCH/DELETE JSON — thin, named wrappers over sendJSON. */
function postJSON(url, payload) {
  return sendJSON("POST", url, payload === undefined ? {} : payload);
}

function patchJSON(url, payload) {
  return sendJSON("PATCH", url, payload === undefined ? {} : payload);
}

function delJSON(url, payload) {
  return sendJSON("DELETE", url, payload);
}

/* Pull a human-readable message out of either the app error envelope
 * ({error:{message}}) or FastAPI's 422 ({detail:[{msg,loc}]}). */
function errorMessage(err, fallback = "Something went wrong. Please try again.") {
  const b = err && err.body;
  if (b && b.error && b.error.message) return b.error.message;
  if (b && Array.isArray(b.detail) && b.detail.length) {
    return b.detail.map((d) => d.msg).join(" ");
  }
  return fallback;
}

/* Nigerian states + FCT — used by the directory + request-org filters. */
const NG_STATES = [
  "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
  "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
  "FCT", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi",
  "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun",
  "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
];

/* ===================== FIELD VALIDATION =====================
 * Every field rendered by auth_macros.html ships an empty .field-error
 * node, so these only flip text + the hidden attribute — never build DOM.
 * The `invalid` class on the wrapper drives the red border via CSS. */

function setFieldError(id, message) {
  const field = document.getElementById(id + "Field");
  const error = document.getElementById(id + "Error");
  if (!field || !error) return;
  field.classList.add("invalid");
  field.classList.remove("valid");
  const slot = error.querySelector(".err-text");
  if (slot) slot.textContent = message;
  error.hidden = false;
  /* aria-invalid is what actually tells a screen reader the control is in
     an error state; the red border alone communicates nothing. */
  const input = document.getElementById(id);
  if (input) input.setAttribute("aria-invalid", "true");
}

function clearFieldError(id) {
  const field = document.getElementById(id + "Field");
  const error = document.getElementById(id + "Error");
  if (!field || !error) return;
  field.classList.remove("invalid");
  error.hidden = true;
  const input = document.getElementById(id);
  if (input) input.removeAttribute("aria-invalid");
}

function setFieldValid(id) {
  clearFieldError(id);
  const field = document.getElementById(id + "Field");
  if (field) field.classList.add("valid");
}

/* Map a 422 body's field errors onto the matching inputs. FastAPI reports
 * loc as ["body", "<field>"], while the app's own envelope uses
 * error.fields as a flat {field: message} object. Handle both. */
function applyFieldErrors(err, knownIds) {
  const body = err && err.body;
  let matched = false;

  const fields = body && body.error && body.error.fields;
  if (fields && typeof fields === "object") {
    for (const [name, message] of Object.entries(fields)) {
      if (!knownIds || knownIds.includes(name)) {
        setFieldError(name, message);
        matched = true;
      }
    }
  }

  if (body && Array.isArray(body.detail)) {
    for (const d of body.detail) {
      const name = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
      if (name && (!knownIds || knownIds.includes(name))) {
        setFieldError(name, d.msg);
        matched = true;
      }
    }
  }
  return matched;
}

/* ===================== BUTTON LOADING ===================== */

function setLoading(btn, isLoading) {
  if (!btn) return;
  btn.dataset.loading = isLoading ? "true" : "false";
  btn.disabled = isLoading;
  /* aria-busy so assistive tech announces the wait rather than reading a
     button that appears unchanged. */
  btn.setAttribute("aria-busy", isLoading ? "true" : "false");
}

/* ===================== PASSWORD REVEAL =====================
 * Toggling type between password/text. autocomplete is preserved because
 * flipping the type resets it in some browsers, which breaks password
 * managers mid-entry. */

function bindPasswordToggle(id) {
  const input = document.getElementById(id);
  const btn = document.getElementById(id + "Toggle");
  if (!input || !btn) return;

  btn.addEventListener("click", () => {
    const revealed = input.type === "text";
    input.type = revealed ? "password" : "text";
    btn.setAttribute("aria-pressed", revealed ? "false" : "true");
    btn.setAttribute("aria-label", revealed ? "Show password" : "Hide password");
    const icon = btn.querySelector(".material-symbols-outlined");
    if (icon) icon.textContent = revealed ? "visibility" : "visibility_off";
    /* Keep the caret where it was — retyping from the start is the usual
       complaint about reveal buttons. */
    const pos = input.value.length;
    input.focus();
    input.setSelectionRange(pos, pos);
  });
}

/* ===================== PASSWORD STRENGTH =====================
 * Advisory meter only. The server enforces the 8-char minimum; this exists
 * so the user finds out before submitting, not after. Scores length and
 * variety rather than pretending to compute real entropy. */

function passwordStrength(pw) {
  if (!pw) return { score: 0, label: "", pct: 0 };

  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;

  /* Long passphrases are strong even without symbol soup — don't punish
     "correct horse battery staple" for lacking a capital letter. */
  if (pw.length >= 16) score = Math.max(score, 4);

  const levels = [
    { label: "Too short", pct: 15 },
    { label: "Weak", pct: 30 },
    { label: "Fair", pct: 50 },
    { label: "Good", pct: 75 },
    { label: "Strong", pct: 100 },
  ];
  const idx = Math.min(Math.max(score - 1, 0), levels.length - 1);
  return { score, label: levels[idx].label, pct: levels[idx].pct };
}

function bindPasswordStrength(inputId, meterId) {
  const input = document.getElementById(inputId);
  const meter = document.getElementById(meterId);
  if (!input || !meter) return;

  const bar = meter.querySelector(".pw-bar-fill");
  const text = meter.querySelector(".pw-label");

  input.addEventListener("input", () => {
    const { score, label, pct } = passwordStrength(input.value);
    meter.hidden = !input.value;
    if (bar) {
      bar.style.width = pct + "%";
      bar.dataset.level = String(Math.min(score, 5));
    }
    if (text) text.textContent = label;
  });
}

/* ===================== LIVE VALIDATION =====================
 * Interactive error states for every field on the auth screens.
 *
 * The markup already ships an empty `.field-error` node per field and the
 * helpers above to fill it; what was missing was *when* to fill it. Nothing
 * happened until the server said no, so a mistyped email cost a round trip and
 * a page that scrolled to an alert at the top.
 *
 * These listeners are delegated and attribute-driven, so a new field inherits
 * the behaviour by existing: `<input class="input" id="x" required>` plus
 * `#xError` is the whole contract. A field is only checked when its error node
 * exists, which keeps search boxes and inline composers out of it.
 *
 * Only three rules are enforced here — required, email shape, minlength. Any
 * server rule that is stricter stays the server's to report; guessing at it in
 * the browser would block valid input.
 */
(function () {
  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const SELECTOR = "input.input, textarea.input, select.input";

  function messageFor(el) {
    const value = (el.value || "").trim();
    if (el.required && !value) {
      return el.dataset.requiredMessage || "This field is required.";
    }
    if (value && el.type === "email" && !EMAIL.test(value)) {
      return "Enter a valid email address.";
    }
    if (value && el.minLength > 0 && value.length < el.minLength) {
      return "Use at least " + el.minLength + " characters.";
    }
    return null;
  }

  function shake(field) {
    if (!field) return;
    /* Reflow between remove/add, or a second error on the same field is a
       class that is already there and therefore animates nothing. */
    field.classList.remove("cf-shake");
    void field.offsetWidth;
    field.classList.add("cf-shake");
  }

  function check(el, opts) {
    if (!el || el.disabled || !el.id || el.type === "hidden") return true;
    if (!document.getElementById(el.id + "Error")) return true;
    const message = messageFor(el);
    if (message) {
      setFieldError(el.id, message);
      if (opts && opts.shake) shake(el.closest(".field"));
      return false;
    }
    if ((el.value || "").trim()) setFieldValid(el.id);
    else clearFieldError(el.id);
    return true;
  }

  /* Validate when a field is left, and clear as soon as the mistake is fixed
     while typing — waiting for another blur would double the correction. */
  document.addEventListener("blur", (e) => {
    const el = e.target;
    if (el instanceof Element && el.matches(SELECTOR)) check(el, { shake: true });
  }, true);

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!(el instanceof Element) || !el.matches(SELECTOR)) return;
    const field = el.closest(".field");
    if (field && field.classList.contains("invalid")) check(el);
  }, true);

  /* Block a submit the user can already see is wrong, and put the caret on the
     first bad field instead of letting the request bounce. Capture phase so
     the page's own submit handler never runs on invalid input. */
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const fields = Array.from(form.querySelectorAll(SELECTOR));
    let firstBad = null;
    fields.forEach((el) => {
      if (!check(el, { shake: true }) && !firstBad) firstBad = el;
    });
    if (!firstBad) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    firstBad.focus({ preventScroll: true });
    firstBad.scrollIntoView({ block: "center", behavior: "smooth" });
  }, true);
})();
