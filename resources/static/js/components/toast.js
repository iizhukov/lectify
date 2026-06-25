export function showToast(type, message) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const colors = {
    success: 'bg-green-600',
    error: 'bg-red-600',
    warning: 'bg-yellow-600',
    info: 'bg-brand',
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
}
