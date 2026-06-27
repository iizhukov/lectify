import { isAuthenticated } from './auth.js';

const PUBLIC_ROUTES = ['/login', '/register', '/forgot-password', '/reset-password', '/'];

let _routerInitialized = false;

export function initRouter() {
  if (_routerInitialized) return;
  _routerInitialized = true;
  window.addEventListener('popstate', () => renderRoute());
  document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href^="/"]');
    if (link && !link.hasAttribute('download') && !link.hasAttribute('target')) {
      e.preventDefault();
      history.pushState(null, '', link.href);
      renderRoute();
    }
  });
}

export function navigate(path) {
  history.pushState(null, '', path);
  renderRoute();
}

export async function renderRoute() {
  const path = window.location.pathname;
  const isPublic = PUBLIC_ROUTES.some(r => path === r || path.startsWith(r + '/'));

  if (!isPublic && !isAuthenticated()) {
    window.location.href = '/login';
    return;
  }

  if (path === '/login' || path === '/forgot-password' || path === '/reset-password') {
    return;
  }

  try {
    const html = await fetch(path).then(r => r.text());
    const doc = new DOMParser().parseFromString(html, 'text/html');

    // Swap <main> content
    const newMain = doc.querySelector('main');
    const curMain = document.querySelector('main');
    if (newMain && curMain) {
      curMain.innerHTML = newMain.innerHTML;
    }

    // Update <title>
    if (doc.title) document.title = doc.title;

    // Re-run page scripts (only from <main> area — not sidebar/base scripts)
    curMain?.querySelectorAll('script').forEach(oldScript => {
      const s = document.createElement('script');
      s.type = oldScript.type || 'text/javascript';
      if (oldScript.src) {
        s.src = oldScript.src;
      } else {
        s.textContent = oldScript.textContent;
      }
      oldScript.replaceWith(s);
    });

    window.scrollTo(0, 0);
  } catch (e) {
    console.error('Navigation failed:', e);
  }

  highlightNav(path);
}

export function highlightNav(path) {
  let name = '';
  if (path.startsWith('/executions')) name = 'executions';
  else if (path.startsWith('/workflows')) name = 'workflows';
  else if (path.startsWith('/prompts')) name = 'prompts';
  else if (path === '/profile') name = 'profile';

  document.querySelectorAll('[data-nav]').forEach(link => {
    const isActive = link.getAttribute('data-nav') === name;
    link.classList.toggle('bg-brand-light', isActive);
    link.classList.toggle('text-brand', isActive);
    link.classList.toggle('font-semibold', isActive);
    link.classList.toggle('text-brand-dark', !isActive);
  });
}
