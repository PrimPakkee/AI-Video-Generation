// v0.6.8 — Auth page bootstrap (login / register / forced-change-password).
//
// Communicates with /api/auth/* and uses session cookies (HttpOnly,
// SameSite=Lax) — no localStorage / Authorization headers. On successful
// login the page redirects to "/" which then renders index.html.

(() => {
  const heroEl = document.getElementById('authHero');
  const taglineEl = document.getElementById('authTagline');
  const tabs = document.querySelectorAll('.auth-tab');
  const form = document.getElementById('authForm');
  const emailEl = document.getElementById('authEmail');
  const passEl = document.getElementById('authPassword');
  const submitBtn = document.getElementById('authSubmit');
  const errorEl = document.getElementById('authError');
  const infoEl = document.getElementById('authInfo');

  const modalBackdrop = document.getElementById('authModalBackdrop');
  const modalTitle = document.getElementById('authModalTitle');
  const modalBody = document.getElementById('authModalBody');
  const modalClose = document.getElementById('authModalClose');

  const changeHero = document.getElementById('changeHero');
  const changeForm = document.getElementById('changeForm');
  const changeOld = document.getElementById('changeOld');
  const changeNew = document.getElementById('changeNew');
  const changeNew2 = document.getElementById('changeNew2');
  const changeError = document.getElementById('changeError');
  const changeSubmit = document.getElementById('changeSubmit');

  let mode = 'login';

  function setMode(next) {
    mode = next;
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === mode;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    if (mode === 'login') {
      taglineEl.textContent = 'Sign in to continue.';
      submitBtn.textContent = 'Sign in';
      passEl.autocomplete = 'current-password';
    } else {
      taglineEl.textContent = 'New accounts need approval before signing in.';
      submitBtn.textContent = 'Create account';
      passEl.autocomplete = 'new-password';
    }
    hide(errorEl);
    hide(infoEl);
  }

  function show(el, text) {
    el.textContent = text;
    el.classList.remove('hidden');
  }
  function hide(el) {
    el.classList.add('hidden');
  }

  function showModal(title, body) {
    modalTitle.textContent = title;
    modalBody.textContent = body;
    modalBackdrop.classList.remove('hidden');
  }
  function hideModal() {
    modalBackdrop.classList.add('hidden');
  }
  if (modalClose) modalClose.addEventListener('click', hideModal);
  if (modalBackdrop) modalBackdrop.addEventListener('click', (e) => {
    if (e.target === modalBackdrop) hideModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modalBackdrop.classList.contains('hidden')) hideModal();
  });

  function describeError(detail) {
    const map = {
      invalid_credentials: 'Email or password is incorrect.',
      invalid_email: 'Please enter a valid email address.',
      invalid_password: 'Password must be at least 8 characters.',
      email_already_registered: 'An account with this email already exists.',
      account_pending_approval: 'Your account is pending approval. Ask the founder to approve it before signing in.',
      account_rejected: 'This account has been rejected.',
      account_inactive: 'This account is inactive.',
      old_password_mismatch: 'Current password is incorrect.',
      new_password_same_as_old: 'New password must differ from the current one.',
      not_logged_in: 'You are signed out.',
      cannot_modify_self: 'You cannot modify your own account here.',
      user_not_found: 'User not found.',
    };
    return map[detail] || detail || 'Something went wrong. Please try again.';
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body || {}),
    });
    let payload = null;
    try { payload = await res.json(); } catch (_) { /* ignore */ }
    return { ok: res.ok, status: res.status, payload };
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => setMode(tab.dataset.tab)));

  // Ensure tagline + submit label match the initial tab on first paint.
  setMode('login');

  // v0.6.8.3 — wrap every password input with an eye-toggle button so
  // users can verify what they typed (the founder default password has
  // similar-looking chars like 1/l/I — easy to mistype).
  const EYE_ON_SVG = '<svg class="eye-on" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF_SVG = '<svg class="eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-6.5 0-10-7-10-7a17.84 17.84 0 0 1 4.06-4.94"/><path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c6.5 0 10 7 10 7a17.83 17.83 0 0 1-3.17 4.19"/><path d="M14.12 14.12A3 3 0 1 1 9.88 9.88"/><line x1="2" y1="2" x2="22" y2="22"/></svg>';

  function attachEyeToggle(input) {
    if (!input || input.dataset.eyeWired === '1') return;
    input.dataset.eyeWired = '1';

    const wrap = document.createElement('div');
    wrap.className = 'auth-password-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'auth-eye-btn';
    btn.setAttribute('aria-label', 'Show password');
    btn.setAttribute('aria-pressed', 'false');
    btn.dataset.revealed = 'false';
    btn.innerHTML = EYE_ON_SVG + EYE_OFF_SVG;
    btn.addEventListener('click', () => {
      const revealed = btn.dataset.revealed === 'true';
      const next = !revealed;
      input.type = next ? 'text' : 'password';
      btn.dataset.revealed = next ? 'true' : 'false';
      btn.setAttribute('aria-pressed', next ? 'true' : 'false');
      btn.setAttribute('aria-label', next ? 'Hide password' : 'Show password');
    });
    wrap.appendChild(btn);
  }

  document.querySelectorAll('.auth-form input[type="password"]').forEach(attachEyeToggle);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hide(errorEl);
    hide(infoEl);
    submitBtn.disabled = true;
    const email = emailEl.value.trim();
    const password = passEl.value;

    try {
      if (mode === 'login') {
        const r = await postJson('/api/auth/login', { email, password });
        if (!r.ok) {
          const detail = r.payload && r.payload.detail;
          if (detail === 'account_pending_approval') {
            showModal(
              'Pending approval',
              'Your account is waiting on founder approval. You will be able to sign in once it is approved.'
            );
            return;
          }
          show(errorEl, describeError(detail));
          return;
        }
        const user = r.payload && r.payload.user;
        if (user && user.must_change_password) {
          heroEl.classList.add('hidden');
          changeHero.classList.remove('hidden');
          return;
        }
        window.location.href = '/';
      } else {
        const r = await postJson('/api/auth/register', { email, password });
        if (!r.ok) {
          show(errorEl, describeError(r.payload && r.payload.detail));
          return;
        }
        showModal(
          'Account created',
          'Your account has been created. The founder needs to approve it before you can sign in.'
        );
        form.reset();
        setMode('login');
      }
    } catch (err) {
      show(errorEl, 'Network error. Please try again.');
    } finally {
      submitBtn.disabled = false;
    }
  });

  changeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    hide(changeError);
    if (changeNew.value !== changeNew2.value) {
      show(changeError, 'New passwords do not match.');
      return;
    }
    if (changeNew.value === changeOld.value) {
      show(changeError, 'New password must differ from the current one.');
      return;
    }
    changeSubmit.disabled = true;
    try {
      const r = await postJson('/api/auth/change-password', {
        old_password: changeOld.value,
        new_password: changeNew.value,
      });
      if (!r.ok) {
        show(changeError, describeError(r.payload && r.payload.detail));
        return;
      }
      window.location.href = '/';
    } catch (err) {
      show(changeError, 'Network error. Please try again.');
    } finally {
      changeSubmit.disabled = false;
    }
  });

  // If somebody navigates here while already logged in, send them home.
  fetch('/api/auth/me', { credentials: 'same-origin' })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (data && data.user && !data.user.must_change_password) {
        window.location.href = '/';
      } else if (data && data.user && data.user.must_change_password) {
        heroEl.classList.add('hidden');
        changeHero.classList.remove('hidden');
      }
    })
    .catch(() => {});
})();
