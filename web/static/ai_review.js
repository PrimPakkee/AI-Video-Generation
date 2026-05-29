/**
 * AI Review Module - v0.4.6.8
 *
 * Manual trigger mode: Only Re-review button can trigger AI Review generation
 * All other operations (tab switching, history switching) are read-only
 */

// In-flight request tracking to prevent duplicate POST requests
const reviewInFlight = new Map();

// Polling state
let reviewPollingTimer = null;

/**
 * Render Video Mode AI Review placeholder.
 * v0.5.1.2: Video Mode does NOT call any Prompt Mode AI Review API.
 * This tab will later evaluate the generated video assets independently.
 */
function renderVideoReviewPlaceholder() {
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl) return;
    reviewEl.innerHTML = `
        <div class="review-empty-state">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="1.5">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 6v6l4 2"/>
            </svg>
            <p><strong>AI Review for Video Mode is not connected in v0.5.1.2.</strong></p>
            <p style="font-size: 14px; color: #666; margin-top: 8px;">This tab will later evaluate the generated video assets independently from Prompt Mode.</p>
        </div>
    `;
}

/**
 * Returns true when the page is in Video Mode and AI Review must NOT call Prompt Mode API.
 */
function isVideoModeForReview() {
    try {
        return typeof window !== 'undefined' && window.getCurrentAppMode && window.getCurrentAppMode() === 'video';
    } catch (e) {
        return false;
    }
}

/**
 * Load AI Review for current history record (READ ONLY)
 * Does NOT automatically generate review
 * Only renders existing data or empty/stale state
 */
async function loadReview() {
    // v0.5.1.2: Video Mode shows a placeholder and never calls Prompt Mode review API
    if (isVideoModeForReview()) {
        stopReviewPolling();
        renderVideoReviewPlaceholder();
        return;
    }

    if (!currentHistoryId) {
        console.error('No current history ID');
        return;
    }

    // IMPORTANT: Capture historyId at the start and use it throughout
    const historyId = currentHistoryId;
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl) return;

    // Show loading state while fetching
    reviewEl.innerHTML = `
        <div class="review-loading">
            <div class="spinner"></div>
            <p>Loading AI Review...</p>
        </div>
    `;

    try {
        // Step 1: GET review status (READ ONLY - never POST)
        const getResponse = await fetch(`/api/history/${historyId}/review`);
        const getData = await getResponse.json();

        if (!getData.success) {
            throw new Error(getData.error || 'Failed to load review status');
        }

        const status = getData.status;

        // Handle different statuses
        if (status === 'completed') {
            // Review is ready, render it with Re-review button
            currentReviewData = getData.review;
            renderReviewWithToolbar(currentReviewData, false); // not stale
            stopReviewPolling();
            return;
        }

        if (status === 'generating') {
            // Review is being generated, show loading and start polling
            reviewEl.innerHTML = `
                <div class="review-loading">
                    <div class="spinner"></div>
                    <p>AI Review is generating...</p>
                    <p style="font-size: 12px; margin-top: 8px;">This may take 20-30 seconds</p>
                </div>
            `;
            startReviewPolling(historyId);
            return;
        }

        if (status === 'stale') {
            // Prompt has changed, show old review with warning banner
            const oldReviewData = getData.review;
            if (oldReviewData) {
                currentReviewData = oldReviewData;
                renderReviewWithToolbar(currentReviewData, true); // is stale
            } else {
                renderReviewEmptyState();
            }
            return;
        }

        if (status === 'failed') {
            // Review generation failed, show error with Re-review button
            const errorMsg = getData.error || 'AI Review generation failed';
            renderReviewFailedState(errorMsg);
            return;
        }

        // Status is 'none' - no review exists yet
        renderReviewEmptyState();

    } catch (error) {
        console.error('Failed to load review:', error);
        reviewEl.innerHTML = `
            <div class="review-error">
                <p><strong>Failed to Load AI Review</strong></p>
                <p style="font-size: 14px; margin-top: 8px;">Please try again.</p>
            </div>
        `;
    }
}

/**
 * Regenerate AI Review (manual trigger via Re-review button)
 * This is the ONLY function that can POST to generate review
 */
async function regenerateReview() {
    // v0.5.1.2: Video Mode shows a placeholder and never calls Prompt Mode review API
    if (isVideoModeForReview()) {
        stopReviewPolling();
        renderVideoReviewPlaceholder();
        return;
    }

    if (!currentHistoryId) {
        console.error('No current history ID');
        return;
    }

    const historyId = currentHistoryId;
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl) return;

    // Check if request already in flight
    const key = `review_${historyId}`;
    if (reviewInFlight.has(key)) {
        console.log('Review regeneration already in flight, skipping duplicate');
        return;
    }

    // Show loading state
    reviewEl.innerHTML = `
        <div class="review-loading">
            <div class="spinner"></div>
            <p>Regenerating AI Review...</p>
            <p style="font-size: 12px; margin-top: 8px;">This may take 20-30 seconds</p>
        </div>
    `;

    try {
        // Mark as in-flight
        reviewInFlight.set(key, true);

        // POST to force regenerate
        const postResponse = await fetch(`/api/history/${historyId}/review?force=true`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const postData = await postResponse.json();

        // Log debug error if present
        if (postData.debug_error) {
            console.error('[AI Review Debug Error]', postData.debug_error);
        }

        if (postData.status === 'generating') {
            startReviewPolling(historyId);
            reviewInFlight.delete(key);
            return;
        }

        if (postData.success && postData.status === 'completed' && postData.review) {
            currentReviewData = postData.review;
            renderReviewWithToolbar(currentReviewData, false);
            reviewInFlight.delete(key);
            return;
        }

        if (postData.cached && postData.review) {
            currentReviewData = postData.review;
            renderReviewWithToolbar(currentReviewData, false);
            reviewInFlight.delete(key);
            return;
        }

        // Regeneration failed
        const errorMsg = postData.error || 'AI Review regeneration failed';
        renderReviewFailedState(errorMsg);
        reviewInFlight.delete(key);

    } catch (error) {
        console.error('Failed to regenerate review:', error);
        renderReviewFailedState('Failed to regenerate AI Review. Please try again.');
        reviewInFlight.delete(key);
    }
}

/**
 * Render review with toolbar (includes Re-review button)
 */
function renderReviewWithToolbar(reviewData, isStale = false) {
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl || !reviewData) return;

    let html = '';

    // Stale warning banner
    if (isStale) {
        html += `
            <div class="review-stale-banner">
                ⚠️ This review may be outdated because the prompt has changed. Click Re-review to update it.
            </div>
        `;
    }

    // Toolbar with Re-review button
    html += `
        <div class="review-toolbar">
            <h3>AI Quality Evaluation</h3>
            <button class="review-rereview-btn" onclick="regenerateReview()" title="Re-review">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                Re-review
            </button>
        </div>
    `;

    // Review table
    const rows = reviewData.rows || [];
    const totalScore = reviewData.total_score || 0;
    const overallReview = reviewData.overall_review || '';

    html += `
        <table class="review-table">
            <thead>
                <tr>
                    <th>Criterion</th>
                    <th style="width: 80px;">Weight</th>
                    <th style="width: 280px;">Evaluation Focus</th>
                    <th style="width: 90px;">LLM Score</th>
                    <th>LLM Comment</th>
                </tr>
            </thead>
            <tbody>
    `;

    // Render each dimension row
    for (const row of rows) {
        html += `
            <tr>
                <td class="criterion">${escapeHtml(row.criterion || '')}</td>
                <td class="weight">${escapeHtml(row.weight || '')}</td>
                <td class="focus">${escapeHtml(row.evaluation_focus || '')}</td>
                <td class="score">${escapeHtml(row.llm_score || '')}</td>
                <td class="comment">${escapeHtml(row.llm_comment || '')}</td>
            </tr>
        `;
    }

    // Total Score row
    html += `
            <tr class="total-score">
                <td class="criterion">Total Score</td>
                <td class="weight">100%</td>
                <td class="focus">-</td>
                <td class="score">${totalScore}/100</td>
                <td class="comment">-</td>
            </tr>
    `;

    // Overall Review row
    html += `
            <tr class="overall-review">
                <td class="criterion">Overall Review</td>
                <td class="weight">-</td>
                <td class="focus">-</td>
                <td class="score">-</td>
                <td class="comment">${escapeHtml(overallReview)}</td>
            </tr>
    `;

    html += `
            </tbody>
        </table>
    `;

    reviewEl.innerHTML = html;
}

/**
 * Render empty state when no review exists
 */
function renderReviewEmptyState() {
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl) return;

    reviewEl.innerHTML = `
        <div class="review-toolbar">
            <h3>AI Quality Evaluation</h3>
            <button class="review-rereview-btn" onclick="regenerateReview()" title="Re-review">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                Re-review
            </button>
        </div>
        <div class="review-empty-state">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="1.5">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 6v6l4 2"/>
            </svg>
            <p><strong>No AI Review yet</strong></p>
            <p style="font-size: 14px; color: #666; margin-top: 8px;">Click Re-review to generate one.</p>
        </div>
    `;
}

/**
 * Render failed state with Re-review button
 */
function renderReviewFailedState(errorMsg) {
    const reviewEl = document.getElementById('prompt-review');
    if (!reviewEl) return;

    reviewEl.innerHTML = `
        <div class="review-toolbar">
            <h3>AI Quality Evaluation</h3>
            <button class="review-rereview-btn" onclick="regenerateReview()" title="Re-review">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                Re-review
            </button>
        </div>
        <div class="review-error">
            <p><strong>AI Review Generation Failed</strong></p>
            <p style="font-size: 14px; margin-top: 8px;">${escapeHtml(errorMsg)}</p>
            <p style="font-size: 14px; margin-top: 8px; color: #666;">Click Re-review to try again.</p>
        </div>
    `;
}

/**
 * Render review table (legacy function, kept for compatibility)
 */
function renderReview(reviewData) {
    renderReviewWithToolbar(reviewData, false);
}

/**
 * Start polling for review status
 * @param {number} historyId - The fixed history ID to poll for (not global currentHistoryId)
 */
function startReviewPolling(historyId) {
    stopReviewPolling(); // Clear any existing timer

    // v0.5.1.2: Video Mode never polls Prompt Mode review API
    if (isVideoModeForReview()) {
        renderVideoReviewPlaceholder();
        return;
    }

    if (!historyId) {
        console.error('startReviewPolling: historyId is required');
        return;
    }

    let pollCount = 0;
    const maxPolls = 150; // 150 polls * 2 seconds = 5 minutes max

    reviewPollingTimer = setInterval(async () => {
        // v0.5.1.2: bail immediately if mode switched to Video mid-polling
        if (isVideoModeForReview()) {
            stopReviewPolling();
            renderVideoReviewPlaceholder();
            return;
        }

        pollCount++;

        if (pollCount > maxPolls) {
            stopReviewPolling();
            // Only show timeout if we're still on the same history record
            if (currentHistoryId === historyId) {
                const reviewEl = document.getElementById('prompt-review');
                if (reviewEl) {
                    reviewEl.innerHTML = `
                        <div class="review-error">
                            <p><strong>AI Review Generation Timeout</strong></p>
                            <p style="font-size: 14px; margin-top: 8px;">Generation took too long. Please try again.</p>
                        </div>
                    `;
                }
            }
            return;
        }

        try {
            // IMPORTANT: Use the fixed historyId parameter, not global currentHistoryId
            const response = await fetch(`/api/history/${historyId}/review`);
            const data = await response.json();

            if (!data.success) {
                console.error('Polling error:', data.error);
                return;
            }

            if (data.status === 'completed' && data.review) {
                // Generation completed
                stopReviewPolling();

                // Only update UI if we're still on the same history record
                if (currentHistoryId === historyId) {
                    currentReviewData = data.review;
                    renderReviewWithToolbar(currentReviewData, false);
                }
            } else if (data.status === 'failed') {
                // Generation failed
                stopReviewPolling();

                // Only show error if we're still on the same history record
                if (currentHistoryId === historyId) {
                    const errorMsg = data.error || 'AI Review generation failed';
                    renderReviewFailedState(errorMsg);
                }
            }
            // If still generating, continue polling
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 2000); // Poll every 2 seconds
}

/**
 * Stop polling for review status
 */
function stopReviewPolling() {
    if (reviewPollingTimer) {
        clearInterval(reviewPollingTimer);
        reviewPollingTimer = null;
    }
}

/**
 * Convert review data to markdown format
 */
function reviewToMarkdown(reviewData) {
    if (!reviewData) return 'AI Review has not been generated yet.';

    const rows = reviewData.rows || [];
    const totalScore = reviewData.total_score || 0;
    const overallReview = reviewData.overall_review || '';

    let markdown = '# AI Quality Evaluation\n\n';
    markdown += '| Criterion | Weight | Evaluation Focus | LLM Score | LLM Comment |\n';
    markdown += '|-----------|-------:|------------------|----------:|-------------|\n';

    for (const row of rows) {
        const criterion = (row.criterion || '').replace(/\|/g, '\\|');
        const weight = (row.weight || '').replace(/\|/g, '\\|');
        const focus = (row.evaluation_focus || '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
        const score = (row.llm_score || '').replace(/\|/g, '\\|');
        const comment = (row.llm_comment || '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
        markdown += `| ${criterion} | ${weight} | ${focus} | ${score} | ${comment} |\n`;
    }

    markdown += `| **Total Score** | **100%** | - | **${totalScore}/100** | - |\n`;
    markdown += `| **Overall Review** | - | - | - | ${overallReview.replace(/\|/g, '\\|')} |\n`;

    return markdown;
}

/**
 * Get review content for download/copy
 */
function getReviewContent() {
    if (!currentReviewData) {
        return 'AI Review has not been generated yet.';
    }
    return reviewToMarkdown(currentReviewData);
}
