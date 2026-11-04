/**
 * SMS Viewer — Main JavaScript
 * Handles theme toggling, entity copy-to-clipboard, live thread filtering,
 * and paginated infinite scroll.
 */

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initEntityCopy();
    initSearchClear();
    initThreadSearch();
    initThreadPagination();
});

// -----------------------------------------------------------------------------
// Theme Management
// -----------------------------------------------------------------------------
function initThemeToggle() {
    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (!toggleBtn) return;

    // Load saved theme or system preference
    const savedTheme = localStorage.getItem('sms-viewer-theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }

    // Toggle on click
    toggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('sms-viewer-theme', newTheme);
    });
}

// -----------------------------------------------------------------------------
// Copy to Clipboard (for Entity Highlights)
// -----------------------------------------------------------------------------
function initEntityCopy() {
    document.addEventListener('click', async (e) => {
        const entitySpan = e.target.closest('.entity[data-copy]');
        if (!entitySpan) return;

        const textToCopy = entitySpan.getAttribute('data-copy');
        if (!textToCopy) return;

        try {
            await navigator.clipboard.writeText(textToCopy);
            showCopyToast(`Copied: ${textToCopy}`);
        } catch (err) {
            console.error('Failed to copy text: ', err);
            const textArea = document.createElement('textarea');
            textArea.value = textToCopy;
            document.body.appendChild(textArea);
            textArea.select();
            try {
                document.execCommand('copy');
                showCopyToast(`Copied: ${textToCopy}`);
            } catch (fallbackErr) {
                console.error('Fallback copy failed', fallbackErr);
            }
            document.body.removeChild(textArea);
        }
    });
}

let toastTimeout;
function showCopyToast(message) {
    let toast = document.getElementById('copy-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'copy-toast';
        toast.className = 'copy-toast';
        document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.classList.remove('copy-toast--visible');
    void toast.offsetWidth;
    toast.classList.add('copy-toast--visible');

    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
        toast.classList.remove('copy-toast--visible');
    }, 2000);
}

// -----------------------------------------------------------------------------
// Search Bar UX & Live Thread Filter
// -----------------------------------------------------------------------------
function initSearchClear() {
    const searchInput = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    
    if (!searchInput || !clearBtn) return;

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchInput.focus();
        searchInput.dispatchEvent(new Event('input'));
    });
}

function initThreadSearch() {
    const searchInput = document.getElementById('search-input');
    const threadList = document.getElementById('thread-list');
    const noResultsMsg = document.getElementById('search-no-results');

    if (!searchInput || !threadList) return;

    searchInput.addEventListener('input', () => {
        const query = searchInput.value.trim().toLowerCase();
        const threadItems = threadList.querySelectorAll('.thread-item');
        let visibleCount = 0;

        threadItems.forEach(item => {
            const address = item.getAttribute('data-address') || '';
            const body = item.getAttribute('data-body') || '';

            if (!query || address.includes(query) || body.includes(query)) {
                item.closest('li').style.display = '';
                visibleCount++;
            } else {
                item.closest('li').style.display = 'none';
            }
        });

        if (noResultsMsg) {
            noResultsMsg.style.display = (visibleCount === 0 && query.length > 0) ? 'block' : 'none';
        }

        const paginationWrap = document.getElementById('pagination-wrap');
        if (paginationWrap) {
            paginationWrap.style.display = query.length > 0 ? 'none' : '';
        }
    });
}

// -----------------------------------------------------------------------------
// Infinite Scroll / Load More for Thread List
// -----------------------------------------------------------------------------
function initThreadPagination() {
    const loadMoreBtn = document.getElementById('load-more-btn');
    const threadList = document.getElementById('thread-list');
    const paginationWrap = document.getElementById('pagination-wrap');

    if (!loadMoreBtn || !threadList) return;

    loadMoreBtn.addEventListener('click', async () => {
        const currentPage = parseInt(loadMoreBtn.getAttribute('data-page') || '1', 10);
        const nextPage = currentPage + 1;
        const btnText = document.getElementById('load-more-text');

        loadMoreBtn.disabled = true;
        if (btnText) btnText.textContent = 'Loading conversations...';

        try {
            const resp = await fetch(`/api/threads?page=${nextPage}&limit=30`);
            if (!resp.ok) throw new Error('Network error');

            const data = await resp.json();
            if (data.threads && data.threads.length > 0) {
                data.threads.forEach(t => {
                    const li = document.createElement('li');
                    const unreadClass = (t.unread_count && t.unread_count > 0) ? 'thread-item--unread' : '';
                    const youPrefix = (t.last_type === 2) ? '<span class="thread-preview__prefix">You: </span>' : '';
                    const badge = (t.unread_count && t.unread_count > 0)
                        ? `<span class="thread-badge thread-badge--unread" title="${t.unread_count} unread">${t.unread_count}</span>`
                        : `<span class="thread-badge" title="${t.message_count} messages">${t.message_count}</span>`;

                    li.innerHTML = `
                        <a href="/thread/${encodeURIComponent(t.address)}" class="thread-item ${unreadClass}" data-address="${escapeHtml(t.address.toLowerCase())}" data-body="${escapeHtml((t.last_body || '').toLowerCase())}">
                            <div class="thread-avatar avatar-color-${t.avatar_color}" aria-hidden="true">
                                ${escapeHtml(t.avatar_initial)}
                            </div>
                            <div class="thread-info">
                                <div class="thread-header">
                                    <span class="thread-name">${escapeHtml(t.address)}</span>
                                    <span class="thread-time">${escapeHtml(t.formatted_time || '')}</span>
                                </div>
                                <div class="thread-preview">${youPrefix}${escapeHtml(t.last_body || '')}</div>
                            </div>
                            <div class="thread-meta">
                                ${badge}
                            </div>
                        </a>
                    `;
                    threadList.appendChild(li);
                });

                loadMoreBtn.setAttribute('data-page', nextPage.toString());
            }

            if (!data.has_more) {
                if (paginationWrap) paginationWrap.style.display = 'none';
            } else {
                loadMoreBtn.disabled = false;
                if (btnText) btnText.textContent = 'Load More Conversations';
            }
        } catch (err) {
            console.error('Failed to load more threads:', err);
            loadMoreBtn.disabled = false;
            if (btnText) btnText.textContent = 'Retry Loading';
        }
    });
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
