// v0.6.8 — App bootstrap.
//
// Runs BEFORE main.js. Three jobs:
//   1) Confirm we have an active session (session cookie). If not, send
//      the user to /auth.html.
//   2) Inject a user chip (email + logout) into the top header so the
//      operator can see who is signed in and sign out without DevTools.
//   3) When the user is an admin, mount a small "Admin" launcher in the
//      header that opens a modal listing pending users with approve /
//      reject buttons.
//
// Pre-existing main.js is untouched. This file only adds DOM and patches
// fetch() to redirect on 401.

(function () {
  const STATIC_PUBLIC_PATHS = new Set(['/auth.html']);

  // Patch fetch so any 401 from a same-origin /api/* call (other than the
  // ones the auth flow itself uses) sends us back to /auth.html. main.js
  // never has to know auth exists.
  const originalFetch = window.fetch.bind(window);
  window.fetch = async function patchedFetch(input, init) {
    const res = await originalFetch(input, init);
    try {
      if (res.status === 401) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (!url.includes('/api/auth/')) {
          window.location.href = '/auth.html';
        }
      }
    } catch (_) {
      /* ignore */
    }
    return res;
  };

  function injectStyles() {
    if (document.getElementById('app-bootstrap-styles')) return;
    const style = document.createElement('style');
    style.id = 'app-bootstrap-styles';
    style.textContent = `
      /* v0.6.8.2 — neutral, theme-aware auth chip. Email truncates with
         ellipsis so the trailing badge / buttons never get pushed off
         screen. Light + dark mode both supported via prefers-color-scheme
         AND the app's existing [data-theme="dark"] / .dark hooks if any
         are present. */
      .auth-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 5px 10px 5px 12px;
        border-radius: 999px;
        background: rgba(0, 0, 0, 0.05);
        border: 1px solid rgba(0, 0, 0, 0.08);
        font-size: 12px;
        color: #1d1d1f;
        margin-left: 8px;
        max-width: 360px;
        min-width: 0;
        overflow: hidden;
        flex-wrap: nowrap;
      }
      .auth-chip .chip-email {
        font-weight: 500;
        min-width: 0;
        max-width: 180px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 0 1 auto;
      }
      .auth-chip .chip-divider {
        opacity: 0.4;
        flex-shrink: 0;
      }
      .auth-chip button {
        border: 0;
        background: transparent;
        color: #1d1d1f;
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        padding: 0;
        flex-shrink: 0;
      }
      .auth-chip button:hover { text-decoration: underline; }
      .auth-chip .admin-badge {
        background: #1d1d1f;
        color: #ffffff;
        border-radius: 5px;
        padding: 2px 7px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        flex-shrink: 0;
        line-height: 1.4;
      }
      @media (prefers-color-scheme: dark) {
        .auth-chip {
          background: rgba(255, 255, 255, 0.08);
          border-color: rgba(255, 255, 255, 0.12);
          color: #f5f5f7;
        }
        .auth-chip button { color: #f5f5f7; }
        .auth-chip .admin-badge {
          background: #f5f5f7;
          color: #1d1d1f;
        }
      }
      /* Pick up the app's manual theme toggle. main.js writes
         "dark-theme" onto <html> when the user clicks the moon/sun
         button; prefers-color-scheme alone misses that. */
      html.dark-theme .auth-chip {
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(255, 255, 255, 0.12);
        color: #f5f5f7;
      }
      html.dark-theme .auth-chip button { color: #f5f5f7; }
      html.dark-theme .auth-chip .admin-badge {
        background: #f5f5f7;
        color: #1d1d1f;
      }

      /* Admin modal — explicit light + dark colours so it doesn't depend
         on which CSS variables happen to be defined on the host page. */
      .admin-modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
      }
      .admin-modal {
        width: 520px;
        max-width: calc(100vw - 32px);
        max-height: calc(100vh - 80px);
        overflow: auto;
        background: #ffffff;
        color: #1d1d1f;
        border-radius: 14px;
        border: 1px solid rgba(0, 0, 0, 0.08);
        box-shadow: 0 30px 80px rgba(0, 0, 0, 0.18);
        padding: 22px 22px 18px;
      }
      .admin-modal h2 {
        margin: 0 0 6px;
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: inherit;
      }
      .admin-modal p.subtitle {
        margin: 0 0 16px;
        font-size: 13px;
        color: #6e6e73;
      }
      .admin-user-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 0;
        border-top: 1px solid rgba(0, 0, 0, 0.08);
      }
      .admin-user-row:first-of-type { border-top: 0; }
      .admin-user-email { flex: 1; font-size: 13px; color: inherit; }
      .admin-user-status {
        font-size: 12px;
        font-weight: 500;
        letter-spacing: -0.005em;
        color: #1d1d1f;
        background: rgba(0, 0, 0, 0.06);
        border-radius: 999px;
        padding: 3px 10px;
        text-transform: none;
      }
      .admin-user-status.status-active   { background: rgba(48, 209, 88, 0.18); color: #1f6e1f; }
      .admin-user-status.status-pending  { background: rgba(255, 159, 10, 0.18); color: #8b5a00; }
      .admin-user-status.status-rejected { background: rgba(255, 59, 48, 0.16); color: #b22a22; }
      .admin-action {
        height: 28px;
        padding: 0 12px;
        border-radius: 8px;
        border: 1px solid rgba(0, 0, 0, 0.14);
        background: #ffffff;
        color: #1d1d1f;
        font-size: 12px;
        cursor: pointer;
        font-family: inherit;
      }
      .admin-action.primary { background: #1d1d1f; color: #ffffff; border-color: #1d1d1f; }
      .admin-action.primary:hover { background: #2d2d2f; }
      .admin-action.danger  { color: #c83329; border-color: rgba(200, 51, 41, 0.4); }
      .admin-action:disabled { opacity: 0.5; cursor: not-allowed; }
      .admin-modal-close {
        margin-top: 12px;
        text-align: right;
      }
      .admin-empty {
        padding: 20px 0;
        text-align: center;
        font-size: 13px;
        color: #6e6e73;
      }

      /* Dark mode — both system preference and manual main.js toggle. */
      html.dark-theme .admin-modal {
        background: #1c1c1e;
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.1);
        box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
      }
      html.dark-theme .admin-modal p.subtitle,
      html.dark-theme .admin-empty,
      html.dark-theme .admin-user-status {
        color: #98989d;
      }
      html.dark-theme .admin-user-row {
        border-top-color: rgba(255, 255, 255, 0.08);
      }
      html.dark-theme .admin-user-status {
        background: rgba(255, 255, 255, 0.1);
        color: #f5f5f7;
      }
      html.dark-theme .admin-user-status.status-active   { background: rgba(48, 209, 88, 0.22); color: #6ee07b; }
      html.dark-theme .admin-user-status.status-pending  { background: rgba(255, 159, 10, 0.22); color: #ffb84d; }
      html.dark-theme .admin-user-status.status-rejected { background: rgba(255, 107, 94, 0.22); color: #ff8a7a; }
      html.dark-theme .admin-action {
        background: #2c2c2e;
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.14);
      }
      html.dark-theme .admin-action:hover {
        background: #3a3a3c;
      }
      html.dark-theme .admin-action.primary {
        background: #f5f5f7;
        color: #1d1d1f;
        border-color: #f5f5f7;
      }
      html.dark-theme .admin-action.primary:hover {
        background: #e5e5ea;
      }
      html.dark-theme .admin-action.danger {
        color: #ff6b5e;
        border-color: rgba(255, 107, 94, 0.45);
        background: transparent;
      }
      @media (prefers-color-scheme: dark) {
        html:not(.light-theme) .admin-modal {
          background: #1c1c1e;
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.1);
          box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
        }
        html:not(.light-theme) .admin-modal p.subtitle,
        html:not(.light-theme) .admin-empty,
        html:not(.light-theme) .admin-user-status {
          color: #98989d;
        }
        html:not(.light-theme) .admin-user-row {
          border-top-color: rgba(255, 255, 255, 0.08);
        }
        html:not(.light-theme) .admin-user-status {
          background: rgba(255, 255, 255, 0.08);
        }
        html:not(.light-theme) .admin-action {
          background: #2c2c2e;
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.14);
        }
        html:not(.light-theme) .admin-action.primary {
          background: #f5f5f7;
          color: #1d1d1f;
          border-color: #f5f5f7;
        }
        html:not(.light-theme) .admin-action.danger {
          color: #ff6b5e;
          border-color: rgba(255, 107, 94, 0.45);
          background: transparent;
        }
      }

      .account-form-group { margin-top: 18px; }
      .account-form {
        display: flex;
        flex-direction: column;
        gap: 8px;
        max-width: 360px;
        margin-top: 6px;
      }
      .account-form input {
        height: 36px;
        border-radius: 8px;
        border: 1px solid var(--border-default, rgba(0,0,0,0.12));
        padding: 0 12px;
        font-size: 13px;
        background: var(--bg-surface, #fff);
        color: var(--text-primary, #1d1d1f);
        outline: none;
      }
      .account-form input:focus {
        border-color: #1d1d1f;
        box-shadow: 0 0 0 3px rgba(29, 29, 31, 0.1);
      }
      .account-submit {
        align-self: flex-start;
        height: 34px;
        padding: 0 16px;
        border-radius: 8px;
        border: 0;
        background: #1d1d1f;
        color: #fff;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        margin-top: 4px;
      }
      .account-submit:hover { background: #2d2d2f; }
      .account-submit:disabled { opacity: 0.55; cursor: not-allowed; }
      .account-msg {
        font-size: 12px;
        margin: 4px 0 0;
        padding: 6px 10px;
        border-radius: 6px;
      }
      .account-msg.ok { background: rgba(34, 139, 34, 0.08); color: #1f6e1f; border: 1px solid rgba(34, 139, 34, 0.2); }
      .account-msg.err { background: rgba(255, 59, 48, 0.08); color: #b22a22; border: 1px solid rgba(255, 59, 48, 0.18); }
    `;
    document.head.appendChild(style);
  }

  function buildChip(user) {
    const wrap = document.createElement('div');
    wrap.className = 'auth-chip';
    const email = document.createElement('span');
    email.className = 'chip-email';
    email.textContent = user.email;
    wrap.appendChild(email);
    if (user.is_admin) {
      const adminBadge = document.createElement('span');
      adminBadge.className = 'admin-badge';
      adminBadge.textContent = 'Admin';
      wrap.appendChild(adminBadge);
      const adminBtn = document.createElement('button');
      adminBtn.type = 'button';
      adminBtn.textContent = 'Manage';
      adminBtn.addEventListener('click', () => openAdminModal());
      wrap.appendChild(adminBtn);
    }
    const divider = document.createElement('span');
    divider.className = 'chip-divider';
    divider.textContent = '·';
    wrap.appendChild(divider);
    const out = document.createElement('button');
    out.type = 'button';
    out.textContent = 'Sign out';
    out.addEventListener('click', async () => {
      try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); } catch (_) {}
      window.location.href = '/auth.html';
    });
    wrap.appendChild(out);
    return wrap;
  }

  function mountChip(user) {
    const headerActions = document.querySelector('.top-header .header-actions')
      || document.querySelector('.top-header');
    if (!headerActions) return;
    const chip = buildChip(user);
    headerActions.appendChild(chip);
  }

  async function openAdminModal() {
    injectStyles();
    let users = [];
    try {
      const r = await fetch('/api/admin/users', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('admin_users_failed');
      const data = await r.json();
      users = (data && data.users) || [];
    } catch (err) {
      alert('Failed to load users.');
      return;
    }

    const backdrop = document.createElement('div');
    backdrop.className = 'admin-modal-backdrop';
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) backdrop.remove();
    });

    const modal = document.createElement('div');
    modal.className = 'admin-modal';
    modal.innerHTML = `
      <h2>User management</h2>
      <p class="subtitle">Approve pending registrations or reject them. Founder accounts cannot be modified here.</p>
      <div id="admin-user-list"></div>
      <div class="admin-modal-close">
        <button class="admin-action" id="admin-modal-close-btn">Close</button>
      </div>
    `;
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    modal.querySelector('#admin-modal-close-btn').addEventListener('click', () => backdrop.remove());

    const listEl = modal.querySelector('#admin-user-list');
    if (!users.length) {
      listEl.innerHTML = '<div class="admin-empty">No users yet.</div>';
      return;
    }

    function renderRow(u) {
      const row = document.createElement('div');
      row.className = 'admin-user-row';
      const email = document.createElement('div');
      email.className = 'admin-user-email';
      email.textContent = u.email;
      const status = document.createElement('span');
      const rawStatus = (u.status || '').toLowerCase();
      const statusLabel = {
        active: 'Active',
        pending: 'Pending',
        rejected: 'Rejected',
      }[rawStatus] || (rawStatus ? rawStatus.charAt(0).toUpperCase() + rawStatus.slice(1) : 'Unknown');
      status.className = `admin-user-status status-${rawStatus || 'unknown'}`;
      status.textContent = statusLabel;
      row.appendChild(email);
      row.appendChild(status);

      if (!u.is_admin) {
        if (u.status === 'pending' || u.status === 'rejected') {
          const approveBtn = document.createElement('button');
          approveBtn.className = 'admin-action primary';
          approveBtn.textContent = 'Approve';
          approveBtn.addEventListener('click', async () => {
            approveBtn.disabled = true;
            try {
              const r = await fetch(`/api/admin/users/${u.id}/approve`, {
                method: 'POST', credentials: 'same-origin',
              });
              if (!r.ok) throw new Error();
              backdrop.remove();
              openAdminModal();
            } catch (_) { alert('Approve failed'); approveBtn.disabled = false; }
          });
          row.appendChild(approveBtn);
        }
        if (u.status !== 'rejected') {
          const rejectBtn = document.createElement('button');
          rejectBtn.className = 'admin-action danger';
          rejectBtn.textContent = u.status === 'active' ? 'Revoke' : 'Reject';
          rejectBtn.addEventListener('click', async () => {
            if (!confirm(`Reject ${u.email}? They will no longer be able to sign in.`)) return;
            rejectBtn.disabled = true;
            try {
              const r = await fetch(`/api/admin/users/${u.id}/reject`, {
                method: 'POST', credentials: 'same-origin',
              });
              if (!r.ok) throw new Error();
              backdrop.remove();
              openAdminModal();
            } catch (_) { alert('Reject failed'); rejectBtn.disabled = false; }
          });
          row.appendChild(rejectBtn);
        }
      }
      return row;
    }

    users.forEach((u) => listEl.appendChild(renderRow(u)));
  }

  function describeAuthError(detail) {
    const map = {
      current_password_mismatch: 'Current password is incorrect.',
      old_password_mismatch: 'Current password is incorrect.',
      new_email_same_as_old: 'New email is the same as the current one.',
      new_password_same_as_old: 'New password must differ from the current one.',
      email_already_registered: 'An account with this email already exists.',
      invalid_email: 'Please enter a valid email address.',
      invalid_password: 'Password must be at least 8 characters.',
    };
    return map[detail] || detail || 'Something went wrong. Please try again.';
  }

  function setMsg(el, kind, text) {
    el.textContent = text;
    el.className = `account-msg ${kind}`;
    el.classList.remove('hidden');
  }

  function mountAccountPanel(user) {
    const emailDisplay = document.getElementById('settings-account-email');
    const roleDisplay = document.getElementById('settings-account-role');
    if (emailDisplay) emailDisplay.textContent = user.email;
    if (roleDisplay) roleDisplay.textContent = user.is_admin ? 'Founder / Admin' : 'Member';

    const emailForm = document.getElementById('account-email-form');
    const passwordForm = document.getElementById('account-password-form');
    const emailMsg = document.getElementById('account-email-msg');
    const passwordMsg = document.getElementById('account-password-msg');

    if (emailForm && !emailForm.dataset.wired) {
      emailForm.dataset.wired = '1';
      emailForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        emailMsg.classList.add('hidden');
        const newEmail = document.getElementById('account-new-email').value.trim();
        const pw = document.getElementById('account-email-password').value;
        const btn = emailForm.querySelector('button');
        btn.disabled = true;
        try {
          const res = await fetch('/api/auth/change-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ new_email: newEmail, current_password: pw }),
          });
          const data = await res.json().catch(() => null);
          if (!res.ok) {
            setMsg(emailMsg, 'err', describeAuthError(data && data.detail));
            return;
          }
          setMsg(emailMsg, 'ok', 'Email updated.');
          if (data && data.user) {
            window.__authUser = data.user;
            if (emailDisplay) emailDisplay.textContent = data.user.email;
            const chipEmail = document.querySelector('.auth-chip .chip-email');
            if (chipEmail) chipEmail.textContent = data.user.email;
          }
          emailForm.reset();
        } catch (_) {
          setMsg(emailMsg, 'err', 'Network error. Please try again.');
        } finally {
          btn.disabled = false;
        }
      });
    }

    if (passwordForm && !passwordForm.dataset.wired) {
      passwordForm.dataset.wired = '1';
      passwordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        passwordMsg.classList.add('hidden');
        const oldPw = document.getElementById('account-old-password').value;
        const newPw = document.getElementById('account-new-password').value;
        const newPw2 = document.getElementById('account-new-password-2').value;
        if (newPw !== newPw2) {
          setMsg(passwordMsg, 'err', 'New passwords do not match.');
          return;
        }
        if (newPw === oldPw) {
          setMsg(passwordMsg, 'err', 'New password must differ from the current one.');
          return;
        }
        const btn = passwordForm.querySelector('button');
        btn.disabled = true;
        try {
          const res = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
          });
          const data = await res.json().catch(() => null);
          if (!res.ok) {
            setMsg(passwordMsg, 'err', describeAuthError(data && data.detail));
            return;
          }
          setMsg(passwordMsg, 'ok', 'Password updated.');
          passwordForm.reset();
        } catch (_) {
          setMsg(passwordMsg, 'err', 'Network error. Please try again.');
        } finally {
          btn.disabled = false;
        }
      });
    }
  }

  function init() {
    injectStyles();
    fetch('/api/auth/me', { credentials: 'same-origin' })
      .then((r) => {
        if (!r.ok) {
          window.location.href = '/auth.html';
          return null;
        }
        return r.json();
      })
      .then((data) => {
        if (!data || !data.user) return;
        const user = data.user;
        if (user.must_change_password) {
          window.location.href = '/auth.html';
          return;
        }
        window.__authUser = user;
        mountChip(user);
        mountAccountPanel(user);
      })
      .catch(() => { window.location.href = '/auth.html'; });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
