/**
 * SMS Viewer — Main JavaScript
 * Handles theme toggling, entity copy-to-clipboard, and basic UI interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initEntityCopy();
    initSearchClear();
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
    // We attach the listener to the document to handle dynamically loaded content
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
            // Fallback for older browsers
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
    
    // Trigger reflow to restart animation
    toast.classList.remove('copy-toast--visible');
    void toast.offsetWidth;
    toast.classList.add('copy-toast--visible');

    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
        toast.classList.remove('copy-toast--visible');
    }, 2000);
}

// -----------------------------------------------------------------------------
// Search Bar UX
// -----------------------------------------------------------------------------
function initSearchClear() {
    const searchInput = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    
    if (!searchInput || !clearBtn) return;

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchInput.focus();
        // Trigger input event to re-filter results if needed
        searchInput.dispatchEvent(new Event('input'));
    });
}
