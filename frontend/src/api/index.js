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
  checkIp: (ip, port) =>
    api.get(`/tools/check-ip?ip=${encodeURIComponent(ip)}${port ? `&port=${encodeURIComponent(port)}` : ''}`),
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
  remove: (id) => api.del(`/domains/${id}`),
};

export const nodesApi = {
  list: () => api.get('/nodes'),
  refresh: () => api.post('/nodes/refresh'),
  action: (uuid, action) => api.post(`/nodes/${uuid}/${action}`),
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
  geopingerSensors: () => api.get('/settings/geopinger/sensors'),
  testTelegram: () => api.post('/settings/test-telegram'),
  testSummary: () => api.post('/settings/test-summary'),
};
