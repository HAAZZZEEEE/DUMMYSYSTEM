import { api, setCSRF } from './api.js';

export function createSession() {
  let preferences = {};
  let queue = Promise.resolve();
  const listeners = new Set();
  const emit = () => listeners.forEach((fn) => fn(preferences));
  let revision;
  const response = (res) => { revision = res.headers.get('ETag'); };
  const read = () => api('preferences', { onResponse: response });
  return {
    get preferences() { return preferences; },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    async bootstrap() {
      const token = new URLSearchParams(location.hash.slice(1)).get('token');
      if (location.hash) history.replaceState(history.state, '', location.pathname + location.search);
      const authenticated = token
        ? await api('session', { body: { bootstrap_token: token } }) : await api('session');
      setCSRF(authenticated.csrf || '');
      const [prefs, catalog] = await Promise.all([read(), api('projects')]);
      preferences = prefs;
      emit();
      return catalog;
    },
    // 串行 PATCH 保留字段合并语义，过时代次的待发送位置写入直接跳过。
    save(patchOrFactory, valid = () => true) {
      const job = queue.then(async () => {
        for (let attempt = 0; attempt < 4; attempt++) {
          if (!valid()) return;
          const patch = typeof patchOrFactory === 'function' ? patchOrFactory(preferences) : patchOrFactory;
          if (!patch) return;
          try {
            const result = await api('preferences', { method: 'PATCH', body: patch,
              headers: revision ? { 'If-Match': revision } : {}, onResponse: response });
            preferences = result;
            emit();
            return result;
          } catch (error) {
            if (error.code !== 'PREFERENCE_CONFLICT' || attempt === 3) throw error;
            preferences = await read();
            emit();
          }
        }
      });
      queue = job.catch(() => {});
      return job;
    },
  };
}
