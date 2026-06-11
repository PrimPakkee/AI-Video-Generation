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
        border-radius: 6px;
        padding: 2px 9px;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: -0.005em;
        flex-shrink: 0;
        line-height: 1.5;
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

      /* v0.6.8.5 — Inbox icon button (sits left of the theme toggle).
         Mirrors .theme-toggle visual weight so the header stays balanced. */
      .inbox-toggle {
        position: relative;
        width: 34px;
        height: 34px;
        border-radius: 50%;
        border: 1px solid rgba(0, 0, 0, 0.1);
        background: transparent;
        color: #1d1d1f;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-right: 8px;
        padding: 0;
        transition: background 0.15s ease, border-color 0.15s ease;
      }
      .inbox-toggle:hover {
        background: rgba(0, 0, 0, 0.04);
      }
      .inbox-toggle svg { width: 18px; height: 18px; }
      .inbox-toggle .inbox-dot {
        position: absolute;
        top: 4px;
        right: 4px;
        min-width: 16px;
        height: 16px;
        padding: 0 4px;
        border-radius: 999px;
        background: #ff3b30;
        color: #ffffff;
        font-size: 10px;
        font-weight: 600;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid #ffffff;
        line-height: 1;
      }
      .inbox-toggle .inbox-dot.hidden { display: none; }
      @media (prefers-color-scheme: dark) {
        .inbox-toggle {
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.18);
        }
        .inbox-toggle:hover { background: rgba(255, 255, 255, 0.08); }
        .inbox-toggle .inbox-dot { border-color: #1c1c1e; }
      }
      html.dark-theme .inbox-toggle {
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.18);
      }
      html.dark-theme .inbox-toggle:hover { background: rgba(255, 255, 255, 0.08); }
      html.dark-theme .inbox-toggle .inbox-dot { border-color: #1c1c1e; }

      /* v0.6.8.5 — Summary grid (Manage modal becomes a stat dashboard;
         the actual approval flow moves to the Inbox icon). */
      .admin-summary-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin: 6px 0 16px;
      }
      .admin-summary-cell {
        background: rgba(0, 0, 0, 0.04);
        border-radius: 10px;
        padding: 12px 8px;
        text-align: center;
      }
      .admin-summary-cell .num {
        font-size: 22px;
        font-weight: 600;
        color: inherit;
        letter-spacing: -0.01em;
        line-height: 1.1;
      }
      .admin-summary-cell .lbl {
        font-size: 11px;
        font-weight: 500;
        color: #6e6e73;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-top: 4px;
      }
      .admin-modal-footer {
        margin-top: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      html.dark-theme .admin-summary-cell { background: rgba(255, 255, 255, 0.06); }
      html.dark-theme .admin-summary-cell .lbl { color: #98989d; }
      @media (prefers-color-scheme: dark) {
        html:not(.light-theme) .admin-summary-cell { background: rgba(255, 255, 255, 0.06); }
        html:not(.light-theme) .admin-summary-cell .lbl { color: #98989d; }
      }

      /* v0.6.8.5 — All-users large modal (Settings-sized: 920x680). */
      .users-modal {
        width: 920px;
        height: 680px;
        max-width: 92vw;
        max-height: 88vh;
        background: #ffffff;
        color: #1d1d1f;
        border-radius: 16px;
        border: 1px solid rgba(0, 0, 0, 0.08);
        box-shadow: 0 30px 80px rgba(0, 0, 0, 0.18);
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .users-modal-header {
        padding: 22px 26px 14px;
        border-bottom: 1px solid rgba(0, 0, 0, 0.08);
      }
      .users-modal-header h2 {
        margin: 0 0 4px;
        font-size: 19px;
        font-weight: 600;
        letter-spacing: -0.01em;
      }
      .users-modal-header p {
        margin: 0;
        font-size: 13px;
        color: #6e6e73;
      }
      .users-table {
        flex: 1;
        overflow-y: auto;
        padding: 0 26px;
      }
      .users-table-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 140px 130px;
        align-items: center;
        gap: 16px;
        padding: 14px 0;
        border-bottom: 1px solid rgba(0, 0, 0, 0.06);
        font-size: 13px;
      }
      .users-table-row.head {
        position: sticky;
        top: 0;
        background: #ffffff;
        font-size: 13px;
        font-weight: 500;
        color: #6e6e73;
        letter-spacing: -0.005em;
        padding: 14px 0;
        z-index: 1;
      }
      .users-table-email {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .users-role-pill {
        display: inline-block;
        font-size: 12px;
        font-weight: 500;
        letter-spacing: -0.005em;
        padding: 4px 12px;
        border-radius: 999px;
        background: rgba(0, 0, 0, 0.06);
        color: #1d1d1f;
      }
      .users-role-pill.is-admin { background: #1d1d1f; color: #ffffff; }
      /* Revoke-mode row delete button (circular ⊗). Only visible while
         the modal is in revoke mode; founders never get one. */
      .users-revoke-cell {
        display: flex;
        justify-content: flex-end;
        align-items: center;
      }
      .users-revoke-btn {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        border: 1px solid rgba(255, 59, 48, 0.45);
        background: transparent;
        color: #ff3b30;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        transition: background 0.15s ease, transform 0.05s ease;
      }
      .users-revoke-btn:hover { background: rgba(255, 59, 48, 0.12); }
      .users-revoke-btn:active { transform: scale(0.94); }
      .users-revoke-btn svg { width: 14px; height: 14px; }
      /* Confirmation sub-modal nests above the users modal at z-index 10000. */
      .confirm-modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10001;
      }
      .confirm-modal {
        width: 380px;
        max-width: calc(100vw - 32px);
        background: #ffffff;
        color: #1d1d1f;
        border-radius: 14px;
        border: 1px solid rgba(0, 0, 0, 0.08);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
        padding: 24px 24px 18px;
        text-align: center;
      }
      .confirm-modal h3 {
        margin: 0 0 8px;
        font-size: 17px;
        font-weight: 600;
        letter-spacing: -0.01em;
      }
      .confirm-modal p {
        margin: 0 0 18px;
        font-size: 13px;
        color: #6e6e73;
        line-height: 1.5;
        word-break: break-all;
      }
      .confirm-modal-actions {
        display: flex;
        gap: 10px;
        justify-content: center;
      }
      .confirm-modal-actions button {
        flex: 1;
        height: 38px;
        border-radius: 9px;
        border: 1px solid rgba(0, 0, 0, 0.14);
        background: #ffffff;
        color: #1d1d1f;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        font-family: inherit;
        transition: background 0.15s ease;
      }
      .confirm-modal-actions button:hover { background: rgba(0, 0, 0, 0.04); }
      .confirm-modal-actions button.danger {
        background: #ff3b30;
        color: #ffffff;
        border-color: #ff3b30;
      }
      .confirm-modal-actions button.danger:hover { background: #e0322a; }
      html.dark-theme .confirm-modal {
        background: #1c1c1e;
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.1);
      }
      html.dark-theme .confirm-modal p { color: #98989d; }
      html.dark-theme .confirm-modal-actions button {
        background: #2c2c2e;
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.14);
      }
      html.dark-theme .confirm-modal-actions button:hover { background: #3a3a3c; }
      html.dark-theme .confirm-modal-actions button.danger {
        background: #ff453a;
        color: #ffffff;
        border-color: #ff453a;
      }
      html.dark-theme .confirm-modal-actions button.danger:hover { background: #ff5a4f; }
      @media (prefers-color-scheme: dark) {
        html:not(.light-theme) .confirm-modal {
          background: #1c1c1e;
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.1);
        }
        html:not(.light-theme) .confirm-modal p { color: #98989d; }
        html:not(.light-theme) .confirm-modal-actions button {
          background: #2c2c2e;
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.14);
        }
        html:not(.light-theme) .confirm-modal-actions button.danger {
          background: #ff453a;
          color: #ffffff;
          border-color: #ff453a;
        }
      }
      .users-modal-footer {
        padding: 14px 26px;
        border-top: 1px solid rgba(0, 0, 0, 0.08);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
      }
      .users-empty {
        padding: 80px 0;
        text-align: center;
        font-size: 14px;
        color: #6e6e73;
      }
      html.dark-theme .users-modal {
        background: #1c1c1e;
        color: #f5f5f7;
        border-color: rgba(255, 255, 255, 0.1);
        box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
      }
      html.dark-theme .users-modal-header,
      html.dark-theme .users-modal-footer {
        border-color: rgba(255, 255, 255, 0.08);
      }
      html.dark-theme .users-modal-header p,
      html.dark-theme .users-empty,
      html.dark-theme .users-table-row.head {
        color: #98989d;
      }
      html.dark-theme .users-table-row.head { background: #1c1c1e; }
      html.dark-theme .users-table-row { border-bottom-color: rgba(255, 255, 255, 0.06); }
      html.dark-theme .users-role-pill {
        background: rgba(255, 255, 255, 0.1);
        color: #f5f5f7;
      }
      html.dark-theme .users-role-pill.is-admin {
        background: #f5f5f7;
        color: #1d1d1f;
      }
      @media (prefers-color-scheme: dark) {
        html:not(.light-theme) .users-modal {
          background: #1c1c1e;
          color: #f5f5f7;
          border-color: rgba(255, 255, 255, 0.1);
          box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
        }
        html:not(.light-theme) .users-modal-header,
        html:not(.light-theme) .users-modal-footer {
          border-color: rgba(255, 255, 255, 0.08);
        }
        html:not(.light-theme) .users-modal-header p,
        html:not(.light-theme) .users-empty,
        html:not(.light-theme) .users-table-row.head {
          color: #98989d;
        }
        html:not(.light-theme) .users-table-row.head { background: #1c1c1e; }
        html:not(.light-theme) .users-table-row { border-bottom-color: rgba(255, 255, 255, 0.06); }
        html:not(.light-theme) .users-role-pill {
          background: rgba(255, 255, 255, 0.1);
          color: #f5f5f7;
        }
        html:not(.light-theme) .users-role-pill.is-admin {
          background: #f5f5f7;
          color: #1d1d1f;
        }
      }

      /* v0.6.8.5 — Inbox modal: same chrome as Admin modal but its own
         empty state + row layout for pending requests. */
      .inbox-empty-illu {
        padding: 30px 0 24px;
        text-align: center;
        color: #98989d;
      }
      .inbox-empty-illu svg { width: 44px; height: 44px; opacity: 0.5; }
      .inbox-empty-illu div { margin-top: 10px; font-size: 13px; }
      .inbox-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 0;
        border-top: 1px solid rgba(0, 0, 0, 0.08);
      }
      .inbox-row:first-of-type { border-top: 0; }
      .inbox-row-email { flex: 1; font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      html.dark-theme .inbox-row { border-top-color: rgba(255, 255, 255, 0.08); }
      @media (prefers-color-scheme: dark) {
        html:not(.light-theme) .inbox-row { border-top-color: rgba(255, 255, 255, 0.08); }
      }
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
      const ok = await openConfirmModal(
        'Sign out?',
        'Are you sure you want to sign out of your account?',
        { okLabel: 'Sign out', cancelLabel: 'Back' }
      );
      if (!ok) return;
      try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); } catch (_) {}
      window.location.href = '/auth.html';
    });
    wrap.appendChild(out);
    return wrap;
  }

  // v0.6.8.5 — Inbox icon button (mounted left of the theme toggle).
  // Shows a pending-count red dot. Click → Inbox modal with Approve/Reject.
  function buildInboxButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'inbox-toggle';
    btn.id = 'admin-inbox-toggle';
    btn.setAttribute('aria-label', 'Pending requests');
    btn.title = 'Pending requests';
    btn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
        <polyline points="22,6 12,13 2,6"/>
      </svg>
      <span class="inbox-dot hidden" id="admin-inbox-dot">0</span>
    `;
    btn.addEventListener('click', () => openInboxModal());
    return btn;
  }

  async function refreshInboxBadge() {
    const dot = document.getElementById('admin-inbox-dot');
    if (!dot) return;
    try {
      const r = await fetch('/api/admin/users/pending', { credentials: 'same-origin' });
      if (!r.ok) { dot.classList.add('hidden'); return; }
      const data = await r.json();
      const n = ((data && data.users) || []).length;
      if (n > 0) {
        dot.textContent = n > 99 ? '99+' : String(n);
        dot.classList.remove('hidden');
      } else {
        dot.classList.add('hidden');
      }
    } catch (_) {
      dot.classList.add('hidden');
    }
  }

  function mountChip(user) {
    const headerActions = document.querySelector('.top-header .header-actions')
      || document.querySelector('.top-header');
    if (!headerActions) return;
    if (user.is_admin) {
      const themeBtn = headerActions.querySelector('#theme-toggle');
      const inbox = buildInboxButton();
      if (themeBtn) {
        headerActions.insertBefore(inbox, themeBtn);
      } else {
        headerActions.appendChild(inbox);
      }
      refreshInboxBadge();
    }
    const chip = buildChip(user);
    headerActions.appendChild(chip);
  }

  async function fetchAllUsers() {
    const r = await fetch('/api/admin/users', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('admin_users_failed');
    const data = await r.json();
    return (data && data.users) || [];
  }

  // v0.6.8.5 — Manage modal is now a compact dashboard. Pending approvals
  // moved to the Inbox icon. Manage-all button (footer-left) opens the
  // big users list modal.
  async function openAdminModal() {
    injectStyles();
    let users = [];
    try {
      users = await fetchAllUsers();
    } catch (err) {
      alert('Failed to load users.');
      return;
    }

    const total = users.length;
    const active = users.filter((u) => u.status === 'active').length;
    const pending = users.filter((u) => u.status === 'pending').length;
    const rejected = users.filter((u) => u.status === 'rejected').length;

    const backdrop = document.createElement('div');
    backdrop.className = 'admin-modal-backdrop';
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) backdrop.remove();
    });

    const modal = document.createElement('div');
    modal.className = 'admin-modal';
    modal.innerHTML = `
      <h2>User management</h2>
      <p class="subtitle">Quick overview. Pending requests are handled in the inbox; click "Manage all" for the full list.</p>
      <div class="admin-summary-grid">
        <div class="admin-summary-cell"><div class="num">${total}</div><div class="lbl">Total</div></div>
        <div class="admin-summary-cell"><div class="num">${active}</div><div class="lbl">Active</div></div>
        <div class="admin-summary-cell"><div class="num">${pending}</div><div class="lbl">Pending</div></div>
        <div class="admin-summary-cell"><div class="num">${rejected}</div><div class="lbl">Rejected</div></div>
      </div>
      <div class="admin-modal-footer">
        <button class="admin-action primary" id="admin-manage-all-btn">Manage all</button>
        <button class="admin-action" id="admin-modal-close-btn">Close</button>
      </div>
    `;
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    modal.querySelector('#admin-modal-close-btn').addEventListener('click', () => backdrop.remove());
    modal.querySelector('#admin-manage-all-btn').addEventListener('click', () => {
      backdrop.remove();
      openAllUsersModal();
    });
  }

  // v0.6.8.5 — Inbox modal: the place where the founder approves or
  // rejects pending registrations. Reachable from the envelope icon
  // in the header.
  async function openInboxModal() {
    injectStyles();
    let pending = [];
    try {
      const r = await fetch('/api/admin/users/pending', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('inbox_failed');
      const data = await r.json();
      pending = (data && data.users) || [];
    } catch (err) {
      alert('Failed to load inbox.');
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
      <h2>Pending requests</h2>
      <p class="subtitle">${pending.length === 0 ? 'No new sign-up requests right now.' : 'Approve or reject the people who recently signed up.'}</p>
      <div id="inbox-list"></div>
      <div class="admin-modal-footer" style="justify-content: flex-end;">
        <button class="admin-action" id="inbox-close-btn">Close</button>
      </div>
    `;
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    modal.querySelector('#inbox-close-btn').addEventListener('click', () => backdrop.remove());

    const listEl = modal.querySelector('#inbox-list');
    if (!pending.length) {
      listEl.innerHTML = `
        <div class="inbox-empty-illu">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
            <polyline points="22,6 12,13 2,6"/>
          </svg>
          <div>Inbox zero — you're all caught up.</div>
        </div>`;
      return;
    }

    pending.forEach((u) => {
      const row = document.createElement('div');
      row.className = 'inbox-row';

      const email = document.createElement('div');
      email.className = 'inbox-row-email';
      email.textContent = u.email;
      row.appendChild(email);

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
          refreshInboxBadge();
          openInboxModal();
        } catch (_) { alert('Approve failed'); approveBtn.disabled = false; }
      });
      row.appendChild(approveBtn);

      const rejectBtn = document.createElement('button');
      rejectBtn.className = 'admin-action danger';
      rejectBtn.textContent = 'Reject';
      rejectBtn.addEventListener('click', async () => {
        if (!confirm(`Reject ${u.email}? They will not be able to sign in.`)) return;
        rejectBtn.disabled = true;
        try {
          const r = await fetch(`/api/admin/users/${u.id}/reject`, {
            method: 'POST', credentials: 'same-origin',
          });
          if (!r.ok) throw new Error();
          backdrop.remove();
          refreshInboxBadge();
          openInboxModal();
        } catch (_) { alert('Reject failed'); rejectBtn.disabled = false; }
      });
      row.appendChild(rejectBtn);

      listEl.appendChild(row);
    });
  }

  // v0.6.8.6 — confirmation sub-modal. Returns a Promise<boolean>.
  function openConfirmModal(title, body, opts) {
    injectStyles();
    const okLabel = (opts && opts.okLabel) || 'Confirm';
    const cancelLabel = (opts && opts.cancelLabel) || 'Back';
    return new Promise((resolve) => {
      const backdrop = document.createElement('div');
      backdrop.className = 'confirm-modal-backdrop';
      const modal = document.createElement('div');
      modal.className = 'confirm-modal';
      modal.innerHTML = `
        <h3></h3>
        <p></p>
        <div class="confirm-modal-actions">
          <button type="button" data-act="cancel"></button>
          <button type="button" class="danger" data-act="ok"></button>
        </div>
      `;
      modal.querySelector('h3').textContent = title;
      modal.querySelector('p').textContent = body;
      modal.querySelector('[data-act="cancel"]').textContent = cancelLabel;
      modal.querySelector('[data-act="ok"]').textContent = okLabel;
      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);
      const finish = (val) => { backdrop.remove(); resolve(val); };
      modal.querySelector('[data-act="cancel"]').addEventListener('click', () => finish(false));
      modal.querySelector('[data-act="ok"]').addEventListener('click', () => finish(true));
      backdrop.addEventListener('click', (e) => { if (e.target === backdrop) finish(false); });
    });
  }

  // v0.6.8.5 / v0.6.8.6 — All-users large modal (Settings-sized).
  // Default view: three columns (email / role / status), read-only.
  // Revoke mode (toggled by the footer button): non-admin rows grow a
  // 4th cell with a circular ⊗ delete button. Confirming wipes the
  // user via DELETE /api/admin/users/{id}.
  async function openAllUsersModal() {
    injectStyles();
    let users = [];
    try {
      users = await fetchAllUsers();
    } catch (err) {
      alert('Failed to load users.');
      return;
    }

    let revokeMode = false;

    const backdrop = document.createElement('div');
    backdrop.className = 'admin-modal-backdrop';
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) backdrop.remove();
    });

    const modal = document.createElement('div');
    modal.className = 'users-modal';
    modal.innerHTML = `
      <div class="users-modal-header">
        <h2>All users</h2>
        <p>${users.length} user${users.length === 1 ? '' : 's'} registered. Founders cannot be modified.</p>
      </div>
      <div class="users-table" id="users-table"></div>
      <div class="users-modal-footer">
        <button class="admin-action danger" id="users-revoke-toggle">Revoke</button>
        <button class="admin-action" id="users-close-btn">Close</button>
      </div>
    `;
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    const tableEl = modal.querySelector('#users-table');
    const revokeToggleBtn = modal.querySelector('#users-revoke-toggle');
    modal.querySelector('#users-close-btn').addEventListener('click', () => backdrop.remove());

    function renderTable() {
      tableEl.innerHTML = '';
      const headRow = document.createElement('div');
      headRow.className = 'users-table-row head';
      headRow.style.gridTemplateColumns = revokeMode
        ? 'minmax(0, 1fr) 140px 130px 60px'
        : 'minmax(0, 1fr) 140px 130px';
      headRow.innerHTML = `
        <div>Email</div>
        <div>Role</div>
        <div>Status</div>
        ${revokeMode ? '<div></div>' : ''}
      `;
      tableEl.appendChild(headRow);

      if (!users.length) {
        tableEl.insertAdjacentHTML('beforeend', '<div class="users-empty">No users yet.</div>');
        return;
      }

      users.forEach((u) => {
        const row = document.createElement('div');
        row.className = 'users-table-row';
        row.style.gridTemplateColumns = revokeMode
          ? 'minmax(0, 1fr) 140px 130px 60px'
          : 'minmax(0, 1fr) 140px 130px';
        row.dataset.userId = String(u.id);

        const email = document.createElement('div');
        email.className = 'users-table-email';
        email.textContent = u.email;
        row.appendChild(email);

        const role = document.createElement('div');
        const rolePill = document.createElement('span');
        rolePill.className = 'users-role-pill' + (u.is_admin ? ' is-admin' : '');
        rolePill.textContent = u.is_admin ? 'Admin' : 'User';
        role.appendChild(rolePill);
        row.appendChild(role);

        const statusCell = document.createElement('div');
        const rawStatus = (u.status || '').toLowerCase();
        const statusLabel = {
          active: 'Active',
          pending: 'Pending',
          rejected: 'Rejected',
        }[rawStatus] || (rawStatus ? rawStatus.charAt(0).toUpperCase() + rawStatus.slice(1) : 'Unknown');
        const statusPill = document.createElement('span');
        statusPill.className = `admin-user-status status-${rawStatus || 'unknown'}`;
        statusPill.textContent = statusLabel;
        statusCell.appendChild(statusPill);
        row.appendChild(statusCell);

        if (revokeMode) {
          const revokeCell = document.createElement('div');
          revokeCell.className = 'users-revoke-cell';
          if (!u.is_admin) {
            const xBtn = document.createElement('button');
            xBtn.className = 'users-revoke-btn';
            xBtn.setAttribute('aria-label', `Remove ${u.email}`);
            xBtn.title = `Remove ${u.email}`;
            xBtn.innerHTML = `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <line x1="6" y1="6" x2="18" y2="18"/>
                <line x1="18" y1="6" x2="6" y2="18"/>
              </svg>
            `;
            xBtn.addEventListener('click', async () => {
              const ok = await openConfirmModal(
                'Remove user?',
                `Are you sure you want to revoke access for ${u.email}? This cannot be undone.`
              );
              if (!ok) return;
              xBtn.disabled = true;
              try {
                const r = await fetch(`/api/admin/users/${u.id}`, {
                  method: 'DELETE',
                  credentials: 'same-origin',
                });
                if (!r.ok) throw new Error();
                users = users.filter((x) => x.id !== u.id);
                renderTable();
                const subtitleEl = modal.querySelector('.users-modal-header p');
                if (subtitleEl) {
                  subtitleEl.textContent = `${users.length} user${users.length === 1 ? '' : 's'} registered. Founders cannot be modified.`;
                }
                refreshInboxBadge();
              } catch (_) {
                alert('Remove failed.');
                xBtn.disabled = false;
              }
            });
            revokeCell.appendChild(xBtn);
          }
          row.appendChild(revokeCell);
        }

        tableEl.appendChild(row);
      });
    }

    revokeToggleBtn.addEventListener('click', () => {
      revokeMode = !revokeMode;
      revokeToggleBtn.textContent = revokeMode ? 'Done' : 'Revoke';
      revokeToggleBtn.classList.toggle('danger', !revokeMode);
      revokeToggleBtn.classList.toggle('primary', revokeMode);
      renderTable();
    });

    renderTable();
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
