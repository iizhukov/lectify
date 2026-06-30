import { getToken } from './auth.js';

const BASE = 'http://localhost:5001';

function headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  const token = getToken();
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function handle(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

async function req(method, path, body) {
  const opts = { method, headers: headers() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(BASE + path, opts);
  return handle(res);
}

export const api = {
  auth: {
    login: (username, password) => req('POST', '/api/auth/login', { username, password }),
    register: (username, email, password, full_name) => req('POST', '/api/auth/register', { username, email, password, full_name }),
    logout: () => req('POST', '/api/auth/logout', {}),
    forgotPassword: (email) => req('POST', '/api/auth/forgot-password', { email }),
    resetPassword: (token, password) => req('POST', '/api/auth/reset-password', { token, password }),
  },

  profile: {
    get: () => req('GET', '/api/profile'),
    update: (data) => req('PUT', '/api/profile', data),
    changePassword: (old_password, new_password) =>
      req('PUT', '/api/profile/password', { current_password: old_password, new_password }),
  },

  workflows: {
    list: () => req('GET', '/api/workflows'),
    get: (id) => req('GET', `/api/workflows/${id}`),
    create: (data) => req('POST', '/api/workflows', data),
    update: (id, data) => req('PUT', `/api/workflows/${id}`, data),
    delete: (id) => req('DELETE', `/api/workflows/${id}`),
    execute: (id, data) => req('POST', `/api/workflows/${id}/execute`, data),
  },

  executions: {
    list: () => req('GET', '/api/workflows/executions'),
    get: (id) => req('GET', `/api/workflows/executions/${id}`),
    getNodes: (id) => req('GET', `/api/workflows/executions/${id}/nodes`),
    restart: (id) => req('POST', `/api/workflows/executions/${id}/restart`, {}),
    cancel: (id) => req('POST', `/api/workflows/executions/${id}/cancel`, {}),
  },

  nodes: {
    list: () => req('GET', '/api/nodes'),
    plugins: () => req('GET', '/api/nodes/plugins'),
    getDetail: (execId, nodeId) => req('GET', `/api/workflows/executions/${execId}/nodes/${nodeId}`),
    logs: (execId, nodeId) => req('GET', `/api/workflows/executions/${execId}/nodes/${nodeId}/logs`),
  },

  artifacts: {
    list: (execId) => req('GET', `/api/workflows/executions/${execId}/artifacts`),
  },

  prompts: {
    list: () => req('GET', '/api/prompts'),
    get: (id) => req('GET', `/api/prompts/${id}`),
    create: (data) => req('POST', '/api/prompts', data),
    update: (id, data) => req('PUT', `/api/prompts/${id}`, data),
    delete: (id) => req('DELETE', `/api/prompts/${id}`),
    render: (id, params) => req('GET', `/api/prompts/${id}/render?${params}`),
  },

  files: {
    list: () => req('GET', '/api/files'),
    get: (id) => req('GET', `/api/files/${id}`),
    upload: (formData) => {
      const opts = { method: 'POST', headers: { Authorization: `Bearer ${getToken()}` } };
      opts.body = formData;
      delete opts.headers['Content-Type'];
      return fetch(BASE + '/api/files', opts).then(handle);
    },
  },
};
