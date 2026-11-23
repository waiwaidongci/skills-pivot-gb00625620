import {request, saveFile} from '../api/http.js';
import {session} from './session.js';

const call = (path, body) => request(path, {token:session.token, body});
export const workspace = {
  spec: null,
  datasets: [],
  runs: [],
  quotaPlans: [],
  async init() { this.spec = await request('/spec'); },
  async refresh() {
    [this.datasets, this.runs] = await Promise.all([call('/datasets'), call('/runs')]);
    try { this.quotaPlans = await call('/quota-plans'); }
    catch (error) { if (error.status === 403) this.quotaPlans = []; else throw error; }
  },
  getDataset: (id, offset = 0) => call(`/datasets/${id}?offset=${offset}`),
  getRun: id => call(`/runs/${id}`),
  getQuotaPlan: id => call(`/quota-plans/${id}`),
  upload: data => call('/datasets', data),
  start: data => call('/runs', data),
  startQuota: data => call('/quota-plans', data),
  review: (id, data) => call(`/runs/${id}/review`, data),
  audit: () => call('/audit'),
  schedules: () => call('/schedules'),
  deliveries: () => call('/deliveries'),
  schedule: data => call('/schedules', data),
  disable: id => call(`/schedules/${id}/disable`, {}),
  download: (path, filename) => saveFile(path, session.token, filename),
};
