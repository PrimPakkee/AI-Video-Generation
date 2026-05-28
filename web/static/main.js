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
let historyItems = [];
let trashItems = [];
let favoriteItems = [];
let currentMode = 'history'; // 'history' | 'trash' | 'favorites'
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
    document.getElementById('prompt-overview').innerHTML = overviewHTML;
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

        const url = params.toString() ? `/api/history?${params}` : '/api/history';
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
            ? `/api/trash?q=${encodeURIComponent(searchQuery)}`
            : '/api/trash';

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
            ? `/api/favorites?q=${encodeURIComponent(searchQuery)}`
            : '/api/favorites';

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
        historyList.innerHTML = '<div class="no-history">No history yet</div>';
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
        const response = await fetch(`/api/history/${historyId}`);
        const data = await response.json();

        if (data.success && data.item) {
            const item = data.item;

            // Render history record
            renderHistoryRecord(item);

            // Fill input
            titleInput.value = item.title;
            autoResizeTextarea();

            // Reset to Raw Text mode
            switchPromptViewMode('raw');

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
        const response = await fetch(`/api/history/${historyId}/pin`, {
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
        const response = await fetch(`/api/history/${historyId}/unpin`, {
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
        const response = await fetch(`/api/history/group/${topicGroupId}/favorite`, {
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
        const response = await fetch(`/api/history/group/${topicGroupId}/unfavorite`, {
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
        const response = await fetch(`/api/history/group/${topicGroupId}/rename`, {
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
        const response = await fetch(`/api/history/group/${topicGroupId}/trash`, {
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
        const response = await fetch(`/api/history/group/${topicGroupId}/permanent`, {
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
        const response = await fetch(`/api/history/${historyId}`, {
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

    // Update title
    const titleEl = document.getElementById('prompt-view-title');
    if (mode === 'raw') {
        titleEl.textContent = 'NotebookLM Prompt';
    } else if (mode === 'preview') {
        titleEl.textContent = 'Prompt Preview';
    } else if (mode === 'overview') {
        titleEl.textContent = 'Content Overview';
    } else if (mode === 'review') {
        titleEl.textContent = 'AI Review';
    }

    // Update active button
    document.querySelectorAll('.view-mode-btn').forEach(btn => {
        if (btn.dataset.mode === mode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Render content based on mode
    if (mode === 'raw') {
        // CRITICAL: Always hydrate from currentRawText
        rawEl.value = currentRawText || '';
        rawEl.setAttribute('readonly', 'readonly');
        rawEl.classList.remove('editing');
        rawEl.classList.remove('hidden');
        previewEl.classList.add('hidden');
        overviewEl.classList.add('hidden');
        reviewEl.classList.add('hidden');

    } else if (mode === 'preview') {
        // CRITICAL: Never touch currentRawText or promptContent.value
        rawEl.classList.add('hidden');
        previewEl.innerHTML = currentPreviewText || '';
        previewEl.classList.remove('hidden');
        overviewEl.classList.add('hidden');
        reviewEl.classList.add('hidden');

    } else if (mode === 'overview') {
        // CRITICAL: Never touch currentRawText
        rawEl.classList.add('hidden');
        previewEl.classList.add('hidden');

        let overviewHTML = `<div class="overview-content">${escapeHtml(currentOverviewText || '').replace(/\n/g, '<br>')}</div>`;
        if (currentChangeSummaryText) {
            overviewHTML += `
                <div class="change-summary-section">
                    <h4 class="change-summary-title">本次生成新增或改动的内容</h4>
                    <div class="change-summary-content">${escapeHtml(currentChangeSummaryText).replace(/\n/g, '<br>')}</div>
                </div>
            `;
        }
        overviewEl.innerHTML = overviewHTML;
        overviewEl.classList.remove('hidden');
        reviewEl.classList.add('hidden');

    } else if (mode === 'review') {
        // CRITICAL: Never touch currentRawText
        rawEl.classList.add('hidden');
        previewEl.classList.add('hidden');
        overviewEl.classList.add('hidden');
        reviewEl.classList.remove('hidden');

        // Load review if not already loaded
        if (!currentReviewData) {
            loadReview();
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
    showSection(loadingSection);

    try {
        const response = await fetch('/api/generate', {
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

            // Update prompt view state
            currentRawText = data.prompt || '';

            // Generate preview
            try {
                const sections = parsePromptSections(currentRawText);
                currentPreviewText = generatePreviewHTML(sections);
            } catch (error) {
                console.error('Failed to generate preview:', error);
                currentPreviewText = '<div class="preview-error">Preview generation failed. See Raw Text for full content.</div>';
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

            // Reset to Raw Text mode
            switchPromptViewMode('raw');

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

            showSection(errorSection);
        }
    } catch (error) {
        // Network or other error
        errorMessage.textContent = `请求失败: ${error.message}`;
        errorDetails.classList.add('hidden');
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
        text = currentOverviewText;
    }

    try {
        await navigator.clipboard.writeText(text);

        // Visual feedback
        copyBtn.classList.add('copied');
        const tooltip = copyBtn.querySelector('.icon-tooltip');
        if (tooltip) {
            const originalText = tooltip.textContent;
            tooltip.textContent = 'Copied!';
            setTimeout(() => {
                copyBtn.classList.remove('copied');
                tooltip.textContent = originalText;
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
        text = currentOverviewText;
        filenameSuffix = 'overview';
    }

    if (!text.trim()) {
        return;
    }

    // Sanitize slug for filename
    const slug = currentSlug || currentHistoryId || 'prompt';
    const safeSlug = String(slug)
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '_')
        .replace(/^_+|_+$/g, '') || 'prompt';

    // Create blob and download
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = `${safeSlug}_${filenameSuffix}.txt`;
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
        const response = await fetch(`/api/history/group/${topicGroupId}/versions`);
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
        const response = await fetch(`/api/history/${historyId}`);
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
        const response = await fetch(`/api/history/${currentHistoryId}/download-all`);

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

    // Only allow editing raw, preview, or overview
    if (currentPromptViewMode !== 'raw' && currentPromptViewMode !== 'preview' && currentPromptViewMode !== 'overview') {
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
        contentToEdit = currentPreviewTextEdited || '';
    } else if (editingViewMode === 'overview') {
        contentToEdit = currentOverviewText || '';
    }

    // CRITICAL: Store original content for cancel
    originalEditContent = contentToEdit;

    // Update edit button to save icon
    editBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
        </svg>
        <span class="icon-tooltip">Save</span>
    `;
    editBtn.classList.add('editing');

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

/**
 * Exit edit mode and save changes
 */
async function exitEditMode() {
    if (!isEditingPrompt) {
        return;
    }

    // CRITICAL: Use editingViewMode, NOT currentPromptViewMode
    // This prevents pollution if user somehow switched tabs during editing
    const view = editingViewMode;
    const editedContent = promptContent.value;

    // Validate view
    if (!view || (view !== 'raw' && view !== 'preview' && view !== 'overview')) {
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
        const response = await fetch(`/api/history/${currentHistoryId}`, {
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
        const response = await fetch(`/api/history/${currentHistoryId}/regenerate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ feedback }),
        });

        const data = await response.json();

        if (data.success) {
            // Convert data to item format for renderHistoryRecord
            const item = {
                id: data.history_id,
                topic_group_id: data.topic_group_id,
                slug: data.slug,
                version_number: data.version_number,
                prompt: data.raw_text,
                preview_text: data.preview_text,
                overview_cn: data.overview_cn,
                change_summary_cn: data.change_summary_cn,
                output_dir: data.output_dir,
                title: titleInput.value  // Keep current title
            };

            // Render new version
            renderHistoryRecord(item);

            // Clear regenerate input
            regenerateFeedbackInput.value = '';
            autoResizeRegenerateTextarea();

            // Reload history to reflect new version
            loadHistory(currentSearchQuery, currentDateFilter);

            // Load and show version selector
            await loadAndShowVersionSelector(item.topic_group_id, item.id);

            // Switch to the current view mode
            switchPromptViewMode(currentPromptViewMode);

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
