let activeModal = null;
let _bodyPoller = null;
let _closeCallback = null;

export function showModal({ title, body, width = 'max-w-lg', onClose }) {
  clearBodyPoller();
  _closeCallback = onClose || null;
  closeModal();

  const maxW = width === 'max-w-2xl' ? '42rem' : width === 'max-w-3xl' ? '48rem' : '32rem';

  const overlay = document.createElement('div');
  overlay.id = 'modal-overlay';
  overlay.style.cssText = [
    'position:fixed',
    'inset:0',
    'background:rgba(0,0,0,0.5)',
    'display:flex',
    'align-items:center',
    'justify-content:center',
    'z-index:9999',
    'padding:1rem',
    'overflow-y:auto',
  ].join(';');

  const container = document.createElement('div');
  container.style.cssText = [
    'background:#fff',
    'border-radius:0.75rem',
    'box-shadow:0 20px 60px rgba(0,0,0,0.25)',
    `width:100%`,
    `max-width:${maxW}`,
    'max-height:85vh',
    'display:flex',
    'flex-direction:column',
    'position:relative',
    'margin:auto',
  ].join(';');

  container.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:1rem 1.5rem;border-bottom:1px solid #DCDCDC;flex-shrink:0">
      <h2 style="font-size:1.1rem;font-weight:600;color:#222;margin:0">${title}</h2>
      <button id="modal-close" style="color:#787878;font-size:1.5rem;line-height:1;background:none;border:none;cursor:pointer;padding:0 0.25rem">&times;</button>
    </div>
    <div style="padding:1rem 1.5rem;overflow-y:auto;flex:1">${body}</div>
  `;

  overlay.appendChild(container);
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeModal();
  });
  container.querySelector('#modal-close').addEventListener('click', closeModal);
  document.addEventListener('keydown', onEsc);

  activeModal = { overlay };
  const firstInput = container.querySelector('input, textarea, select');
  if (firstInput) firstInput.focus();

  if (typeof body === 'function') startBodyPoller(body, container);
}

function onEsc(e) {
  if (e.key === 'Escape') closeModal();
}

export function closeModal() {
  if (activeModal) {
    activeModal.overlay.remove();
    document.body.style.overflow = '';
    document.removeEventListener('keydown', onEsc);
    activeModal = null;
  }
  clearBodyPoller();
  if (_closeCallback) { _closeCallback(); _closeCallback = null; }
}

export function updateModalBody(bodyFn) {
  if (!activeModal) return;
  clearBodyPoller();
  startBodyPoller(bodyFn, activeModal.overlay);
}

function startBodyPoller(body, overlay) {
  _bodyPoller = setInterval(() => {
    if (!document.body.contains(overlay)) { clearBodyPoller(); return; }
    const newBody = typeof body === 'function' ? body() : body;
    const content = overlay.querySelector('div:last-child');
    if (content) content.innerHTML = newBody;
  }, 5000);
  if (typeof body === 'function') body();
}

function clearBodyPoller() {
  if (_bodyPoller) { clearInterval(_bodyPoller); _bodyPoller = null; }
}

export function buildBody(fields) {
  return fields.map(f => {
    if (f.type === 'textarea') {
      return `<div class="mb-4">
        <label class="block text-sm font-medium text-brand-dark mb-1">${f.label}</label>
        <textarea name="${f.name}" ${f.rows ? `rows="${f.rows}"` : ''}
          class="input-field font-mono text-sm" ${f.required ? 'required' : ''}
          ${f.placeholder ? `placeholder="${f.placeholder}"` : ''}>${f.value || ''}</textarea>
      </div>`;
    }
    if (f.type === 'display') {
      return `<div class="mb-4">
        <label class="block text-sm font-medium text-brand-dark mb-1">${f.label}</label>
        <div class="input-field bg-gray-50">${f.value || '-'}</div>
      </div>`;
    }
    return `<div class="mb-4">
      <label class="block text-sm font-medium text-brand-dark mb-1">${f.label}</label>
      <input name="${f.name}" type="${f.type || 'text'}" value="${f.value || ''}"
        class="input-field" ${f.required ? 'required' : ''}
        ${f.placeholder ? `placeholder="${f.placeholder}"` : ''}>
    </div>`;
  }).join('');
}
