// AI Video Prompt Generator - Frontend Logic

// DOM Elements
const titleInput = document.getElementById('title-input');
const generateBtn = document.getElementById('generate-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const copyBtn = document.getElementById('copy-btn');
const downloadBtn = document.getElementById('download-btn');
const editBtn = document.getElementById('edit-btn');
const regenerateBtn = document.getElementById('regenerate-btn');
const regenerateFeedbackInput = document.getElementById('regenerate-feedback-input');
const themeToggle = document.getElementById('theme-toggle');
const settingsBtn = document.getElementById('settingsBtn');
const settingsModal = document.getElementById('settingsModal');
const settingsClose = document.querySelector('.settings-close');
const settingsBackdrop = document.querySelector('.settings-backdrop');
const settingsNavItems = document.querySelectorAll('.settings-nav-item');
const settingsPanels = document.querySelectorAll('.settings-panel');

// Sections
const initialSection = document.getElementById('initial-section');
const loadingSection = document.getElementById('loading-section');
const errorSection = document.getElementById('error-section');
const resultSection = document.getElementById('result-section');

// Error elements
const errorMessage = document.getElementById('error-message');
const errorDetails = document.getElementById('error-details');
const errorStdout = document.getElementById('error-stdout');
const errorStderr = document.getElementById('error-stderr');

// Result elements
const resultSlug = document.getElementById('result-slug');
const resultDir = document.getElementById('result-dir');
const promptContent = document.getElementById('prompt-content');

// State
let isGenerating = false;
let currentSlug = '';
let currentHistoryId = null;
let currentTopicGroupId = null;
// v0.5.3 - Latest VideoJob for the active record (null in Prompt Mode or
// when no VideoJob exists yet). Backed by /api/video/history/{id}/jobs/latest.
let currentVideoJob = null;
let historyItems = [];
let trashItems = [];
let favoriteItems = [];
let currentMode = 'history'; // 'history' | 'trash' | 'favorites'

// v0.5.1 - Top-level app mode (Prompt Mode vs Video Mode).
// 'prompt' routes API calls to `/api/...`, 'video' routes them to `/api/video/...`.
// All Prompt Mode v0.4.10 protections continue to apply when this is 'prompt'.
let currentAppMode = 'prompt';

/**
 * Build the API URL for the active app mode.
 *   apiUrl('/history')           -> '/api/history'  (prompt mode)
 *                                  -> '/api/video/history' (video mode)
 *   apiUrl(`/history/${id}`)     -> same pattern
 * The suffix MUST start with '/'.
 */
function apiUrl(suffix) {
    const base = currentAppMode === 'video' ? '/api/video' : '/api';
    return base + suffix;
}

/** Backwards-compatible alias used in stability checks. */
function getApiPrefix() {
    return currentAppMode === 'video' ? '/api/video' : '/api';
}

/**
 * v0.5.1.2 — pick the default view-mode tab for the current app mode.
 * Video Mode lands on the Video tab; Prompt Mode keeps Raw Text.
 */
function getDefaultViewMode() {
    return currentAppMode === 'video' ? 'video' : 'raw';
}

/**
 * v0.5.1.2 hotfix: Reflect tab capabilities on Edit / Copy / Download buttons.
 *
 * Each button has its own .icon-tooltip child — that is the ONLY visible
 * tooltip we want. Native browser `title` is intentionally NOT set on these
 * three buttons (it would render a second, misplaced tooltip). The
 * unavailable hint is stored on `data-unavailable-message` for the click
 * handler to read when the button is disabled.
 */
function updateActionButtonsForCurrentView() {
    try {
        const editBtnEl = document.getElementById('edit-btn');
        const copyBtnEl = document.getElementById('copy-btn');
        const downloadBtnEl = document.getElementById('download-btn');

        // v0.5.1.2 round 3: every tab-switch resets tooltip placement so the
        // default center-above-icon rule wins. tooltip-below is only added
        // back below for the Video tab Download button (the single tooltip
        // that is too long to fit above without colliding with the toolbar).
        // The legacy data-tooltip-align attribute is also cleared in case
        // any earlier markup still has it.
        [editBtnEl, copyBtnEl, downloadBtnEl].forEach(btn => {
            if (!btn) return;
            btn.classList.remove('tooltip-below');
            if (btn.hasAttribute('data-tooltip-align')) {
                btn.removeAttribute('data-tooltip-align');
            }
            if (btn.hasAttribute('title')) {
                btn.removeAttribute('title');
            }
        });

        const setBtnState = (btn, disabled, tooltipText) => {
            if (!btn) return;
            if (disabled) {
                btn.setAttribute('data-disabled', 'true');
                btn.setAttribute('data-unavailable-message', tooltipText || '');
            } else {
                btn.removeAttribute('data-disabled');
                btn.removeAttribute('data-unavailable-message');
            }
            const tip = btn.querySelector('.icon-tooltip');
            if (tip && tooltipText) {
                tip.textContent = tooltipText;
            }
            if (tooltipText) {
                btn.setAttribute('aria-label', tooltipText);
            }
            // Always strip native title so the browser tooltip doesn't fight
            // the project's .icon-tooltip.
            if (btn.hasAttribute('title')) {
                btn.removeAttribute('title');
            }
        };
        if (currentPromptViewMode === 'video') {
            setBtnState(editBtnEl, true, 'Video tab cannot be edited.');
            setBtnState(copyBtnEl, true, 'Video content cannot be copied.');
            setBtnState(downloadBtnEl, true, 'Video file is not available yet. Download will be available when a video file exists.');
            // Long Download tooltip: drop it below the icon, still
            // center-axis aligned (left:50% + translateX(-50%)).
            if (downloadBtnEl) {
                downloadBtnEl.classList.add('tooltip-below');
            }
        } else if (currentPromptViewMode === 'review') {
            setBtnState(editBtnEl, true, 'AI Review cannot be edited.');
            setBtnState(copyBtnEl, false, 'Copy');
            setBtnState(downloadBtnEl, false, 'Download');
        } else {
            setBtnState(editBtnEl, false, 'Edit');
            setBtnState(copyBtnEl, false, 'Copy');
            setBtnState(downloadBtnEl, false, 'Download');
        }
        // Make sure newly added .icon-button nodes (or freshly mutated
        // tooltip text) are picked up by the global tooltip portal, and
        // refresh the active tooltip if a hovered button's text changed.
        if (typeof bindGlobalIconTooltips === 'function') {
            bindGlobalIconTooltips();
        }
        if (typeof refreshActiveGlobalIconTooltip === 'function') {
            refreshActiveGlobalIconTooltip();
        }
    } catch (e) {
        // Non-fatal — buttons will simply use their default tooltips.
    }
}

// =====================================================================
// Global tooltip portal (v0.5.1.2 UI hotfix round 4)
//
// All `.icon-button` tooltips render through a single fixed-positioned
// node appended to document.body. This avoids overflow / z-index /
// stacking-context clipping by ancestor containers (video frame,
// result card, dark panels, etc.). Tooltip text is sourced live from
// each button's inner `.icon-tooltip` span (default state) or from
// `data-unavailable-message` (disabled state). Placement defaults to
// "above center"; long-tooltip buttons opt in to "below center" via
// the `.tooltip-below` marker class. Native browser `title` is never
// used.
// =====================================================================

let _activeTooltipAnchor = null;

function ensureGlobalIconTooltip() {
    let tooltip = document.getElementById('global-icon-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'global-icon-tooltip';
        tooltip.className = 'global-icon-tooltip hidden';
        document.body.appendChild(tooltip);
    }
    return tooltip;
}

function getIconTooltipMessage(button) {
    if (!button) return '';
    const disabledMessage = button.getAttribute('data-unavailable-message');
    if (button.getAttribute('data-disabled') === 'true' && disabledMessage) {
        return disabledMessage;
    }
    const tooltipEl = button.querySelector('.icon-tooltip');
    return tooltipEl ? (tooltipEl.textContent || '').trim() : '';
}

function getIconTooltipPlacement(button) {
    if (!button) return 'top';
    return button.classList.contains('tooltip-below') ? 'below' : 'top';
}

function showGlobalIconTooltip(anchorEl, message, options) {
    if (!anchorEl || !message) return;
    const opts = options || {};
    const tooltip = ensureGlobalIconTooltip();
    tooltip.textContent = String(message);
    tooltip.classList.remove('hidden');
    // Measure off-screen first so we can compute centered placement
    // without the tooltip flashing in the wrong spot.
    tooltip.style.visibility = 'hidden';
    tooltip.style.left = '0px';
    tooltip.style.top = '0px';
    // Force a reflow so width/height reflect the new textContent.
    // eslint-disable-next-line no-unused-expressions
    tooltip.offsetHeight;

    const anchorRect = anchorEl.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const gap = 8;
    const viewportPadding = 8;

    // Center the tooltip horizontally on the anchor (clamped to viewport).
    let left = anchorRect.left + anchorRect.width / 2 - tooltipRect.width / 2;
    // Default placement: above the icon.
    let top = anchorRect.top - tooltipRect.height - gap;

    const preferBelow = opts.placement === 'below';
    if (preferBelow || top < viewportPadding) {
        top = anchorRect.bottom + gap;
    }

    if (left < viewportPadding) left = viewportPadding;
    const maxLeft = window.innerWidth - tooltipRect.width - viewportPadding;
    if (left > maxLeft) left = maxLeft;

    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
    tooltip.style.visibility = 'visible';
    // Trigger fade-in.
    // eslint-disable-next-line no-unused-expressions
    tooltip.offsetHeight;
    tooltip.classList.add('show');
    _activeTooltipAnchor = anchorEl;
}

function hideGlobalIconTooltip() {
    const tooltip = document.getElementById('global-icon-tooltip');
    if (!tooltip) return;
    tooltip.classList.remove('show');
    tooltip.classList.add('hidden');
    _activeTooltipAnchor = null;
}

function refreshActiveGlobalIconTooltip() {
    if (!_activeTooltipAnchor || !document.body.contains(_activeTooltipAnchor)) {
        _activeTooltipAnchor = null;
        return;
    }
    const message = getIconTooltipMessage(_activeTooltipAnchor);
    if (!message) {
        hideGlobalIconTooltip();
        return;
    }
    showGlobalIconTooltip(_activeTooltipAnchor, message, {
        placement: getIconTooltipPlacement(_activeTooltipAnchor),
    });
}

function bindGlobalIconTooltips(root) {
    const scope = root || document;
    const buttons = scope.querySelectorAll('.icon-button');
    buttons.forEach((btn) => {
        if (btn.dataset.globalTooltipBound === 'true') return;
        btn.dataset.globalTooltipBound = 'true';
        if (btn.hasAttribute('title')) btn.removeAttribute('title');

        btn.addEventListener('mouseenter', () => {
            const message = getIconTooltipMessage(btn);
            if (!message) return;
            showGlobalIconTooltip(btn, message, {
                placement: getIconTooltipPlacement(btn),
            });
        });
        btn.addEventListener('mouseleave', () => {
            if (_activeTooltipAnchor === btn) hideGlobalIconTooltip();
        });
        btn.addEventListener('focus', () => {
            const message = getIconTooltipMessage(btn);
            if (!message) return;
            showGlobalIconTooltip(btn, message, {
                placement: getIconTooltipPlacement(btn),
            });
        });
        btn.addEventListener('blur', () => {
            if (_activeTooltipAnchor === btn) hideGlobalIconTooltip();
        });
    });
}

window.addEventListener('scroll', hideGlobalIconTooltip, true);
window.addEventListener('resize', hideGlobalIconTooltip);

/**
 * v0.5.1.2 — lightweight non-blocking toast for short status messages.
 *
 * Falls back to alert() if for any reason the DOM cannot host a toast.
 * Used by Video Mode unavailable-action hints, the no-source player
 * notice, and a few edge cases where alert() would feel too heavy.
 */
function showAppToast(message, opts) {
    if (!message) return;
    try {
        const ttl = (opts && typeof opts.ttl === 'number') ? opts.ttl : 2400;
        let host = document.getElementById('app-toast-host');
        if (!host) {
            host = document.createElement('div');
            host.id = 'app-toast-host';
            host.className = 'app-toast-host';
            document.body.appendChild(host);
        }
        const el = document.createElement('div');
        el.className = 'app-toast';
        el.textContent = String(message);
        host.appendChild(el);
        // Force a reflow so the transition picks up the entrance.
        // eslint-disable-next-line no-unused-expressions
        el.offsetHeight;
        el.classList.add('show');
        setTimeout(() => {
            el.classList.remove('show');
            setTimeout(() => {
                if (el.parentNode) el.parentNode.removeChild(el);
            }, 250);
        }, ttl);
    } catch (e) {
        try { alert(message); } catch (_) { /* noop */ }
    }
}
window.showAppToast = showAppToast;
window.getCurrentAppMode = function() { return currentAppMode; };

/**
 * v0.5.1.2 hotfix: Player-scoped toast.
 *
 * Mounts a transient message inside #video-player-shell so the cue
 * appears inside the video frame instead of at the page bottom.
 * Used exclusively for the no-source player click hint. Falls back
 * to showAppToast() only if the player shell cannot be located.
 */
function showVideoPlayerToast(message, opts) {
    if (!message) return;
    try {
        const shell = document.getElementById('video-player-shell');
        if (!shell) {
            if (typeof showAppToast === 'function') showAppToast(message);
            return;
        }
        const ttl = (opts && typeof opts.ttl === 'number') ? opts.ttl : 1800;
        // Reuse / replace prior toast so rapid clicks don't stack.
        const prior = shell.querySelector('.video-player-toast');
        if (prior && prior.parentNode) {
            prior.parentNode.removeChild(prior);
        }
        const el = document.createElement('div');
        el.className = 'video-player-toast';
        el.textContent = String(message);
        // Ensure shell can host an absolutely-positioned child.
        const computed = window.getComputedStyle(shell);
        if (computed && computed.position === 'static') {
            shell.style.position = 'relative';
        }
        shell.appendChild(el);
        // Force reflow so the transition runs.
        el.offsetHeight;
        el.classList.add('show');
        setTimeout(() => {
            el.classList.remove('show');
            setTimeout(() => {
                if (el.parentNode) el.parentNode.removeChild(el);
            }, 220);
        }, ttl);
    } catch (e) {
        if (typeof showAppToast === 'function') showAppToast(message);
    }
}
window.showVideoPlayerToast = showVideoPlayerToast;
let currentSearchQuery = '';
let currentDateFilter = 'all';
let currentVersions = [];
let currentVersionNumber = null;

// Prompt view state
let currentPromptViewMode = 'raw'; // 'raw' | 'preview' | 'overview' | 'review'
let currentRawText = '';
let currentPreviewText = '';
let currentPreviewTextEdited = ''; // User-edited preview text
let currentOverviewText = '';
let currentChangeSummaryText = ''; // Change summary for regenerated versions
let currentWebCopyText = ''; // v0.5.1.2: Video Mode Web Copy plain text (YouTube/TikTok titles/descriptions/captions/posts)
let currentReviewData = null; // AI Review data
let isEditingPrompt = false; // Whether in editing mode
let isRegenerating = false; // Whether regenerating

// CRITICAL: Edit mode lock to prevent view pollution
let editingViewMode = null; // Lock the view being edited ('raw' | 'preview' | 'overview')
let originalEditContent = ''; // Original content before editing (for cancel)

/**
 * Render a history record to the result page
 */
function renderHistoryRecord(item) {
    // Stop any ongoing review polling when switching records
    if (typeof stopReviewPolling === 'function') {
        stopReviewPolling();
    }

    // Update state
    currentHistoryId = item.id;
    currentTopicGroupId = item.topic_group_id;
    currentSlug = item.slug;
    currentVersionNumber = item.version_number;

    // Update prompt view state
    currentRawText = item.prompt || '';
    currentPreviewTextEdited = item.preview_text || '';
    currentChangeSummaryText = item.change_summary_cn || '';
    currentWebCopyText = item.web_copy_text || '';
    currentReviewData = null; // Reset review data for new version

    // Generate preview - use preview_text if available
    if (currentPreviewTextEdited) {
        currentPreviewText = `<div class="preview-content">${escapeHtml(currentPreviewTextEdited).replace(/\n/g, '<br>')}</div>`;
    } else {
        try {
            const sections = parsePromptSections(currentRawText);
            currentPreviewText = generatePreviewHTML(sections);
        } catch (error) {
            console.error('Failed to generate preview:', error);
            currentPreviewText = '<div class="preview-error">Preview generation failed. See Raw Text for full content.</div>';
        }
    }

    // Get or generate overview
    currentOverviewText = item.overview_cn || generateFallbackOverview(item.title);

    // Show result section
    resultSlug.textContent = item.slug;
    resultDir.textContent = item.output_dir;
    promptContent.value = currentRawText;
    document.getElementById('prompt-preview').innerHTML = currentPreviewText;

    // Update overview with change summary if available
    let overviewHTML = `<div class="overview-content">${escapeHtml(currentOverviewText).replace(/\n/g, '<br>')}</div>`;
    if (currentChangeSummaryText) {
        overviewHTML += `
            <div class="change-summary-section">
                <h4 class="change-summary-title">本次生成新增或改动的内容</h4>
                <div class="change-summary-content">${escapeHtml(currentChangeSummaryText).replace(/\n/g, '<br>')}</div>
            </div>
        `;
    }
    // v0.5.5: in Video Mode, append a small Provider Contract Summary block.
    // The summary reflects v0.5.5 invariants (no real API call); the real
    // validation result can be fetched lazily from
    // /api/video/history/{id}/provider-contract.
    if (currentAppMode === 'video') {
        overviewHTML += renderProviderContractSummaryHTML(item);
    }
    document.getElementById('prompt-overview').innerHTML = overviewHTML;
    if (currentAppMode === 'video' && item && item.id != null) {
        refreshProviderContractSummary(item.id);
    }

    // v0.5.3: in Video Mode, fetch the latest VideoJob and render the
    // status panel inside the Video tab. Prompt Mode skips this entirely.
    if (currentAppMode === 'video' && currentHistoryId != null) {
        currentVideoJob = null;
        renderVideoJobStatus(null);
        fetch(`/api/video/history/${currentHistoryId}/jobs/latest`)
            .then(r => r.ok ? r.json() : null)
            .then(payload => {
                if (!payload || !payload.success) return;
                if (currentHistoryId !== item.id) return;
                currentVideoJob = payload.job || null;
                renderVideoJobStatus(currentVideoJob);
            })
            .catch(err => console.warn('Failed to fetch latest VideoJob:', err));
        // v0.5.3: if the record has a real video asset, route the player
        // through the asset endpoint (never an absolute filesystem path).
        // v0.5.3 records never set video_file_path, so this is a no-op now.
        try {
            applyVideoAssetSrc(item);
        } catch (e) { /* defensive */ }
    } else {
        currentVideoJob = null;
        renderVideoJobStatus(null);
    }
}

/**
 * v0.5.3 — If the active Video Mode record advertises a video asset,
 * point the <video> element at the asset endpoint URL. Never assigns a
 * local filesystem path. v0.5.3 always leaves video_file_path null, so
 * this clears the src.
 */
function applyVideoAssetSrc(item) {
    const v = document.getElementById('video-element');
    if (!v) return;
    const hasAsset = item && item.video_file_path && currentHistoryId != null;
    if (!hasAsset) {
        try {
            v.pause();
            v.removeAttribute('src');
            v.load();
        } catch (e) { /* ignore */ }
        return;
    }
    const url = `/api/video/history/${currentHistoryId}/asset/video`;
    if (v.getAttribute('src') !== url) {
        v.setAttribute('src', url);
        try { v.load(); } catch (e) { /* ignore */ }
    }
}

/**
 * Show a specific section and hide others
 */
function showSection(section) {
    initialSection.classList.add('hidden');
    loadingSection.classList.add('hidden');
    errorSection.classList.add('hidden');
    resultSection.classList.add('hidden');

    document.body.classList.remove('has-result', 'has-loading', 'has-error');

    if (section) {
        section.classList.remove('hidden');

        if (section === resultSection) {
            document.body.classList.add('has-result');
        } else if (section === loadingSection) {
            document.body.classList.add('has-loading');
        } else if (section === errorSection) {
            document.body.classList.add('has-error');
        }
    }
}

/**
 * Auto-resize textarea based on content
 */
function autoResizeTextarea() {
    titleInput.style.height = 'auto';
    const newHeight = Math.min(titleInput.scrollHeight, 140);
    titleInput.style.height = newHeight + 'px';
}

/**
 * Load history from database
 */
async function loadHistory(searchQuery = '', dateFilter = 'all') {
    try {
        const params = new URLSearchParams();
        if (searchQuery) {
            params.append('q', searchQuery);
        }
        if (dateFilter && dateFilter !== 'all') {
            params.append('date_filter', dateFilter);
        }

        const url = params.toString() ? `${apiUrl('/history')}?${params}` : apiUrl('/history');
        const response = await fetch(url);
        const data = await response.json();

        if (data.success && data.items) {
            historyItems = data.items;
            renderHistoryList(data.items);
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

/**
 * Load trash from database
 */
async function loadTrash(searchQuery = '') {
    try {
        const url = searchQuery
            ? `${apiUrl('/trash')}?q=${encodeURIComponent(searchQuery)}`
            : apiUrl('/trash');

        const response = await fetch(url);
        const data = await response.json();

        if (data.success && data.items) {
            trashItems = data.items;
            renderTrashList(data.items);
        }
    } catch (error) {
        console.error('Failed to load trash:', error);
    }
}

/**
 * Load favorites from database
 */
async function loadFavorites(searchQuery = '') {
    try {
        const url = searchQuery
            ? `${apiUrl('/favorites')}?q=${encodeURIComponent(searchQuery)}`
            : apiUrl('/favorites');

        const response = await fetch(url);
        const data = await response.json();

        if (data.success && data.items) {
            favoriteItems = data.items;
            renderFavoritesList(data.items);
        }
    } catch (error) {
        console.error('Failed to load favorites:', error);
    }
}

/**
 * Render history list to sidebar
 */
function renderHistoryList(items) {
    const historyList = document.getElementById('historyList');

    if (!historyList) {
        return;
    }

    if (items.length === 0) {
        // v0.5.1.2: mode-aware sidebar empty state
        const emptyText = currentAppMode === 'video' ? 'No video topics yet.' : 'No history yet';
        historyList.innerHTML = `<div class="no-history">${emptyText}</div>`;
        return;
    }

    historyList.innerHTML = items.map(item => {
        const isActive = currentTopicGroupId != null && String(item.topic_group_id) === String(currentTopicGroupId);
        const isPinned = item.is_pinned || false;
        const isFavorite = item.is_favorite || false;
        const versionCount = item.version_count || 1;

        // Pin indicator SVG
        const pinIcon = isPinned ? `
            <span class="pin-indicator">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M16 12V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/>
                </svg>
            </span>
        ` : '';

        // Favorite indicator SVG
        const favoriteIcon = isFavorite ? `
            <span class="favorite-indicator">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
            </span>
        ` : '';

        return `
            <div class="topic-item ${isActive ? 'active' : ''} ${isFavorite ? 'favorite' : ''}"
                 data-history-id="${item.id}"
                 data-topic-group-id="${item.topic_group_id}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <span class="topic-title">${escapeHtml(item.title)}</span>
                <div class="history-actions">
                    ${pinIcon}
                    ${favoriteIcon}
                    <button class="history-more-btn"
                            data-history-id="${item.id}"
                            data-topic-group-id="${item.topic_group_id}"
                            data-is-pinned="${isPinned}"
                            data-is-favorite="${isFavorite}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                            <circle cx="12" cy="5" r="2"/>
                            <circle cx="12" cy="12" r="2"/>
                            <circle cx="12" cy="19" r="2"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers for topic items
    historyList.querySelectorAll('.topic-item').forEach(item => {
        item.addEventListener('click', handleHistoryItemClick);
    });

    // Add click handlers for more buttons
    historyList.querySelectorAll('.history-more-btn').forEach(btn => {
        btn.addEventListener('click', handleMoreButtonClick);
    });
}

/**
 * Render trash list to sidebar
 */
function renderTrashList(items) {
    const historyList = document.getElementById('historyList');

    if (!historyList) {
        return;
    }

    if (items.length === 0) {
        historyList.innerHTML = '<div class="no-history">Trash is empty</div>';
        return;
    }

    historyList.innerHTML = items.map(item => {
        return `
            <div class="topic-item"
                 data-history-id="${item.id}"
                 data-topic-group-id="${item.topic_group_id}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <span>${escapeHtml(item.title)}</span>
                <div class="history-actions">
                    <button class="trash-delete-btn"
                            data-topic-group-id="${item.topic_group_id}"
                            title="Permanently delete">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers for permanent delete buttons
    historyList.querySelectorAll('.trash-delete-btn').forEach(btn => {
        btn.addEventListener('click', handlePermanentDeleteClick);
    });
}

/**
 * Render favorites list to sidebar
 */
function renderFavoritesList(items) {
    const historyList = document.getElementById('historyList');

    if (!historyList) {
        return;
    }

    if (items.length === 0) {
        historyList.innerHTML = `
            <div class="no-history">
                <div class="no-history-icon">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                    </svg>
                </div>
                <div class="no-history-title">No favorites yet</div>
                <div class="no-history-subtitle">Favorite important prompts to find them quickly</div>
            </div>
        `;
        return;
    }

    historyList.innerHTML = items.map(item => {
        const isActive = currentTopicGroupId != null && String(item.topic_group_id) === String(currentTopicGroupId);
        const isPinned = item.is_pinned || false;
        const versionCount = item.version_count || 1;

        // Pin indicator SVG
        const pinIcon = isPinned ? `
            <span class="pin-indicator">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M16 12V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/>
                </svg>
            </span>
        ` : '';

        // Favorite indicator SVG (always show in favorites mode)
        const favoriteIcon = `
            <span class="favorite-indicator">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
            </span>
        `;

        return `
            <div class="topic-item ${isActive ? 'active' : ''} favorite"
                 data-history-id="${item.id}"
                 data-topic-group-id="${item.topic_group_id}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <span class="topic-title">${escapeHtml(item.title)}</span>
                <div class="history-actions">
                    ${pinIcon}
                    ${favoriteIcon}
                    <button class="history-more-btn"
                            data-history-id="${item.id}"
                            data-topic-group-id="${item.topic_group_id}"
                            data-is-pinned="${isPinned}"
                            data-is-favorite="true">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                            <circle cx="12" cy="5" r="2"/>
                            <circle cx="12" cy="12" r="2"/>
                            <circle cx="12" cy="19" r="2"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers for topic items
    historyList.querySelectorAll('.topic-item').forEach(item => {
        item.addEventListener('click', handleHistoryItemClick);
    });

    // Add click handlers for more buttons
    historyList.querySelectorAll('.history-more-btn').forEach(btn => {
        btn.addEventListener('click', handleMoreButtonClick);
    });
}

/**
 * Handle history item click
 */
async function handleHistoryItemClick(event) {
    // Ignore if clicking on actions (more button, rename input)
    if (event.target.closest('.history-actions') || event.target.classList.contains('topic-item-rename-input')) {
        return;
    }

    // CRITICAL: Block history switching while editing
    if (isEditingPrompt) {
        alert('You are currently editing. Please save or cancel your changes before switching to another record.');
        return;
    }

    const historyId = parseInt(event.currentTarget.dataset.historyId);
    const topicGroupId = event.currentTarget.dataset.topicGroupId;

    if (!historyId || !topicGroupId) {
        return;
    }

    try {
        const response = await fetch(apiUrl(`/history/${historyId}`));
        const data = await response.json();

        if (data.success && data.item) {
            const item = data.item;

            // Render history record
            renderHistoryRecord(item);

            // Fill input
            titleInput.value = item.title;
            autoResizeTextarea();

            // v0.5.1.2: Video Mode lands on Video tab; Prompt Mode keeps Raw Text.
            switchPromptViewMode(getDefaultViewMode());

            showSection(resultSection);

            // Load and show version selector (show even for single version)
            await loadAndShowVersionSelector(item.topic_group_id, item.id);

            // Update active state in sidebar
            if (currentMode === 'history') {
                renderHistoryList(historyItems);
            } else if (currentMode === 'favorites') {
                renderFavoritesList(favoriteItems);
            }

            // Scroll to result
            setTimeout(() => {
                resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        }
    } catch (error) {
        console.error('Failed to load history item:', error);
    }
}

/**
 * Handle more button click (show menu)
 */
function handleMoreButtonClick(event) {
    event.stopPropagation();

    const button = event.currentTarget;
    const historyId = parseInt(button.dataset.historyId);
    const topicGroupId = button.dataset.topicGroupId;
    const isPinned = button.dataset.isPinned === 'true';
    const isFavorite = button.dataset.isFavorite === 'true';

    // Close any existing menu
    closeHistoryMenu();

    // Create and show menu
    showHistoryMenu(button, historyId, topicGroupId, isPinned, isFavorite);
}

/**
 * Show history action menu
 */
function showHistoryMenu(button, historyId, topicGroupId, isPinned, isFavorite) {
    // Create menu element
    const menu = document.createElement('div');
    menu.className = 'history-menu show';
    menu.id = 'historyMenu';

    // Pin/Unpin option
    const pinText = isPinned ? '取消置顶' : '置顶对话';
    const pinIcon = '<path d="M16 12V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/>';

    // Favorite/Unfavorite option
    const favoriteText = isFavorite ? '取消收藏' : '收藏';
    const favoriteIcon = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>';

    menu.innerHTML = `
        <button class="history-menu-item" data-action="${isPinned ? 'unpin' : 'pin'}" data-history-id="${historyId}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                ${pinIcon}
            </svg>
            <span>${pinText}</span>
        </button>
        <button class="history-menu-item" data-action="${isFavorite ? 'unfavorite' : 'favorite'}" data-topic-group-id="${topicGroupId}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="${isFavorite ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
                ${favoriteIcon}
            </svg>
            <span>${favoriteText}</span>
        </button>
        <button class="history-menu-item" data-action="rename" data-topic-group-id="${topicGroupId}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            <span>重命名</span>
        </button>
        <button class="history-menu-item danger" data-action="delete" data-topic-group-id="${topicGroupId}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z"/>
            </svg>
            <span>删除对话</span>
        </button>
    `;

    document.body.appendChild(menu);

    // Position menu near button
    const buttonRect = button.getBoundingClientRect();
    menu.style.top = `${buttonRect.bottom + 4}px`;
    menu.style.left = `${buttonRect.left - menu.offsetWidth + button.offsetWidth}px`;

    // Add click handlers
    menu.querySelectorAll('.history-menu-item').forEach(item => {
        item.addEventListener('click', handleMenuItemClick);
    });

    // Close menu when clicking outside
    setTimeout(() => {
        document.addEventListener('click', closeHistoryMenuOnOutsideClick);
    }, 0);
}

/**
 * Close history menu
 */
function closeHistoryMenu() {
    const menu = document.getElementById('historyMenu');
    if (menu) {
        menu.remove();
        document.removeEventListener('click', closeHistoryMenuOnOutsideClick);
    }
}

/**
 * Close menu when clicking outside
 */
function closeHistoryMenuOnOutsideClick(event) {
    const menu = document.getElementById('historyMenu');
    if (menu && !menu.contains(event.target)) {
        closeHistoryMenu();
    }
}

/**
 * Handle menu item click
 */
async function handleMenuItemClick(event) {
    event.stopPropagation();

    const action = event.currentTarget.dataset.action;
    const historyId = event.currentTarget.dataset.historyId ? parseInt(event.currentTarget.dataset.historyId) : null;
    const topicGroupId = event.currentTarget.dataset.topicGroupId;

    closeHistoryMenu();

    if (action === 'pin' && historyId) {
        await pinHistory(historyId);
    } else if (action === 'unpin' && historyId) {
        await unpinHistory(historyId);
    } else if (action === 'favorite' && topicGroupId) {
        await favoriteHistory(topicGroupId);
    } else if (action === 'unfavorite' && topicGroupId) {
        await unfavoriteHistory(topicGroupId);
    } else if (action === 'rename' && topicGroupId) {
        startRenameMode(topicGroupId);
    } else if (action === 'delete' && topicGroupId) {
        showSoftDeleteConfirmation(topicGroupId);
    }
}

/**
 * Pin a history record
 */
async function pinHistory(historyId) {
    try {
        const response = await fetch(apiUrl(`/history/${historyId}/pin`), {
            method: 'POST',
        });

        const data = await response.json();

        if (data.success) {
            // Reload history list
            await loadHistory();
        } else {
            alert('置顶失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to pin history:', error);
        alert('置顶失败');
    }
}

/**
 * Unpin a history record
 */
async function unpinHistory(historyId) {
    try {
        const response = await fetch(apiUrl(`/history/${historyId}/unpin`), {
            method: 'POST',
        });

        const data = await response.json();

        if (data.success) {
            // Reload history list
            await loadHistory();
        } else {
            alert('取消置顶失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to unpin history:', error);
        alert('取消置顶失败');
    }
}

/**
 * Favorite a history group
 */
async function favoriteHistory(topicGroupId) {
    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/favorite`), {
            method: 'POST',
        });

        const data = await response.json();

        if (data.success) {
            // Reload current list
            if (currentMode === 'history') {
                await loadHistory(currentSearchQuery, currentDateFilter);
            } else if (currentMode === 'favorites') {
                await loadFavorites(currentSearchQuery);
            }
        } else {
            alert('收藏失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to favorite history:', error);
        alert('收藏失败');
    }
}

/**
 * Unfavorite a history group
 */
async function unfavoriteHistory(topicGroupId) {
    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/unfavorite`), {
            method: 'POST',
        });

        const data = await response.json();

        if (data.success) {
            // Reload current list
            if (currentMode === 'history') {
                await loadHistory(currentSearchQuery, currentDateFilter);
            } else if (currentMode === 'favorites') {
                await loadFavorites(currentSearchQuery);
            }
        } else {
            alert('取消收藏失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to unfavorite history:', error);
        alert('取消收藏失败');
    }
}

/**
 * Start rename mode for a topic group
 */
function startRenameMode(topicGroupId) {
    const topicItem = document.querySelector(`.topic-item[data-topic-group-id="${topicGroupId}"]`);
    if (!topicItem) return;

    const titleSpan = topicItem.querySelector('.topic-title');
    if (!titleSpan) return;

    const currentTitle = titleSpan.textContent;

    // Create input element
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'topic-item-rename-input';
    input.value = currentTitle;

    // Replace span with input
    titleSpan.replaceWith(input);

    // Focus and select
    input.focus();
    input.select();

    // Save on blur
    input.addEventListener('blur', () => finishRenameMode(topicGroupId, input, currentTitle));

    // Save on Enter
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelRenameMode(topicGroupId, currentTitle);
        }
    });
}

/**
 * Finish rename mode (save new title)
 */
async function finishRenameMode(topicGroupId, input, oldTitle) {
    const newTitle = input.value.trim();

    // If empty or unchanged, cancel
    if (!newTitle || newTitle === oldTitle) {
        cancelRenameMode(topicGroupId, oldTitle);
        return;
    }

    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/rename`), {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ title: newTitle }),
        });

        const data = await response.json();

        if (data.success) {
            // Update current title if viewing this group
            if (currentTopicGroupId === topicGroupId) {
                titleInput.value = newTitle;
                autoResizeTextarea();
            }

            // Reload history list
            await loadHistory(currentSearchQuery, currentDateFilter);
        } else {
            alert('重命名失败：' + (data.error || '未知错误'));
            cancelRenameMode(topicGroupId, oldTitle);
        }
    } catch (error) {
        console.error('Failed to rename:', error);
        alert('重命名失败');
        cancelRenameMode(topicGroupId, oldTitle);
    }
}

/**
 * Cancel rename mode (restore old title)
 */
function cancelRenameMode(topicGroupId, oldTitle) {
    const topicItem = document.querySelector(`.topic-item[data-topic-group-id="${topicGroupId}"]`);
    if (!topicItem) return;

    const input = topicItem.querySelector('.topic-item-rename-input');
    if (!input) return;

    // Create span element
    const span = document.createElement('span');
    span.className = 'topic-title';
    span.textContent = oldTitle;

    // Replace input with span
    input.replaceWith(span);
}

/**
 * Show soft delete confirmation dialog (move to trash)
 */
function showSoftDeleteConfirmation(topicGroupId) {
    // Create modal
    const modal = document.createElement('div');
    modal.className = 'delete-confirm-modal show';
    modal.id = 'deleteConfirmModal';

    modal.innerHTML = `
        <div class="delete-confirm-content">
            <div class="delete-confirm-title">提示</div>
            <div class="delete-confirm-message">
                确认删除吗？<br>
                删除后的题目将会在废纸篓中保留。
            </div>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn delete-confirm-cancel">返回</button>
                <button class="delete-confirm-btn delete-confirm-delete" data-topic-group-id="${topicGroupId}">确认删除</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Add event handlers
    modal.querySelector('.delete-confirm-cancel').addEventListener('click', closeDeleteConfirmation);
    modal.querySelector('.delete-confirm-delete').addEventListener('click', handleSoftDeleteConfirm);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeDeleteConfirmation();
        }
    });
}

/**
 * Handle soft delete confirmation (move to trash)
 */
async function handleSoftDeleteConfirm(event) {
    const topicGroupId = event.currentTarget.dataset.topicGroupId;

    closeDeleteConfirmation();

    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/trash`), {
            method: 'POST',
        });

        const data = await response.json();

        if (data.success) {
            // If we're viewing the deleted group, reset to initial
            if (currentTopicGroupId === topicGroupId) {
                resetToInitial();
            }

            // Reload history list
            await loadHistory(currentSearchQuery, currentDateFilter);
        } else {
            alert('删除失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to delete:', error);
        alert('删除失败');
    }
}

/**
 * Handle permanent delete button click (in trash mode)
 */
function handlePermanentDeleteClick(event) {
    event.stopPropagation();

    const topicGroupId = event.currentTarget.dataset.topicGroupId;
    showPermanentDeleteConfirmation(topicGroupId);
}

/**
 * Show permanent delete confirmation dialog
 */
function showPermanentDeleteConfirmation(topicGroupId) {
    // Create modal
    const modal = document.createElement('div');
    modal.className = 'delete-confirm-modal show';
    modal.id = 'deleteConfirmModal';

    modal.innerHTML = `
        <div class="delete-confirm-content">
            <div class="delete-confirm-title">提示</div>
            <div class="delete-confirm-message">
                确认将此对话删除？<br>
                删除此对话后将无法找回历史记录。
            </div>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn delete-confirm-cancel">返回</button>
                <button class="delete-confirm-btn delete-confirm-delete" data-topic-group-id="${topicGroupId}">确认删除</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Add event handlers
    modal.querySelector('.delete-confirm-cancel').addEventListener('click', closeDeleteConfirmation);
    modal.querySelector('.delete-confirm-delete').addEventListener('click', handlePermanentDeleteConfirm);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeDeleteConfirmation();
        }
    });
}

/**
 * Handle permanent delete confirmation
 */
async function handlePermanentDeleteConfirm(event) {
    const topicGroupId = event.currentTarget.dataset.topicGroupId;

    closeDeleteConfirmation();

    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/permanent`), {
            method: 'DELETE',
        });

        const data = await response.json();

        if (data.success) {
            // Reload trash list
            await loadTrash(currentSearchQuery);
        } else {
            alert('删除失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to permanently delete:', error);
        alert('删除失败');
    }
}

/**
 * Show delete confirmation dialog (legacy - for backward compatibility)
 */
function showDeleteConfirmation(historyId) {
    // Create modal
    const modal = document.createElement('div');
    modal.className = 'delete-confirm-modal show';
    modal.id = 'deleteConfirmModal';

    modal.innerHTML = `
        <div class="delete-confirm-content">
            <div class="delete-confirm-title">提示</div>
            <div class="delete-confirm-message">
                确认将此对话删除？<br>
                删除此对话后将无法找回历史记录。
            </div>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn delete-confirm-cancel">返回</button>
                <button class="delete-confirm-btn delete-confirm-delete" data-history-id="${historyId}">确认删除</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Add event handlers
    modal.querySelector('.delete-confirm-cancel').addEventListener('click', closeDeleteConfirmation);
    modal.querySelector('.delete-confirm-delete').addEventListener('click', handleDeleteConfirm);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeDeleteConfirmation();
        }
    });
}

/**
 * Close delete confirmation dialog
 */
function closeDeleteConfirmation() {
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.remove();
    }
}

/**
 * Handle delete confirmation
 */
async function handleDeleteConfirm(event) {
    const historyId = parseInt(event.currentTarget.dataset.historyId);

    closeDeleteConfirmation();

    try {
        const response = await fetch(apiUrl(`/history/${historyId}`), {
            method: 'DELETE',
        });

        const data = await response.json();

        if (data.success) {
            // If we're viewing the deleted item, reset to initial
            if (currentHistoryId === historyId) {
                resetToInitial();
            }

            // Reload history list
            await loadHistory();
        } else {
            alert('删除失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to delete history:', error);
        alert('删除失败');
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Parse prompt into sections for Preview mode
 */
function parsePromptSections(rawText) {
    const sections = {};
    let currentSection = null;
    let currentContent = [];

    const lines = rawText.split('\n');

    for (const line of lines) {
        if (line.startsWith('## ')) {
            // Save previous section
            if (currentSection) {
                sections[currentSection] = currentContent.join('\n').trim();
            }
            // Start new section
            currentSection = line.substring(3).trim();
            currentContent = [];
        } else if (line.startsWith('# ')) {
            // Top-level header
            if (currentSection) {
                sections[currentSection] = currentContent.join('\n').trim();
            }
            currentSection = line.substring(2).trim();
            currentContent = [];
        } else {
            currentContent.push(line);
        }
    }

    // Save last section
    if (currentSection) {
        sections[currentSection] = currentContent.join('\n').trim();
    }

    return sections;
}

/**
 * Generate preview HTML from parsed sections
 */
function generatePreviewHTML(sections) {
    let html = '';

    // Basic Info
    html += '<div class="preview-section">';
    html += '<h4 class="preview-section-title">BASIC INFO</h4>';
    const basicFields = ['Title', 'Topic', 'Target platform', 'Target audience', 'Video length', 'Core concept'];
    for (const field of basicFields) {
        if (sections[field]) {
            html += `<div class="preview-field"><span class="preview-label">${field}:</span> ${escapeHtml(sections[field])}</div>`;
        }
    }
    html += '</div>';

    // Problem & Answer
    html += '<div class="preview-section">';
    html += '<h4 class="preview-section-title">PROBLEM & ANSWER</h4>';
    const problemFields = ['Puzzle setup', 'Question', 'Correct answer', 'Wrong intuition'];
    for (const field of problemFields) {
        if (sections[field]) {
            html += `<div class="preview-field"><span class="preview-label">${field}:</span><div class="preview-value">${escapeHtml(sections[field]).replace(/\n/g, '<br>')}</div></div>`;
        }
    }
    html += '</div>';

    // Reasoning
    if (sections['Reasoning']) {
        html += '<div class="preview-section">';
        html += '<h4 class="preview-section-title">REASONING</h4>';
        html += `<div class="preview-value">${escapeHtml(sections['Reasoning']).replace(/\n/g, '<br>')}</div>`;
        html += '</div>';
    }

    // Production
    html += '<div class="preview-section">';
    html += '<h4 class="preview-section-title">PRODUCTION PLAN</h4>';
    const productionFields = ['Narration Script', 'On-screen text', 'Visual style'];
    for (const field of productionFields) {
        if (sections[field]) {
            html += `<div class="preview-field"><span class="preview-label">${field}:</span><div class="preview-value">${escapeHtml(sections[field]).replace(/\n/g, '<br>')}</div></div>`;
        }
    }
    html += '</div>';

    // Requirements
    if (sections['Important requirements']) {
        html += '<div class="preview-section">';
        html += '<h4 class="preview-section-title">REQUIREMENTS</h4>';
        html += `<div class="preview-value">${escapeHtml(sections['Important requirements']).replace(/\n/g, '<br>')}</div>`;
        html += '</div>';
    }

    return html;
}

/**
 * Generate fallback overview text
 */
function generateFallbackOverview(title, coreConcept = null) {
    if (coreConcept) {
        return `这个视频围绕「${title}」展开，核心概念是「${coreConcept}」。内容会先提出一个反直觉问题，再通过分步推理解释答案。画面上将使用白底线稿和大号英文字幕，帮助观众理解关键逻辑。`;
    } else {
        return `这个视频围绕「${title}」展开。内容会先提出一个适合短视频传播的问题，再通过分步推理解释答案。画面上将使用白底线稿和大号英文字幕，帮助观众理解关键逻辑。`;
    }
}

/**
 * Render current prompt view based on currentPromptViewMode
 * CRITICAL: This is the ONLY function that should hydrate view content
 */
function renderCurrentPromptView() {
    const mode = currentPromptViewMode;

    // Get DOM elements
    const rawEl = document.getElementById('prompt-content');
    const previewEl = document.getElementById('prompt-preview');
    const overviewEl = document.getElementById('prompt-overview');
    const reviewEl = document.getElementById('prompt-review');
    const videoEl = document.getElementById('prompt-video');
    const webCopyEl = document.getElementById('prompt-web-copy');

    // Update title
    // v0.5.1.2: Video Mode uses "Educational Video" / "Video Output" framing
    // for video-related tabs to make the mode contextually clear.
    const titleEl = document.getElementById('prompt-view-title');
    if (mode === 'raw') {
        titleEl.textContent = currentAppMode === 'video' ? 'Educational Video' : 'NotebookLM Prompt';
    } else if (mode === 'preview') {
        titleEl.textContent = 'Prompt Preview';
    } else if (mode === 'overview') {
        titleEl.textContent = 'Content Overview';
    } else if (mode === 'review') {
        titleEl.textContent = 'AI Review';
    } else if (mode === 'video') {
        titleEl.textContent = 'Video Output';
    } else if (mode === 'web_copy') {
        titleEl.textContent = 'Web Copy';
    }

    // Update active button
    document.querySelectorAll('.view-mode-btn').forEach(btn => {
        if (btn.dataset.mode === mode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // v0.5.1.2: Reflect Video tab unavailability on Edit / Copy / Download buttons.
    // The buttons stay visible but render as disabled with explanatory tooltips.
    updateActionButtonsForCurrentView();

    // Hide all panels first, then show the active one. Keeps the v0.4.10
    // contract: only one panel visible at a time, and Raw textarea is the
    // only place that holds the clean Prompt text.
    rawEl.classList.add('hidden');
    previewEl.classList.add('hidden');
    overviewEl.classList.add('hidden');
    reviewEl.classList.add('hidden');
    if (videoEl) videoEl.classList.add('hidden');
    if (webCopyEl) webCopyEl.classList.add('hidden');

    if (mode === 'raw') {
        // CRITICAL: Always hydrate from currentRawText
        rawEl.value = currentRawText || '';
        rawEl.setAttribute('readonly', 'readonly');
        rawEl.classList.remove('editing');
        rawEl.classList.remove('hidden');

    } else if (mode === 'preview') {
        previewEl.innerHTML = currentPreviewText || '';
        previewEl.classList.remove('hidden');

    } else if (mode === 'overview') {
        let overviewHTML = `<div class="overview-content">${escapeHtml(currentOverviewText || '').replace(/\n/g, '<br>')}</div>`;
        if (currentChangeSummaryText) {
            overviewHTML += `
                <div class="change-summary-section">
                    <h4 class="change-summary-title">本次生成新增或改动的内容</h4>
                    <div class="change-summary-content">${escapeHtml(currentChangeSummaryText).replace(/\n/g, '<br>')}</div>
                </div>
            `;
        }
        if (currentAppMode === 'video') {
            overviewHTML += renderProviderContractSummaryHTML({ id: currentHistoryId });
        }
        overviewEl.innerHTML = overviewHTML;
        overviewEl.classList.remove('hidden');
        if (currentAppMode === 'video' && currentHistoryId != null) {
            refreshProviderContractSummary(currentHistoryId);
        }

    } else if (mode === 'review') {
        reviewEl.classList.remove('hidden');
        if (!currentReviewData) {
            loadReview();
        }

    } else if (mode === 'video' && videoEl) {
        // v0.5.1: framework-only video panel. No real video URL is ever set.
        videoEl.classList.remove('hidden');

    } else if (mode === 'web_copy' && webCopyEl) {
        // v0.5.1.2: hydrate Web Copy from currentWebCopyText. Empty-state placeholder
        // shows only when no web copy is present; otherwise show plain content view.
        webCopyEl.classList.remove('hidden');
        const emptyEl = document.getElementById('web-copy-empty-state');
        const contentEl = document.getElementById('web-copy-content');
        const textareaEl = document.getElementById('web-copy-edit-textarea');
        if (textareaEl) textareaEl.classList.add('hidden');
        const hasText = !!(currentWebCopyText && String(currentWebCopyText).trim());
        if (contentEl) {
            if (hasText) {
                contentEl.textContent = currentWebCopyText;
                contentEl.classList.remove('hidden');
            } else {
                contentEl.textContent = '';
                contentEl.classList.add('hidden');
            }
        }
        if (emptyEl) {
            if (hasText) {
                emptyEl.classList.add('hidden');
            } else {
                emptyEl.classList.remove('hidden');
            }
        }
    }
}

/**
 * Switch prompt view mode
 * SIMPLIFIED: Only do 3 things - check editing, set mode, render
 */
function switchPromptViewMode(mode) {
    // Step 1: Check if editing
    if (isEditingPrompt) {
        alert('You are currently editing. Please save or cancel your changes before switching tabs.');
        return;
    }

    // Step 2: Set mode
    currentPromptViewMode = mode;

    // Step 3: Render
    renderCurrentPromptView();
}

// ============================================================
// v0.5.3 - Video Mode multi-stage progress + Video Job status panel
// ============================================================

/**
 * Visual stages for Video Mode generation. The actual /api/video/generate
 * call is synchronous on the backend, so the UI advances through these
 * stages on a timer to give the user visible feedback. The final stage
 * resolves based on the real response (either provider_not_configured or
 * an error). Indices correspond to the rendered list.
 */
const VIDEO_GENERATION_STEPS = [
    { key: 'analyzing_topic', label: 'Analyzing topic' },
    { key: 'verifying_answer', label: 'Verifying answer' },
    { key: 'writing_video_script', label: 'Writing video script' },
    { key: 'building_storyboard', label: 'Building storyboard' },
    { key: 'creating_provider_prompt', label: 'Creating provider prompt' },
    { key: 'preparing_provider_request', label: 'Preparing provider request' },
    { key: 'creating_mock_video_job', label: 'Creating mock video job' },
    { key: 'saving_assets', label: 'Saving assets' },
    { key: 'completed', label: 'Done' },
];

let _videoProgressTimer = null;
let _videoProgressIndex = 0;

// v0.5.5 — Render the Provider Contract Summary block shown at the bottom
// of the Overview tab in Video Mode. Initial render uses static defaults
// (no real API call ever happens in v0.5.5); refreshProviderContractSummary
// can fetch the on-disk validation result lazily.
function renderProviderContractSummaryHTML(item) {
    const slot = `<div id="provider-contract-summary" class="provider-contract-summary"
        data-history-id="${(item && item.id != null) ? String(item.id) : ''}">
        <h4 class="provider-contract-title">Provider Contract</h4>
        <ul class="provider-contract-list">
            <li><strong>Future Provider:</strong> Seedance</li>
            <li><strong>Contract Status:</strong> <span data-field="contract-status">Loading…</span></li>
            <li><strong>Seedance Prompt Compiler:</strong> <span data-field="prompt-compiler-status">Loading…</span></li>
            <li><strong>Real API Call:</strong> Disabled until v0.6.0</li>
            <li><strong>Real Video Generated:</strong> No</li>
        </ul>
    </div>`;
    return slot;
}

function refreshProviderContractSummary(historyId) {
    if (historyId == null) return;
    fetch(`/api/video/history/${historyId}/provider-contract`)
        .then(r => r.ok ? r.json() : null)
        .then(payload => {
            if (!payload || !payload.success) return;
            const el = document.getElementById('provider-contract-summary');
            if (!el) return;
            const expected = el.getAttribute('data-history-id');
            if (expected && String(historyId) !== expected) return;
            const statusEl = el.querySelector('[data-field="contract-status"]');
            if (statusEl) {
                statusEl.textContent = payload.contract_ready ? 'Ready' : 'Validation Failed';
            }
            const compilerEl = el.querySelector('[data-field="prompt-compiler-status"]');
            if (compilerEl) {
                compilerEl.textContent = payload.prompt_compiler_ready ? 'Ready' : 'Not Available';
            }
        })
        .catch(() => {});
}

function _videoProgressEls() {
    return {
        panel: document.getElementById('video-progress-panel'),
        list: document.getElementById('video-progress-list'),
        message: document.getElementById('video-progress-message'),
        spinner: document.getElementById('loading-spinner'),
        loadingText: document.getElementById('loading-text'),
    };
}

function _renderVideoProgressList(currentIdx, finalState) {
    const { list } = _videoProgressEls();
    if (!list) return;
    const html = VIDEO_GENERATION_STEPS.map((step, idx) => {
        let cls = 'pending';
        if (finalState === 'failed' && idx === currentIdx) {
            cls = 'failed';
        } else if (finalState === 'not-configured' && idx === VIDEO_GENERATION_STEPS.length - 1) {
            cls = 'not-configured';
        } else if (idx < currentIdx) {
            cls = 'done';
        } else if (idx === currentIdx) {
            cls = 'active';
        }
        return `<li class="video-progress-step ${cls}" data-step="${step.key}">
            <span class="video-progress-step-marker"></span>
            <span class="video-progress-step-label">${step.label}</span>
        </li>`;
    }).join('');
    list.innerHTML = html;
}

function startVideoGenerationProgress() {
    const { panel, message, spinner, loadingText } = _videoProgressEls();
    if (!panel) return;
    panel.removeAttribute('hidden');
    panel.classList.remove('hidden');
    if (spinner) spinner.classList.add('hidden');
    if (loadingText) loadingText.textContent = 'Generating your video assets...';
    _videoProgressIndex = 0;
    _renderVideoProgressList(0, null);
    if (message) message.textContent = VIDEO_GENERATION_STEPS[0].label + '...';
    if (_videoProgressTimer) clearInterval(_videoProgressTimer);
    _videoProgressTimer = setInterval(advanceVideoGenerationProgress, 1500);
}

function advanceVideoGenerationProgress() {
    // Auto-advance up to but not including the final 'saving_assets' step;
    // completion / failure is driven by the actual API response.
    const ceiling = VIDEO_GENERATION_STEPS.length - 2;
    if (_videoProgressIndex < ceiling) {
        _videoProgressIndex += 1;
        _renderVideoProgressList(_videoProgressIndex, null);
        const { message } = _videoProgressEls();
        if (message) message.textContent = VIDEO_GENERATION_STEPS[_videoProgressIndex].label + '...';
    }
}

function completeVideoGenerationProgress(videoJob) {
    if (_videoProgressTimer) {
        clearInterval(_videoProgressTimer);
        _videoProgressTimer = null;
    }
    const finalState = (videoJob && videoJob.status === 'provider_not_configured') ? 'not-configured' : null;
    _videoProgressIndex = VIDEO_GENERATION_STEPS.length - 1;
    _renderVideoProgressList(_videoProgressIndex, finalState);
    const { message } = _videoProgressEls();
    if (message) {
        if (videoJob && videoJob.status === 'provider_not_configured') {
            message.textContent = 'Seedance prompt compiler + contract adapter are ready. Content assets, compiled Seedance prompt, and payload preview were generated, but no real video API was called. Real Seedance provider calls are reserved for v0.6.0.';
        } else if (videoJob && videoJob.error_message) {
            message.textContent = videoJob.error_message;
        } else {
            message.textContent = 'Done.';
        }
    }
}

function failVideoGenerationProgress(errorText) {
    if (_videoProgressTimer) {
        clearInterval(_videoProgressTimer);
        _videoProgressTimer = null;
    }
    _renderVideoProgressList(_videoProgressIndex, 'failed');
    const { message } = _videoProgressEls();
    if (message) message.textContent = errorText || 'Video generation failed.';
}

function resetVideoGenerationProgress() {
    if (_videoProgressTimer) {
        clearInterval(_videoProgressTimer);
        _videoProgressTimer = null;
    }
    _videoProgressIndex = 0;
    const { panel, list, message, spinner } = _videoProgressEls();
    if (panel) {
        panel.classList.add('hidden');
        panel.setAttribute('hidden', '');
    }
    if (list) list.innerHTML = '';
    if (message) message.textContent = '';
    if (spinner) spinner.classList.remove('hidden');
}

/**
 * v0.5.3 — Render the Video Job status panel inside the Video tab. Pass
 * null to clear/hide. Safe to call when the panel DOM doesn't exist yet
 * (Prompt Mode page render).
 */
function renderVideoJobStatus(job) {
    const panel = document.getElementById('video-job-status-panel');
    if (!panel) return;
    if (!job) {
        panel.classList.add('hidden');
        panel.setAttribute('hidden', '');
        return;
    }
    panel.classList.remove('hidden');
    panel.removeAttribute('hidden');

    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = (value === null || value === undefined || value === '') ? '—' : String(value);
    };
    const pill = document.getElementById('video-job-status-pill');
    if (pill) {
        pill.textContent = job.status || 'unknown';
        pill.dataset.status = job.status || '';
    }
    setText('video-job-stage', job.stage);
    setText('video-job-provider', job.provider);
    const progressVal = (job.progress === null || job.progress === undefined) ? null : `${job.progress}%`;
    setText('video-job-progress', progressVal);
    setText('video-job-provider-id', job.provider_job_id);
    setText('video-job-updated', job.updated_at || job.completed_at || job.submitted_at || job.created_at);

    const msgEl = document.getElementById('video-job-message');
    if (msgEl) {
        if (job.message) {
            msgEl.textContent = job.message;
        } else if (job.status === 'provider_not_configured') {
            msgEl.textContent = 'Seedance prompt compiler + contract adapter are ready. Content assets, compiled Seedance prompt, and payload preview were generated, but no real video API was called. Real Seedance provider calls are reserved for v0.6.0.';
        } else if (job.error_message) {
            msgEl.textContent = job.error_message;
        } else {
            msgEl.textContent = '';
        }
    }
}

/**
 * Trigger prompt generation
 */
async function triggerGenerate() {
    if (isGenerating) {
        return;
    }

    const title = titleInput.value.trim();

    if (!title) {
        alert('请输入视频题目');
        titleInput.focus();
        return;
    }

    // Show loading
    isGenerating = true;
    generateBtn.disabled = true;
    titleInput.disabled = true;
    // v0.5.1.2: mode-aware loading copy
    const loadingTextEl = document.getElementById('loading-text');
    if (loadingTextEl) {
        loadingTextEl.textContent = currentAppMode === 'video'
            ? 'Generating your video assets...'
            : 'Generating your prompt...';
    }
    showSection(loadingSection);

    // v0.5.3: in Video Mode, replace the simple spinner with a multi-stage
    // progress panel. Prompt Mode keeps the existing spinner.
    if (currentAppMode === 'video') {
        startVideoGenerationProgress();
    } else {
        resetVideoGenerationProgress();
    }

    try {
        const generateEndpoint = currentAppMode === 'video' ? '/api/video/generate' : '/api/generate';
        const response = await fetch(generateEndpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ title }),
        });

        const data = await response.json();

        if (data.success) {
            // Update current state
            currentSlug = data.slug || 'notebooklm_prompt';
            currentHistoryId = data.history_id || data.id || null;
            currentTopicGroupId = data.topic_group_id || null;
            currentVersionNumber = data.version_number || 1;
            // v0.5.3: capture the auto-created Mock VideoJob (if any) so the
            // Video tab can show the status panel after we transition to the
            // result section.
            currentVideoJob = data.video_job || null;
            if (currentAppMode === 'video') {
                completeVideoGenerationProgress(currentVideoJob);
            }
            renderVideoJobStatus(currentVideoJob);

            // Update prompt view state. In Video Mode v0.5.4 the backend sets
            // `prompt` to the provider_prompt produced by the Video Content
            // Asset Pipeline; in Prompt Mode it remains the NotebookLM prompt.
            currentRawText = data.prompt || '';

            // Generate preview. v0.5.4: in Video Mode prefer the
            // pipeline-rendered preview_text (script + storyboard) directly,
            // since the provider_prompt no longer follows NotebookLM section
            // headings that parsePromptSections expects.
            if (currentAppMode === 'video' && data.preview_text) {
                currentPreviewText = `<div class="preview-content">${escapeHtml(data.preview_text).replace(/\n/g, '<br>')}</div>`;
            } else {
                try {
                    const sections = parsePromptSections(currentRawText);
                    currentPreviewText = generatePreviewHTML(sections);
                } catch (error) {
                    console.error('Failed to generate preview:', error);
                    currentPreviewText = '<div class="preview-error">Preview generation failed. See Raw Text for full content.</div>';
                }
            }

            // Get or generate overview
            currentOverviewText = data.overview_cn || generateFallbackOverview(title);
            currentChangeSummaryText = ''; // First generation has no change summary

            // Show success
            resultSlug.textContent = data.slug;
            resultDir.textContent = data.output_dir;
            promptContent.value = currentRawText;
            document.getElementById('prompt-preview').innerHTML = currentPreviewText;

            // Update overview (no change summary for first generation)
            let overviewHTML = `<div class="overview-content">${escapeHtml(currentOverviewText).replace(/\n/g, '<br>')}</div>`;
            document.getElementById('prompt-overview').innerHTML = overviewHTML;

            // v0.5.1.2: Video Mode lands on Video tab; Prompt Mode keeps Raw Text.
            switchPromptViewMode(getDefaultViewMode());

            showSection(resultSection);

            // Load and show version selector (show Version 1 for new generation)
            if (currentTopicGroupId && currentHistoryId) {
                await loadAndShowVersionSelector(currentTopicGroupId, currentHistoryId);
            }

            // Reload history list to show new item
            loadHistory(currentSearchQuery, currentDateFilter);

            // Scroll to result
            setTimeout(() => {
                resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        } else {
            // Show error
            errorMessage.textContent = data.error || '未知错误';

            // Show detailed error if available
            if (data.stdout || data.stderr) {
                errorDetails.classList.remove('hidden');
                errorStdout.textContent = data.stdout
                    ? `STDOUT:\n${data.stdout}`
                    : '';
                errorStderr.textContent = data.stderr
                    ? `STDERR:\n${data.stderr}`
                    : '';
            } else {
                errorDetails.classList.add('hidden');
            }

            if (currentAppMode === 'video') {
                failVideoGenerationProgress(data.error || 'Video generation failed.');
            }
            showSection(errorSection);
        }
    } catch (error) {
        // Network or other error
        errorMessage.textContent = `请求失败: ${error.message}`;
        errorDetails.classList.add('hidden');
        if (currentAppMode === 'video') {
            failVideoGenerationProgress(`Request failed: ${error.message}`);
        }
        showSection(errorSection);
    } finally {
        // Reset state
        isGenerating = false;
        generateBtn.disabled = false;
        titleInput.disabled = false;
    }
}

/**
 * Copy prompt to clipboard
 */
/**
 * Build the plain-text payload that Overview Copy/Download should emit.
 *
 * The Overview tab visually concatenates the overview body with a
 * "本次生成新增或改动的内容" (change_summary_cn) section for regenerated
 * versions. Copy/Download should match that, but Raw Text must NEVER
 * be polluted with this concatenation — Raw Text stays the clean
 * NotebookLM-ready prompt.
 */
function getOverviewPlainText() {
    const overview = (typeof currentOverviewText === 'string' ? currentOverviewText : '') || '';
    const changeSummary = (typeof currentChangeSummaryText === 'string' ? currentChangeSummaryText : '') || '';

    const overviewTrimmed = overview.replace(/\s+$/u, '');
    if (!changeSummary.trim()) {
        return overviewTrimmed;
    }

    const header = '本次生成新增或改动的内容';
    const parts = [];
    if (overviewTrimmed) {
        parts.push(overviewTrimmed);
    }
    parts.push(header);
    parts.push(changeSummary.replace(/^\s+|\s+$/gu, ''));
    return parts.join('\n\n');
}

/**
 * v0.5.1.2 UI hotfix round 2: return Web Copy text suitable for Copy/Download.
 *
 * If currentWebCopyText is non-empty, return it as-is. Otherwise fall back to
 * the placeholder copy shown in the Web Copy tab so that Download still
 * produces a usable web_copy.txt and Copy still has something to put on the
 * clipboard. Keep this string in sync with the empty-state placeholder
 * rendered by switchPromptView() for the 'web_copy' branch.
 */
function getWebCopyPlainText() {
    const text = (typeof currentWebCopyText === 'string' ? currentWebCopyText : '') || '';
    if (text.trim()) return text;
    return [
        'Web Copy is not generated yet.',
        '',
        'This tab will later contain YouTube/TikTok titles, descriptions, captions, and posting copy.'
    ].join('\n');
}

async function copyPrompt() {
    let text = '';

    // Get text based on current view mode
    if (currentPromptViewMode === 'raw') {
        text = currentRawText;
    } else if (currentPromptViewMode === 'preview') {
        // Get plain text from preview HTML
        const previewEl = document.getElementById('prompt-preview');
        text = previewEl.innerText || previewEl.textContent;
    } else if (currentPromptViewMode === 'overview') {
        text = getOverviewPlainText();
    } else if (currentPromptViewMode === 'review') {
        // AI Review tab: copy the markdown summary if a review is loaded.
        if (!currentReviewData || typeof getReviewContent !== 'function') {
            alert('AI Review has not been generated yet. Click Re-review to generate one before copying.');
            return;
        }
        text = getReviewContent();
    } else if (currentPromptViewMode === 'web_copy') {
        text = getWebCopyPlainText();
    } else if (currentPromptViewMode === 'video') {
        // v0.5.1.2 hotfix: video tab cannot be copied. Read tooltip text
        // from data-unavailable-message so the toast string matches the
        // hover tooltip exactly.
        const copyBtnEl = document.getElementById('copy-btn');
        const msg = (copyBtnEl && copyBtnEl.getAttribute('data-unavailable-message'))
            || 'Video content cannot be copied.';
        if (typeof showAppToast === 'function') {
            showAppToast(msg);
        } else {
            alert(msg);
        }
        return;
    }

    if (!text || !String(text).trim()) {
        alert('There is nothing to copy yet for this view.');
        return;
    }

    try {
        await navigator.clipboard.writeText(text);

        // Visual feedback
        copyBtn.classList.add('copied');
        const tooltip = copyBtn.querySelector('.icon-tooltip');
        if (tooltip) {
            const originalText = tooltip.textContent;
            tooltip.textContent = 'Copied!';
            // Refresh global tooltip so the swapped label shows immediately
            // if the user is still hovering the Copy button.
            if (typeof refreshActiveGlobalIconTooltip === 'function') {
                refreshActiveGlobalIconTooltip();
            }
            setTimeout(() => {
                copyBtn.classList.remove('copied');
                tooltip.textContent = originalText;
                if (typeof refreshActiveGlobalIconTooltip === 'function') {
                    refreshActiveGlobalIconTooltip();
                }
            }, 1500);
        }
    } catch (error) {
        alert('复制失败，请手动选择文本复制');
    }
}

/**
 * Download prompt as .txt file
 */
function downloadPrompt() {
    let text = '';
    let filenameSuffix = '';
    let extension = 'txt';
    let mimeType = 'text/plain;charset=utf-8';

    // Get text and filename based on current view mode
    if (currentPromptViewMode === 'raw') {
        text = currentRawText;
        filenameSuffix = 'raw_text';
    } else if (currentPromptViewMode === 'preview') {
        // Get plain text from preview HTML
        const previewEl = document.getElementById('prompt-preview');
        text = previewEl.innerText || previewEl.textContent;
        filenameSuffix = 'preview';
    } else if (currentPromptViewMode === 'overview') {
        text = getOverviewPlainText();
        filenameSuffix = 'overview';
    } else if (currentPromptViewMode === 'review') {
        if (!currentReviewData || typeof getReviewContent !== 'function') {
            alert('AI Review has not been generated yet. Click Re-review to generate one before downloading.');
            return;
        }
        text = getReviewContent();
        filenameSuffix = 'ai_review';
        extension = 'md';
        mimeType = 'text/markdown;charset=utf-8';
    } else if (currentPromptViewMode === 'web_copy') {
        text = getWebCopyPlainText();
        filenameSuffix = 'web_copy';
    } else if (currentPromptViewMode === 'video') {
        // v0.5.1.2 hotfix: video tab has no downloadable file yet. Read
        // tooltip text from data-unavailable-message so the toast string
        // matches the hover tooltip exactly.
        const downloadBtnEl = document.getElementById('download-btn');
        const msg = (downloadBtnEl && downloadBtnEl.getAttribute('data-unavailable-message'))
            || 'Video file is not available yet. Download will be available when a video file exists.';
        if (typeof showAppToast === 'function') {
            showAppToast(msg);
        } else {
            alert(msg);
        }
        return;
    }

    if (!text || !String(text).trim()) {
        return;
    }

    // Sanitize slug for filename
    const slug = currentSlug || currentHistoryId || 'prompt';
    const safeSlug = String(slug)
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '_')
        .replace(/^_+|_+$/g, '') || 'prompt';

    // Build a timestamp suffix for AI Review files so users can keep
    // multiple review snapshots without overwriting.
    let stampedSuffix = filenameSuffix;
    if (currentPromptViewMode === 'review') {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
        stampedSuffix = `${filenameSuffix}_${ts}`;
    }

    // Create blob and download
    const blob = new Blob([text], { type: mimeType });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = `${safeSlug}_${stampedSuffix}.${extension}`;
    document.body.appendChild(link);
    link.click();

    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/**
 * Reset to initial state (New Chat)
 */
function resetToInitial() {
    // CRITICAL: Block New Chat while editing
    if (isEditingPrompt) {
        alert('You are currently editing. Please save or cancel your changes before starting a new chat.');
        return;
    }

    titleInput.value = '';
    titleInput.style.height = 'auto';
    currentSlug = '';
    currentHistoryId = null;
    currentTopicGroupId = null;
    currentVersionNumber = null;
    titleInput.focus();
    document.body.classList.remove('has-result', 'has-loading', 'has-error');
    showSection(initialSection);

    // Hide version selector
    hideVersionSelector();

    // Re-render history list to clear active state
    if (currentMode === 'history' && historyItems.length > 0) {
        renderHistoryList(historyItems);
    }

    // Scroll to top
    const mainContent = document.querySelector('.main-content');
    if (mainContent) {
        mainContent.scrollTop = 0;
    }
}

/**
 * Switch to trash mode
 */
function switchToTrashMode() {
    currentMode = 'trash';

    // Update title
    const topicsTitle = document.querySelector('.topics-title');
    if (topicsTitle) {
        topicsTitle.textContent = 'TRASH';
    }

    // Hide action buttons, show back button
    const topicsActions = document.querySelector('.topics-actions');
    if (topicsActions) {
        topicsActions.innerHTML = `
            <button class="topics-back-btn" id="backToHistoryBtn">← Recent</button>
        `;

        document.getElementById('backToHistoryBtn').addEventListener('click', switchToHistoryMode);
    }

    // Load and render trash
    loadTrash(currentSearchQuery);
}

/**
 * Switch to history mode
 */
function switchToHistoryMode() {
    currentMode = 'history';

    // Update title
    const topicsTitle = document.querySelector('.topics-title');
    if (topicsTitle) {
        topicsTitle.textContent = 'RECENT TOPICS';
    }

    // Show action buttons, hide back button
    const topicsActions = document.querySelector('.topics-actions');
    if (topicsActions) {
        topicsActions.innerHTML = `
            <button class="topics-action-btn" id="favoriteBtn" data-tooltip="Favorites">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
            </button>
            <button class="topics-action-btn" id="dateFilterBtn" data-tooltip="Filter by date">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                    <line x1="16" y1="2" x2="16" y2="6"/>
                    <line x1="8" y1="2" x2="8" y2="6"/>
                    <line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
            </button>
            <button class="topics-action-btn" id="trashBtn" data-tooltip="Trash">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z"/>
                </svg>
            </button>
        `;

        // Re-attach event listeners
        document.getElementById('favoriteBtn').addEventListener('click', switchToFavoritesMode);
        document.getElementById('dateFilterBtn').addEventListener('click', showDateFilterDropdown);
        document.getElementById('trashBtn').addEventListener('click', switchToTrashMode);
    }

    // Load and render history
    loadHistory(currentSearchQuery, currentDateFilter);
}

/**
 * Switch to favorites mode
 */
function switchToFavoritesMode() {
    currentMode = 'favorites';

    // Update title
    const topicsTitle = document.querySelector('.topics-title');
    if (topicsTitle) {
        topicsTitle.textContent = 'FAVORITES';
    }

    // Hide action buttons, show back button
    const topicsActions = document.querySelector('.topics-actions');
    if (topicsActions) {
        topicsActions.innerHTML = `
            <button class="topics-back-btn" id="backToHistoryBtn">← Recent</button>
        `;

        document.getElementById('backToHistoryBtn').addEventListener('click', switchToHistoryMode);
    }

    // Load and render favorites
    loadFavorites(currentSearchQuery);
}

/**
 * Show date filter dropdown
 */
function showDateFilterDropdown(event) {
    event.stopPropagation();

    // Close any existing dropdown
    closeDateFilterDropdown();

    const button = event.currentTarget;

    // Create dropdown
    const dropdown = document.createElement('div');
    dropdown.className = 'date-filter-dropdown show';
    dropdown.id = 'dateFilterDropdown';

    const filters = [
        { value: 'all', label: 'All' },
        { value: '1h', label: 'Past 1 hour' },
        { value: '3h', label: 'Past 3 hours' },
        { value: 'today', label: 'Today' },
        { value: 'yesterday', label: 'Yesterday' },
        { value: '7d', label: 'Previous 7 Days' },
        { value: '30d', label: 'Previous 30 Days' },
    ];

    dropdown.innerHTML = filters.map(filter => `
        <button class="date-filter-item ${filter.value === currentDateFilter ? 'selected' : ''}"
                data-filter="${filter.value}">
            ${filter.label}
        </button>
    `).join('');

    document.body.appendChild(dropdown);

    // Position dropdown
    const buttonRect = button.getBoundingClientRect();
    dropdown.style.top = `${buttonRect.bottom + 4}px`;
    dropdown.style.left = `${buttonRect.left}px`;

    // Add click handlers
    dropdown.querySelectorAll('.date-filter-item').forEach(item => {
        item.addEventListener('click', handleDateFilterSelect);
    });

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', closeDateFilterDropdownOnOutsideClick);
    }, 0);
}

/**
 * Handle date filter selection
 */
async function handleDateFilterSelect(event) {
    const filter = event.currentTarget.dataset.filter;

    currentDateFilter = filter;

    closeDateFilterDropdown();

    // Reload history with new filter
    await loadHistory(currentSearchQuery, currentDateFilter);
}

/**
 * Close date filter dropdown
 */
function closeDateFilterDropdown() {
    const dropdown = document.getElementById('dateFilterDropdown');
    if (dropdown) {
        dropdown.remove();
        document.removeEventListener('click', closeDateFilterDropdownOnOutsideClick);
    }
}

/**
 * Close date filter dropdown on outside click
 */
function closeDateFilterDropdownOnOutsideClick(event) {
    const dropdown = document.getElementById('dateFilterDropdown');
    if (dropdown && !dropdown.contains(event.target)) {
        closeDateFilterDropdown();
    }
}

/**
 * Load and show version selector
 */
async function loadAndShowVersionSelector(topicGroupId, currentHistoryId) {
    try {
        const response = await fetch(apiUrl(`/history/group/${topicGroupId}/versions`));
        const data = await response.json();

        if (data.success && data.versions) {
            currentVersions = data.versions;
            renderVersionSelector(currentHistoryId);
        }
    } catch (error) {
        console.error('Failed to load versions:', error);
    }
}

/**
 * Render version selector
 */
function renderVersionSelector(selectedHistoryId) {
    let versionSelectorContainer = document.querySelector('.version-selector');

    // Create container if it doesn't exist
    if (!versionSelectorContainer) {
        versionSelectorContainer = document.createElement('div');
        versionSelectorContainer.className = 'version-selector';

        // Insert before prompt-view-modes in prompt-header-actions
        const promptViewModes = document.querySelector('.prompt-view-modes');
        if (promptViewModes) {
            promptViewModes.parentElement.insertBefore(versionSelectorContainer, promptViewModes);
        }
    }

    const selectedVersion = currentVersions.find(v => v.id === selectedHistoryId);
    const selectedVersionNumber = selectedVersion ? selectedVersion.version_number : 1;

    versionSelectorContainer.innerHTML = `
        <div class="version-dropdown">
            <button class="version-dropdown-toggle" id="versionDropdownToggle">
                Version ${selectedVersionNumber}
                <svg class="version-dropdown-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"/>
                </svg>
            </button>
            <div class="version-dropdown-menu" id="versionDropdownMenu">
                ${currentVersions.map(v => `
                    <div class="version-dropdown-item ${v.id === selectedHistoryId ? 'selected' : ''}"
                         data-history-id="${v.id}">
                        Version ${v.version_number}
                    </div>
                `).join('')}
            </div>
        </div>
    `;

    versionSelectorContainer.style.display = 'flex';

    // Add event listeners
    const toggle = document.getElementById('versionDropdownToggle');
    const menu = document.getElementById('versionDropdownMenu');

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('show');
    });

    menu.querySelectorAll('.version-dropdown-item').forEach(item => {
        item.addEventListener('click', handleVersionSelect);
    });

    // Close dropdown on outside click
    document.addEventListener('click', () => {
        menu.classList.remove('show');
    });
}

/**
 * Handle version selection
 */
async function handleVersionSelect(event) {
    const historyId = parseInt(event.currentTarget.dataset.historyId);

    if (!historyId || historyId === currentHistoryId) {
        return;
    }

    try {
        const response = await fetch(apiUrl(`/history/${historyId}`));
        const data = await response.json();

        if (data.success && data.item) {
            const item = data.item;

            // Render history record
            renderHistoryRecord(item);

            // Update current view display
            switchPromptViewMode(currentPromptViewMode);

            // Re-render version selector to update selected state
            renderVersionSelector(item.id);
        }
    } catch (error) {
        console.error('Failed to load version:', error);
    }
}

/**
 * Hide version selector
 */
function hideVersionSelector() {
    const versionSelector = document.querySelector('.version-selector');
    if (versionSelector) {
        versionSelector.style.display = 'none';
    }
}

/**
 * Download all prompt views as zip
 */
async function downloadAllPrompts() {
    if (!currentHistoryId) {
        alert('No prompt to download');
        return;
    }

    try {
        const response = await fetch(apiUrl(`/history/${currentHistoryId}/download-all`));

        if (!response.ok) {
            throw new Error('Download failed');
        }

        // Get filename from Content-Disposition header or use default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'prompt_package.zip';
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="?([^"]+)"?/);
            if (match) {
                filename = match[1];
            }
        }

        // Download the file
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();

        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Failed to download all:', error);
        alert('Download failed: ' + error.message);
    }
}

// Event Listeners
generateBtn.addEventListener('click', triggerGenerate);
newChatBtn.addEventListener('click', resetToInitial);
copyBtn.addEventListener('click', copyPrompt);
downloadBtn.addEventListener('click', downloadPrompt);

// View mode buttons
document.querySelectorAll('.view-mode-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const mode = e.currentTarget.dataset.mode;
        switchPromptViewMode(mode);
    });
});

// Download All button
const downloadAllBtn = document.getElementById('download-all-btn');
if (downloadAllBtn) {
    downloadAllBtn.addEventListener('click', downloadAllPrompts);
}

// Textarea auto-resize
titleInput.addEventListener('input', autoResizeTextarea);

// Enter to generate, Shift+Enter to newline
titleInput.addEventListener('keydown', (e) => {
    // Ignore if composing (IME input)
    if (e.isComposing) {
        return;
    }

    // Enter without Shift: trigger generation
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!isGenerating) {
            triggerGenerate();
        }
    }

    // Shift+Enter: allow default newline behavior
});

// Focus input on load
titleInput.focus();

// Search history with debounce
const searchInput = document.querySelector('.search-input');
if (searchInput) {
    searchInput.removeAttribute('readonly');
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        currentSearchQuery = query;
        searchTimeout = setTimeout(() => {
            if (currentMode === 'history') {
                loadHistory(query, currentDateFilter);
            } else if (currentMode === 'trash') {
                loadTrash(query);
            } else if (currentMode === 'favorites') {
                loadFavorites(query);
            }
        }, 200);
    });
}

// Load history on page load
window.addEventListener('DOMContentLoaded', () => {
    loadHistory();

    // v0.5.1.2 round 4: install the global tooltip portal once the DOM is
    // ready and bind every existing .icon-button to it. Subsequent calls
    // from updateActionButtonsForCurrentView()/enterEditMode/exitEditMode
    // pick up any new icon-buttons via dataset.globalTooltipBound guards.
    if (typeof ensureGlobalIconTooltip === 'function') {
        ensureGlobalIconTooltip();
    }
    if (typeof bindGlobalIconTooltips === 'function') {
        bindGlobalIconTooltips();
    }

    // Initialize action buttons
    const favoriteBtn = document.getElementById('favoriteBtn');
    const dateFilterBtn = document.getElementById('dateFilterBtn');
    const trashBtn = document.getElementById('trashBtn');

    if (favoriteBtn) {
        favoriteBtn.addEventListener('click', switchToFavoritesMode);
    }

    if (dateFilterBtn) {
        dateFilterBtn.addEventListener('click', showDateFilterDropdown);
    }

    if (trashBtn) {
        trashBtn.addEventListener('click', switchToTrashMode);
    }
});

// ============================================
// Theme Management
// ============================================

const THEME_KEY = 'ai-video-theme';
const THEMES = {
    LIGHT: 'light',
    DARK: 'dark'
};

/**
 * Get current theme from localStorage or default to light
 */
function getCurrentTheme() {
    return localStorage.getItem(THEME_KEY) || THEMES.LIGHT;
}

/**
 * Set theme
 */
function setTheme(theme) {
    const html = document.documentElement;
    const moonIcon = themeToggle.querySelector('.moon-icon');
    const sunIcon = themeToggle.querySelector('.sun-icon');

    if (theme === THEMES.DARK) {
        html.classList.add('dark-theme');
        moonIcon.classList.remove('active');
        sunIcon.classList.add('active');
        themeToggle.setAttribute('data-tooltip', 'Light mode');
        themeToggle.setAttribute('aria-label', 'Switch to light mode');
    } else {
        html.classList.remove('dark-theme');
        moonIcon.classList.add('active');
        sunIcon.classList.remove('active');
        themeToggle.setAttribute('data-tooltip', 'Dark mode');
        themeToggle.setAttribute('aria-label', 'Switch to dark mode');
    }

    localStorage.setItem(THEME_KEY, theme);
}

/**
 * Toggle theme
 */
function toggleTheme() {
    const currentTheme = getCurrentTheme();
    const newTheme = currentTheme === THEMES.LIGHT ? THEMES.DARK : THEMES.LIGHT;
    setTheme(newTheme);
}

// Initialize theme on page load
setTheme(getCurrentTheme());

// Theme toggle event listener
themeToggle.addEventListener('click', toggleTheme);

// ============================================
// Settings Modal
// ============================================

/**
 * Open settings modal
 */
function openSettingsModal() {
    settingsModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

/**
 * Close settings modal
 */
function closeSettingsModal() {
    settingsModal.classList.add('hidden');
    document.body.style.overflow = '';
}

/**
 * Switch settings panel
 */
function switchSettingsPanel(panelName) {
    // Hide all panels
    settingsPanels.forEach(panel => {
        panel.classList.add('hidden');
    });

    // Remove active from all nav items
    settingsNavItems.forEach(item => {
        item.classList.remove('active');
    });

    // Show selected panel
    const targetPanel = document.getElementById(`panel-${panelName}`);
    if (targetPanel) {
        targetPanel.classList.remove('hidden');
    }

    // Set active nav item
    const targetNavItem = document.querySelector(`[data-panel="${panelName}"]`);
    if (targetNavItem) {
        targetNavItem.classList.add('active');
    }
}

// Settings button click
settingsBtn.addEventListener('click', openSettingsModal);

// Close button click
if (settingsClose) {
    settingsClose.addEventListener('click', closeSettingsModal);
}

// Backdrop click
if (settingsBackdrop) {
    settingsBackdrop.addEventListener('click', closeSettingsModal);
}

// Esc key to close
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !settingsModal.classList.contains('hidden')) {
        closeSettingsModal();
    }
});

// Settings nav items click
settingsNavItems.forEach(item => {
    item.addEventListener('click', () => {
        const panelName = item.dataset.panel;
        if (panelName) {
            switchSettingsPanel(panelName);
        }
    });
});

// ============================================
// Edit and Regenerate Functions
// ============================================

/**
 * Enter edit mode for current view
 */
function enterEditMode() {
    if (isEditingPrompt) {
        return;
    }

    // CRITICAL: AI Review cannot be edited
    if (currentPromptViewMode === 'review') {
        alert('AI Review cannot be edited. Please switch to Raw Text, Preview, or Overview to edit.');
        return;
    }

    // v0.5.1.2: Video tab cannot be edited
    if (currentPromptViewMode === 'video') {
        if (typeof showAppToast === 'function') {
            showAppToast('Video tab cannot be edited.');
        } else {
            alert('Video tab cannot be edited.');
        }
        return;
    }

    // Only allow editing raw, preview, overview, or web_copy
    if (currentPromptViewMode !== 'raw' && currentPromptViewMode !== 'preview' && currentPromptViewMode !== 'overview' && currentPromptViewMode !== 'web_copy') {
        console.error('Invalid edit mode:', currentPromptViewMode);
        return;
    }

    // CRITICAL: Lock the editing view mode to prevent pollution
    editingViewMode = currentPromptViewMode;
    isEditingPrompt = true;

    // Get current view content
    let contentToEdit = '';
    if (editingViewMode === 'raw') {
        contentToEdit = currentRawText || '';
    } else if (editingViewMode === 'preview') {
        // Prefer the user-edited Preview text if it exists.
        // Otherwise fall back to the current rendered Preview so the
        // textarea is never blank on first edit.
        if (currentPreviewTextEdited && currentPreviewTextEdited.trim()) {
            contentToEdit = currentPreviewTextEdited;
        } else {
            const previewEl = document.getElementById('prompt-preview');
            const renderedText = previewEl
                ? (previewEl.innerText || previewEl.textContent || '')
                : '';
            contentToEdit = renderedText.trim();
            // Last-resort fallback: generate from the raw prompt directly.
            if (!contentToEdit && currentRawText) {
                try {
                    const sections = parsePromptSections(currentRawText);
                    const tmp = document.createElement('div');
                    tmp.innerHTML = generatePreviewHTML(sections);
                    contentToEdit = (tmp.innerText || tmp.textContent || '').trim();
                } catch (e) {
                    contentToEdit = currentRawText;
                }
            }
        }
    } else if (editingViewMode === 'overview') {
        contentToEdit = currentOverviewText || '';
    } else if (editingViewMode === 'web_copy') {
        contentToEdit = currentWebCopyText || '';
    }

    // CRITICAL: Store original content for cancel
    originalEditContent = contentToEdit;

    // Update edit button to save icon. innerHTML replacement is exclusive,
    // so the Save tooltip span exists exactly once.
    editBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
        </svg>
        <span class="icon-tooltip">Save</span>
    `;
    editBtn.classList.add('editing');
    // While saving, the button is active; clear any prior unavailable state.
    editBtn.removeAttribute('data-disabled');
    editBtn.removeAttribute('data-unavailable-message');
    if (editBtn.hasAttribute('title')) editBtn.removeAttribute('title');
    // Refresh global tooltip so it picks up the new "Save" label, and
    // bind the freshly-created Cancel button into the portal.
    if (typeof bindGlobalIconTooltips === 'function') bindGlobalIconTooltips();
    if (typeof refreshActiveGlobalIconTooltip === 'function') refreshActiveGlobalIconTooltip();

    // Add cancel button next to save button
    let cancelBtn = document.getElementById('cancel-edit-btn');
    if (!cancelBtn) {
        cancelBtn = document.createElement('button');
        cancelBtn.id = 'cancel-edit-btn';
        cancelBtn.className = 'icon-button cancel-edit-button';
        cancelBtn.setAttribute('aria-label', 'Cancel');
        cancelBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span class="icon-tooltip">Cancel</span>
        `;
        cancelBtn.onclick = cancelEditMode;
        // Insert after editBtn
        editBtn.parentElement.insertBefore(cancelBtn, editBtn.nextSibling);
    }
    cancelBtn.style.display = 'inline-flex';

    // v0.5.1.2: Web Copy uses its own dedicated textarea so we never pollute
    // the Raw Text textarea (promptContent), preserving the v0.4.x data
    // protection for Raw Text.
    if (editingViewMode === 'web_copy') {
        const webCopyEl = document.getElementById('prompt-web-copy');
        const webCopyTextarea = document.getElementById('web-copy-edit-textarea');
        const emptyEl = document.getElementById('web-copy-empty-state');
        const contentEl = document.getElementById('web-copy-content');
        if (webCopyEl) webCopyEl.classList.remove('hidden');
        if (emptyEl) emptyEl.classList.add('hidden');
        if (contentEl) contentEl.classList.add('hidden');
        if (webCopyTextarea) {
            webCopyTextarea.value = contentToEdit;
            webCopyTextarea.classList.remove('hidden');
            webCopyTextarea.focus({ preventScroll: true });
        }
        // Hide other panels
        promptContent.classList.add('hidden');
        document.getElementById('prompt-preview').classList.add('hidden');
        document.getElementById('prompt-overview').classList.add('hidden');
        document.getElementById('prompt-review').classList.add('hidden');
        const videoEl = document.getElementById('prompt-video');
        if (videoEl) videoEl.classList.add('hidden');
    } else {
        // Show textarea with content, hide preview/overview/review
        promptContent.value = contentToEdit;
        promptContent.removeAttribute('readonly');
        promptContent.classList.add('editing');
        promptContent.classList.remove('hidden');
        document.getElementById('prompt-preview').classList.add('hidden');
        document.getElementById('prompt-overview').classList.add('hidden');
        document.getElementById('prompt-review').classList.add('hidden');
        promptContent.focus({ preventScroll: true });
    }
}

/**
 * Exit edit mode and save changes
 */
// v0.5.1.2 hotfix: re-entrance guard for exitEditMode().
// Click-outside autosave can fire while a save is in flight; guarantee
// only one save attempt per edit session.
let _exitEditModeInFlight = false;

async function exitEditMode() {
    if (!isEditingPrompt) {
        return;
    }
    if (_exitEditModeInFlight) {
        return;
    }
    _exitEditModeInFlight = true;
    try {
        await _exitEditModeImpl();
    } finally {
        _exitEditModeInFlight = false;
    }
}

async function _exitEditModeImpl() {

    // CRITICAL: Use editingViewMode, NOT currentPromptViewMode
    // This prevents pollution if user somehow switched tabs during editing
    const view = editingViewMode;
    let editedContent;
    if (view === 'web_copy') {
        const webCopyTextarea = document.getElementById('web-copy-edit-textarea');
        editedContent = webCopyTextarea ? webCopyTextarea.value : '';
    } else {
        editedContent = promptContent.value;
    }

    // Validate view
    if (!view || (view !== 'raw' && view !== 'preview' && view !== 'overview' && view !== 'web_copy')) {
        alert('Cannot save: Invalid edit mode. Please cancel and try again.');
        return;
    }

    // CRITICAL DATA PROTECTION: Validate content before saving
    if (view === 'raw') {
        const trimmedContent = editedContent.trim();

        // Check 1: Content cannot be empty
        if (!trimmedContent) {
            alert('Raw Text cannot be empty. Save cancelled to prevent data loss.');
            return;
        }

        // Check 2: Content cannot be suspiciously short
        if (trimmedContent.length < 500) {
            const confirmSave = confirm(
                `Warning: Raw Text is very short (${trimmedContent.length} characters).\n\n` +
                `This is unusual for a NotebookLM prompt and may indicate accidental deletion.\n\n` +
                `Are you sure you want to save this?\n\n` +
                `Click Cancel to keep editing, or OK to save anyway.`
            );
            if (!confirmSave) {
                return; // Stay in editing mode
            }
        }
    }

    // Validate history ID
    if (!currentHistoryId) {
        alert('Cannot save: No history record loaded. Please select a record first.');
        return;
    }

    // Save to backend
    try {
        const response = await fetch(apiUrl(`/history/${currentHistoryId}`), {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                view: view,
                content: editedContent
            }),
        });

        if (!response.ok) {
            // Try to parse error from backend
            let errorMsg = 'Unknown error';
            try {
                const errorData = await response.json();
                errorMsg = errorData.detail || errorData.error || errorMsg;
            } catch (e) {
                errorMsg = `HTTP ${response.status}: ${response.statusText}`;
            }

            alert(`Failed to save: ${errorMsg}\n\nYour changes are still in the editor. Please fix the issue or copy your content before closing.`);
            return; // Stay in editing mode, preserve textarea content
        }

        const data = await response.json();

        if (data.success) {
            // Update local state only after successful save
            if (view === 'raw') {
                currentRawText = editedContent;
            } else if (view === 'preview') {
                currentPreviewTextEdited = editedContent;
                // Regenerate preview HTML
                currentPreviewText = `<div class="preview-content">${escapeHtml(editedContent).replace(/\n/g, '<br>')}</div>`;
            } else if (view === 'overview') {
                currentOverviewText = editedContent;
            } else if (view === 'web_copy') {
                currentWebCopyText = editedContent;
            }
        } else {
            const errorMsg = data.error || data.detail || 'Unknown error';
            alert(`Failed to save: ${errorMsg}\n\nYour changes are still in the editor. Please fix the issue or copy your content before closing.`);
            return; // Stay in editing mode
        }
    } catch (error) {
        console.error('Save error:', error);
        alert(`Failed to save: ${error.message}\n\nYour changes are still in the editor. Please try again or copy your content.`);
        return; // Stay in editing mode, preserve textarea content
    }

    // CRITICAL: Clear editing state
    isEditingPrompt = false;
    editingViewMode = null;
    originalEditContent = '';

    // Update edit button back to edit icon
    editBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
        </svg>
        <span class="icon-tooltip">Edit</span>
    `;
    editBtn.classList.remove('editing');
    // Refresh global tooltip so it picks up the restored "Edit" label.
    if (typeof refreshActiveGlobalIconTooltip === 'function') refreshActiveGlobalIconTooltip();

    // Hide cancel button
    const cancelBtn = document.getElementById('cancel-edit-btn');
    if (cancelBtn) {
        cancelBtn.style.display = 'none';
    }

    // Re-render current view using unified render function
    renderCurrentPromptView();
}

/**
 * Cancel edit mode without saving
 */
function cancelEditMode() {
    if (!isEditingPrompt) {
        return;
    }

    // CRITICAL: Restore original content
    if (editingViewMode === 'raw') {
        currentRawText = originalEditContent;
    } else if (editingViewMode === 'preview') {
        currentPreviewTextEdited = originalEditContent;
        currentPreviewText = `<div class="preview-content">${escapeHtml(originalEditContent).replace(/\n/g, '<br>')}</div>`;
    } else if (editingViewMode === 'overview') {
        currentOverviewText = originalEditContent;
    } else if (editingViewMode === 'web_copy') {
        currentWebCopyText = originalEditContent;
    }

    // Clear editing state
    isEditingPrompt = false;
    editingViewMode = null;
    originalEditContent = '';

    // Update edit button back to edit icon
    editBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
        </svg>
        <span class="icon-tooltip">Edit</span>
    `;
    editBtn.classList.remove('editing');
    // Refresh global tooltip so it picks up the restored "Edit" label.
    if (typeof refreshActiveGlobalIconTooltip === 'function') refreshActiveGlobalIconTooltip();

    // Hide cancel button
    const cancelBtn = document.getElementById('cancel-edit-btn');
    if (cancelBtn) {
        cancelBtn.style.display = 'none';
    }

    // Re-render current view
    renderCurrentPromptView();
}

/**
 * Auto-resize regenerate textarea
 */
function autoResizeRegenerateTextarea() {
    regenerateFeedbackInput.style.height = 'auto';
    const maxHeight = 140;
    const newHeight = Math.min(regenerateFeedbackInput.scrollHeight, maxHeight);
    regenerateFeedbackInput.style.height = newHeight + 'px';
    regenerateFeedbackInput.style.overflowY =
        regenerateFeedbackInput.scrollHeight > maxHeight ? 'auto' : 'hidden';
}

/**
 * Trigger regenerate prompt
 */
async function triggerRegenerate() {
    if (isRegenerating) {
        return;
    }

    const feedback = regenerateFeedbackInput.value.trim();

    if (!feedback) {
        alert('请输入修改意见');
        regenerateFeedbackInput.focus();
        return;
    }

    if (!currentHistoryId) {
        alert('No current prompt to regenerate');
        return;
    }

    // Show loading
    isRegenerating = true;
    regenerateBtn.disabled = true;
    regenerateFeedbackInput.disabled = true;

    const loadingEl = document.getElementById('regenerate-loading');
    const errorEl = document.getElementById('regenerate-error');
    loadingEl.classList.remove('hidden');
    errorEl.classList.add('hidden');

    try {
        const response = await fetch(apiUrl(`/history/${currentHistoryId}/regenerate`), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ feedback }),
        });

        const data = await response.json();

        if (data.success) {
            // Convert data to item format for renderHistoryRecord. v0.5.1.2:
            // include web_copy_text so the Web Copy tab hydrates correctly
            // when regenerate runs in Video Mode.
            const item = {
                id: data.history_id,
                topic_group_id: data.topic_group_id,
                slug: data.slug,
                version_number: data.version_number,
                prompt: data.raw_text || data.prompt || data.prompt_text || '',
                preview_text: data.preview_text,
                overview_cn: data.overview_cn,
                change_summary_cn: data.change_summary_cn,
                web_copy_text: data.web_copy_text || '',
                output_dir: data.output_dir,
                title: titleInput.value  // Keep current title
            };

            // Render new version
            renderHistoryRecord(item);

            // v0.5.3: Mock VideoJob is auto-created on regenerate; use it
            // immediately rather than waiting on the latest-job fetch.
            if (currentAppMode === 'video' && data.video_job) {
                currentVideoJob = data.video_job;
                renderVideoJobStatus(currentVideoJob);
            }

            // Clear regenerate input
            regenerateFeedbackInput.value = '';
            autoResizeRegenerateTextarea();

            // Reload history to reflect new version
            loadHistory(currentSearchQuery, currentDateFilter);

            // Load and show version selector
            await loadAndShowVersionSelector(item.topic_group_id, item.id);

            // v0.5.1.2: Video Mode lands on Video tab after regenerate; Prompt
            // Mode keeps whichever tab the user was viewing.
            if (currentAppMode === 'video') {
                switchPromptViewMode('video');
            } else {
                switchPromptViewMode(currentPromptViewMode);
            }

            // Hide loading
            loadingEl.classList.add('hidden');
        } else {
            // Show error
            errorEl.textContent = 'Regenerate failed: ' + (data.error || 'Unknown error');
            errorEl.classList.remove('hidden');
            loadingEl.classList.add('hidden');
        }
    } catch (error) {
        // Network or other error
        errorEl.textContent = 'Request failed: ' + error.message;
        errorEl.classList.remove('hidden');
        loadingEl.classList.add('hidden');
    } finally {
        // Reset state
        isRegenerating = false;
        regenerateBtn.disabled = false;
        regenerateFeedbackInput.disabled = false;
    }
}

// Edit button click
if (editBtn) {
    editBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();

        // v0.5.1.2: Honor data-disabled on uneditable tabs (Video, AI Review).
        if (editBtn.getAttribute('data-disabled') === 'true' && !isEditingPrompt) {
            const msg = editBtn.getAttribute('data-unavailable-message') || 'This tab cannot be edited.';
            if (typeof showAppToast === 'function') {
                showAppToast(msg);
            }
            return;
        }

        if (isEditingPrompt) {
            exitEditMode();
        } else {
            enterEditMode();
        }
    });
}

// Click outside content area to save
document.addEventListener('click', (e) => {
    if (isEditingPrompt) {
        const contentContainer = document.getElementById('prompt-content-container');
        const editButton = document.getElementById('edit-btn');

        // Don't save if clicking inside these areas
        const clickedInsidePromptActions = e.target.closest('.prompt-header-actions');
        const clickedInsideVersionSelector = e.target.closest('.version-selector');
        const clickedInsideViewModes = e.target.closest('.prompt-view-modes');

        if (contentContainer &&
            !contentContainer.contains(e.target) &&
            !editButton.contains(e.target) &&
            !clickedInsidePromptActions &&
            !clickedInsideVersionSelector &&
            !clickedInsideViewModes) {
            exitEditMode();
        }
    }
});

// Regenerate button click
if (regenerateBtn) {
    regenerateBtn.addEventListener('click', triggerRegenerate);
}

// Regenerate textarea auto-resize
if (regenerateFeedbackInput) {
    regenerateFeedbackInput.addEventListener('input', autoResizeRegenerateTextarea);

    // Handle Enter and Shift+Enter
    regenerateFeedbackInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            triggerRegenerate();
        }
    });
}

// =============================================================================
// Debug Helper for Console
// =============================================================================
// Usage: In Chrome DevTools Console, type: __APP_DEBUG_STATE__()
// This will print the current application state for debugging
window.__APP_DEBUG_STATE__ = function() {
    return {
        currentHistoryId,
        currentTopicGroupId,
        currentSlug,
        currentVersionNumber,
        currentPromptViewMode,
        isEditingPrompt,
        isRegenerating,
        isGenerating,
        currentMode,
        rawLength: currentRawText ? currentRawText.length : 0,
        previewEditedLength: currentPreviewTextEdited ? currentPreviewTextEdited.length : 0,
        overviewLength: currentOverviewText ? currentOverviewText.length : 0,
        hasReviewData: !!currentReviewData,
        changeSummaryLength: currentChangeSummaryText ? currentChangeSummaryText.length : 0
    };
};

console.log('[Debug] __APP_DEBUG_STATE__() function is available in console');

// ============================================================
// v0.5.1 - Mode Selector (Prompt Mode <-> Video Mode)
// ============================================================
//
// Top-level app mode is held in `currentAppMode` (declared above). The
// switchAppMode() routine performs full state isolation between the two
// modes: history list, current selection, content panels, version state,
// and AI Review state are all reset when crossing the boundary.
//
// Prompt Mode v0.4.10 protections continue to apply when currentAppMode
// is 'prompt' (Raw must stay clean, schema frozen, etc.).

const MODE_LABELS = {
    prompt: 'Prompt Mode',
    video: 'Video Mode',
};

const MODE_WELCOME = {
    prompt: {
        title: 'Hi, Video Designer!',
        subtitle: '输入视频题目，生成 NotebookLM 教育视频 Prompt',
        placeholder: '请输入视频题目，例如：为什么盲盒越到最后越难集齐',
    },
    video: {
        title: 'Hi, Video Designer!',
        subtitle: '输入视频题目，生成教育视频与配套 Prompt 资产',
        placeholder: '请输入视频题目，例如：为什么指数会爆炸？',
    },
};

function applyModeChrome(mode) {
    const label = document.getElementById('mode-selector-label');
    if (label) label.textContent = MODE_LABELS[mode] || MODE_LABELS.prompt;

    const welcomeTitle = document.getElementById('welcome-title');
    const welcomeSubtitle = document.getElementById('welcome-subtitle');
    const titleInputEl = document.getElementById('title-input');
    const w = MODE_WELCOME[mode] || MODE_WELCOME.prompt;
    if (welcomeTitle) welcomeTitle.textContent = w.title;
    if (welcomeSubtitle) welcomeSubtitle.textContent = w.subtitle;
    if (titleInputEl) titleInputEl.placeholder = w.placeholder;

    // Toggle Video-Mode-only tabs.
    document.querySelectorAll('.view-mode-btn.video-only-tab').forEach((btn) => {
        if (mode === 'video') {
            btn.removeAttribute('hidden');
        } else {
            btn.setAttribute('hidden', '');
        }
    });

    // Update mode-option active state.
    document.querySelectorAll('.mode-option').forEach((btn) => {
        const isActive = btn.dataset.mode === mode;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    // v0.5.3: swap homepage circular generate button per mode.
    updateGenerateButtonForCurrentMode();
}

/**
 * v0.5.3 — Update the homepage circular generate button based on currentAppMode.
 * Prompt Mode keeps "Generate Prompt"; Video Mode shows "Generate Video".
 * Mutates: aria-label, .send-tooltip text. Called from applyModeChrome /
 * switchAppMode and at startup.
 */
function updateGenerateButtonForCurrentMode() {
    const btn = document.getElementById('generate-btn');
    if (!btn) return;
    const isVideo = currentAppMode === 'video';
    const label = isVideo ? 'Generate Video' : 'Generate Prompt';
    btn.setAttribute('aria-label', label);
    const tip = btn.querySelector('.send-tooltip');
    if (tip) tip.textContent = label;
}

function clearActiveSelectionState() {
    currentSlug = '';
    currentHistoryId = null;
    currentTopicGroupId = null;
    currentVideoJob = null;
    currentVersionNumber = null;
    currentVersions = [];
    currentRawText = '';
    currentPreviewText = '';
    currentPreviewTextEdited = '';
    currentOverviewText = '';
    currentChangeSummaryText = '';
    currentReviewData = null;
    historyItems = [];
    trashItems = [];
    favoriteItems = [];
    currentSearchQuery = '';
    currentDateFilter = 'all';
    isEditingPrompt = false;
    isRegenerating = false;
    renderVideoJobStatus(null);

    const titleInputEl = document.getElementById('title-input');
    if (titleInputEl) titleInputEl.value = '';

    const promptContentEl = document.getElementById('prompt-content');
    if (promptContentEl) promptContentEl.value = '';

    const previewEl = document.getElementById('prompt-preview');
    if (previewEl) previewEl.innerHTML = '';

    const overviewEl = document.getElementById('prompt-overview');
    if (overviewEl) overviewEl.innerHTML = '';

    const reviewEl = document.getElementById('prompt-review');
    if (reviewEl) reviewEl.innerHTML = '';
}

function switchAppMode(nextMode) {
    if (nextMode !== 'prompt' && nextMode !== 'video') return;
    if (nextMode === currentAppMode) {
        closeModeDropdown();
        return;
    }

    if (isEditingPrompt) {
        const ok = confirm('You are currently editing. Switching mode will discard your changes. Continue?');
        if (!ok) {
            closeModeDropdown();
            return;
        }
    }

    if (isGenerating || isRegenerating) {
        const ok = confirm('A generation is in progress. Switching mode will not cancel it but will hide its output. Continue?');
        if (!ok) {
            closeModeDropdown();
            return;
        }
    }

    // Stop any playing video before tearing down panels.
    try {
        const v = document.getElementById('video-element');
        if (v) {
            v.pause();
            v.removeAttribute('src');
            v.load();
        }
    } catch (e) { /* ignore */ }

    currentAppMode = nextMode;
    currentMode = 'history';

    clearActiveSelectionState();
    applyModeChrome(nextMode);

    // Default Video Mode tab is "video"; Prompt Mode keeps "raw" default.
    currentPromptViewMode = (nextMode === 'video') ? 'video' : 'raw';

    // Reset to initial / welcome state.
    showSection(document.getElementById('initial-section'));

    // Reload sidebar history list against the new mode's database.
    loadHistory('', 'all');

    closeModeDropdown();
}

function openModeDropdown() {
    const dd = document.getElementById('mode-dropdown');
    const btn = document.getElementById('mode-selector-btn');
    if (!dd || !btn) return;
    dd.classList.remove('hidden');
    btn.setAttribute('aria-expanded', 'true');
    setTimeout(() => {
        document.addEventListener('click', closeModeDropdownOnOutsideClick);
    }, 0);
}

function closeModeDropdown() {
    const dd = document.getElementById('mode-dropdown');
    const btn = document.getElementById('mode-selector-btn');
    if (dd) dd.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', closeModeDropdownOnOutsideClick);
}

function closeModeDropdownOnOutsideClick(e) {
    const selector = document.getElementById('mode-selector');
    if (selector && !selector.contains(e.target)) {
        closeModeDropdown();
    }
}

(function wireModeSelector() {
    const btn = document.getElementById('mode-selector-btn');
    if (btn) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const dd = document.getElementById('mode-dropdown');
            if (dd && dd.classList.contains('hidden')) {
                openModeDropdown();
            } else {
                closeModeDropdown();
            }
        });
    }
    document.querySelectorAll('.mode-option').forEach((opt) => {
        opt.addEventListener('click', (e) => {
            e.stopPropagation();
            const next = e.currentTarget.dataset.mode;
            switchAppMode(next);
        });
    });
})();

// ============================================================
// v0.5.1 - Video Player wiring (framework only — no real video URL)
// ============================================================

function formatVideoTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '00:00';
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(m)}:${pad(s)}`;
}

function refreshVideoPlayPauseIcons(isPlaying) {
    const btn = document.getElementById('video-play-btn');
    const center = document.getElementById('video-center-play');
    if (btn) {
        const playIcon = btn.querySelector('.icon-play');
        const pauseIcon = btn.querySelector('.icon-pause');
        if (playIcon && pauseIcon) {
            playIcon.classList.toggle('hidden', isPlaying);
            pauseIcon.classList.toggle('hidden', !isPlaying);
        }
    }
    if (center) {
        center.style.display = isPlaying ? 'none' : '';
    }
}

(function wireVideoPlayer() {
    const video = document.getElementById('video-element');
    const placeholder = document.getElementById('video-placeholder');
    const controls = document.getElementById('video-controls');
    const playBtn = document.getElementById('video-play-btn');
    const centerPlay = document.getElementById('video-center-play');
    const progress = document.getElementById('video-progress');
    const timeEl = document.getElementById('video-time');
    const fullscreenBtn = document.getElementById('video-fullscreen-btn');
    const speedBtn = document.getElementById('video-speed-btn');
    const speedMenu = document.getElementById('video-speed-menu');
    const speedLabel = document.getElementById('video-speed-label');
    const volumeBtn = document.getElementById('video-volume-btn');
    const volumePopover = document.getElementById('video-volume-popover');
    const volumeInput = document.getElementById('video-volume');
    const shell = document.getElementById('video-player-shell');

    if (!video) return;

    const hasSource = () => !!(video.currentSrc || video.src);

    const togglePlay = () => {
        if (!hasSource()) {
            // v0.5.1.2 hotfix: scope the cue to the player frame so it
            // doesn't pop at the page bottom. Falls back to global toast
            // only if the player shell is missing.
            if (typeof showVideoPlayerToast === 'function') {
                showVideoPlayerToast('Video source is not available yet.');
            } else if (typeof showAppToast === 'function') {
                showAppToast('Video source is not available yet.');
            }
            return;
        }
        if (video.paused) {
            video.play().catch(() => { /* user activation may be required */ });
        } else {
            video.pause();
        }
    };

    if (playBtn) playBtn.addEventListener('click', togglePlay);
    if (centerPlay) centerPlay.addEventListener('click', togglePlay);

    video.addEventListener('play', () => {
        if (placeholder) placeholder.style.display = 'none';
        if (controls) controls.removeAttribute('hidden');
        refreshVideoPlayPauseIcons(true);
    });
    video.addEventListener('pause', () => refreshVideoPlayPauseIcons(false));
    video.addEventListener('ended', () => refreshVideoPlayPauseIcons(false));

    video.addEventListener('loadedmetadata', () => {
        if (controls) controls.removeAttribute('hidden');
        if (timeEl) timeEl.textContent = `${formatVideoTime(0)} / ${formatVideoTime(video.duration)}`;
    });

    video.addEventListener('timeupdate', () => {
        if (!isFinite(video.duration) || video.duration <= 0) return;
        const pct = (video.currentTime / video.duration) * 100;
        if (progress && document.activeElement !== progress) {
            progress.value = String(pct);
        }
        if (timeEl) {
            timeEl.textContent = `${formatVideoTime(video.currentTime)} / ${formatVideoTime(video.duration)}`;
        }
    });

    if (progress) {
        progress.addEventListener('input', () => {
            if (!isFinite(video.duration) || video.duration <= 0) return;
            const pct = parseFloat(progress.value || '0');
            video.currentTime = (pct / 100) * video.duration;
        });
    }

    if (fullscreenBtn && shell) {
        fullscreenBtn.addEventListener('click', () => {
            if (!document.fullscreenElement) {
                if (shell.requestFullscreen) shell.requestFullscreen();
            } else {
                if (document.exitFullscreen) document.exitFullscreen();
            }
        });
    }

    if (speedBtn && speedMenu) {
        speedBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = speedMenu.classList.toggle('hidden');
            speedBtn.setAttribute('aria-expanded', isHidden ? 'false' : 'true');
        });
        document.addEventListener('click', (e) => {
            if (!speedMenu.classList.contains('hidden') && !speedMenu.contains(e.target) && e.target !== speedBtn) {
                speedMenu.classList.add('hidden');
                speedBtn.setAttribute('aria-expanded', 'false');
            }
        });
        speedMenu.querySelectorAll('.video-speed-option').forEach((opt) => {
            opt.addEventListener('click', (e) => {
                const speed = parseFloat(e.currentTarget.dataset.speed || '1');
                if (isFinite(speed) && speed > 0) {
                    video.playbackRate = speed;
                    if (speedLabel) speedLabel.textContent = `${speed}×`;
                    speedMenu.querySelectorAll('.video-speed-option').forEach((o) => {
                        o.classList.toggle('active', o === e.currentTarget);
                    });
                }
                speedMenu.classList.add('hidden');
                speedBtn.setAttribute('aria-expanded', 'false');
            });
        });
    }

    if (volumeBtn && volumePopover) {
        volumeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            volumePopover.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!volumePopover.classList.contains('hidden') &&
                !volumePopover.contains(e.target) &&
                e.target !== volumeBtn) {
                volumePopover.classList.add('hidden');
            }
        });
    }

    if (volumeInput) {
        volumeInput.addEventListener('input', () => {
            const v = parseFloat(volumeInput.value || '1');
            video.volume = Math.max(0, Math.min(1, v));
            video.muted = video.volume === 0;
        });
    }
})();

// Apply initial mode chrome on first paint.
applyModeChrome(currentAppMode);
