/**
 * app.js — Global utilities and helpers
 */

// Toast notification system
function showToast(message, type = 'info', duration = 4000) {
  const existing = document.getElementById('toast-container');
  if (!existing) {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed bottom-4 right-4 z-50 space-y-2';
    document.body.appendChild(container);
  }

  const colors = {
    info: 'bg-slate-800 text-white',
    success: 'bg-emerald-600 text-white',
    error: 'bg-red-600 text-white',
    warning: 'bg-amber-500 text-white',
  };

  const toast = document.createElement('div');
  toast.className = `${colors[type] || colors.info} px-5 py-3 rounded-xl shadow-xl text-sm font-medium max-w-xs transition-all transform translate-y-0 opacity-100`;
  toast.textContent = message;

  document.getElementById('toast-container').appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// Fetch wrapper with error handling
async function apiFetch(url, options = {}) {
  try {
    const resp = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    return await resp.json();
  } catch (e) {
    throw e;
  }
}

// Format duration
function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// Escape HTML
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
