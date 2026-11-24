import { api } from './client.js';

export const authApi = {
  me: () => api.get('/auth/me'),
  login: (password) => api.post('/auth/login', { password }),
  logout: () => api.post('/auth/logout'),
};

export const dashboardApi = {
  get: () => api.get('/dashboard'),
  status: () => api.get('/system/status'),
  checkNow: () => api.post('/system/check-now'),
  check: (body) => api.post('/tools/check', body),
};

export const domainsApi = {
  list: () => api.get('/domains'),
  lookup: (name) => api.get(`/domains/lookup?name=${encodeURIComponent(name)}`),
  get: (id) => api.get(`/domains/${id}`),
  create: (data) => api.post('/domains', data),
  update: (id, data) => api.patch(`/domains/${id}`, data),
  setIps: (id, ips) => api.put(`/domains/${id}/ips`, { ips }),
  switchIp: (id, ip) => api.post(`/domains/${id}/switch`, { ip }),
  check: (id) => api.post(`/domains/${id}/check`),
  checkOneIp: (id, ip) => api.post(`/domains/${id}/ips/check`, { ip }),
  checkAllIps: (id) => api.post(`/domains/${id}/check-ips`),
  remove: (id) => api.del(`/domains/${id}`),
};

export const nodesApi = {
  list: () => api.get('/nodes'),
  refresh: () => api.post('/nodes/refresh'),
  sync: () => api.post('/nodes/sync'),
  remove: (uuid) => api.del(`/nodes/${uuid}`),
  saveOrder: (uuids) => api.put('/nodes/order', { uuids }),
};

export const eventsApi = {
  list: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') q.set(k, v);
    });
    return api.get(`/events?${q.toString()}`);
  },
  types: () => api.get('/events/types'),
};

export const settingsApi = {
  get: () => api.get('/settings'),
  update: (data) => api.put('/settings', data),
  checkersStatus: () => api.get('/settings/checkers/status'),
  integrations: () => api.get('/settings/integrations'),
  updateIntegrations: (values) => api.put('/settings/integrations', { values }),
  testIntegration: (group) => api.post(`/settings/integrations/test/${group}`),
  bschekUnits: () => api.get('/settings/bschek/units'),
  testTelegram: () => api.post('/settings/test-telegram'),
  testSummary: () => api.post('/settings/test-summary'),
};

export const investigationsApi = {
  list: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') q.set(k, v);
    });
    return api.get(`/investigations?${q.toString()}`);
  },
  start: (domainId) => api.post(`/domains/${domainId}/investigate`),
  cancel: (id) => api.post(`/investigations/${id}/cancel`),
};
