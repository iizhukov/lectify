import { initRouter, highlightNav } from './router.js';
import { api } from './api.js';
import { logout } from './auth.js';

window.api = api;

document.addEventListener('DOMContentLoaded', () => {
  initRouter();
  highlightNav(window.location.pathname);

  document.getElementById('sidebar-logout-btn')?.addEventListener('click', () => {
    api.auth.logout().catch(() => {});
    logout();
  });
});

window.showToast = function(type, message) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const colors = {
    success: 'bg-green-600',
    error:   'bg-red-600',
    warning: 'bg-yellow-600',
    info:    'bg-brand',
  };
  const toast = document.createElement('div');
  toast.className = `px-4 py-3 rounded-lg shadow-lg text-white transform transition-all duration-300 translate-x-full ${colors[type] || colors.info}`;
  toast.textContent = message;
  toast.style.opacity = '0';
  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(0)';
  });
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
};

window.formatDate = function(date) {
  if (!date) return '-';
  return new Date(date).toLocaleString('ru-RU');
};

window.formatSize = function(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(1) + ' ' + units[i];
};
