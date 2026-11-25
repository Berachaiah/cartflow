/*
  "Continue with Google" — shared by /login and /signup.

  LAZY ON PURPOSE. The Firebase SDK is ~100KB of module JavaScript that a
  visitor who signs in with a password never needs. It is imported inside the
  click handler, so /login's first paint carries none of it; the wait happens
  after the tap, behind the button's own loading state, which is the one moment
  a spinner is honest.

  WHY fetch AND NOT A FORM. The endpoint answers with JSON (`next`) and a
  Set-Cookie. A normal form post would be a full navigation for what is one
  round trip, and the popup has already happened — there is nothing left to
  render server-side.

  FAILURES ARE MESSAGES, NOT SILENCE. Every branch that ends without a session
  says why: cancelled popup, blocked popup, a domain Firebase does not list,
  and the server's own refusal. An auth screen that does nothing when tapped
  reads as broken.
*/
(function () {
  var btn = document.getElementById('googleBtn');
  if (!btn || btn.disabled) return;

  var firebaseConfig = null;
  if (btn.dataset.googleFirebase) {
    try { firebaseConfig = JSON.parse(btn.dataset.googleFirebase); } catch (e) { firebaseConfig = null; }
  }

  var intent = btn.dataset.googleIntent || 'login';
  var SDK = 'https://www.gstatic.com/firebasejs/13.4.0/';
  var sdkPromise = null;

  function message(text) {
    var alertEl = document.getElementById('formAlert');
    if (alertEl) {
      alertEl.textContent = text;
      alertEl.hidden = false;
    } else if (typeof window.showToast === 'function') {
      window.showToast(text);
    }
    // Keep the button usable: Google is often the second attempt.
    if (typeof window.setLoading === 'function') window.setLoading(btn, false);
    btn.disabled = false;
  }

  function clearMessage() {
    var alertEl = document.getElementById('formAlert');
    if (alertEl) alertEl.hidden = true;
  }

  /* One import per page, however many times the button is pressed. */
  function loadSdk() {
    if (!sdkPromise) {
      sdkPromise = Promise.all([
        import(SDK + 'firebase-app.js'),
        import(SDK + 'firebase-auth.js'),
      ]);
    }
    return sdkPromise;
  }

  async function signInWithFirebase() {
    var mods = await loadSdk();
    var initializeApp = mods[0].initializeApp;
    var authMod = mods[1];

    var app = initializeApp(firebaseConfig);
    var auth = authMod.getAuth(app);
    var provider = new authMod.GoogleAuthProvider();
    // Always show the account chooser: on a shared phone the last Google
    // session is usually not the person holding it.
    provider.setCustomParameters({ prompt: 'select_account' });

    var cred = await authMod.signInWithPopup(auth, provider);
    var idToken = await cred.user.getIdToken();

    var res = await fetch('/api/auth/firebase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken }),
    });

    var data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error body */ }

    if (!res.ok) {
      var detail = data && data.error && data.error.message;
      throw new Error(detail || 'We could not complete Google sign-in. Please try again.');
    }
    // The session cookie is already set by the response above.
    window.location.assign(data.next || '/discover');
  }

  btn.addEventListener('click', function () {
    clearMessage();
    if (typeof window.setLoading === 'function') window.setLoading(btn, true);

    if (firebaseConfig) {
      signInWithFirebase().catch(function (err) {
        var code = (err && err.code) || '';
        if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
          message('Google sign-in was cancelled.');
        } else if (code === 'auth/popup-blocked') {
          message('Your browser blocked the sign-in window. Allow pop-ups for this site and try again.');
        } else if (code === 'auth/unauthorized-domain') {
          message('This address is not authorised for Google sign-in yet. Add it under Firebase → Authentication → Settings → Authorized domains.');
        } else if (code === 'auth/operation-not-allowed') {
          message('Google sign-in is not enabled for this Firebase project yet.');
        } else {
          message(err && err.message ? err.message : 'We could not complete Google sign-in. Please try again.');
        }
      });
      return;
    }

    if (btn.dataset.googleOauth === '1') {
      // No Firebase: fall back to the server-side redirect flow, which needs no
      // JavaScript beyond this navigation.
      window.location.assign('/api/auth/google/login?intent=' + encodeURIComponent(intent));
      return;
    }

    message('Google sign-in is not configured on this install yet.');
  });
})();
