import { record } from './diagnostics.js';
// 所有 HTTP 调用共享中文错误、JSON 校验与会话凭据。
let csrf = '';
export function setCSRF(value) {
  csrf = value;
}
export function target(value) {
  return Object.freeze({ project_id: value.project_id, root_id: value.root_id,
    relative_path: value.relative_path ?? '' });
}
export const targetKey = (value) => JSON.stringify(target(value));
export function mark(element, id, value) {
  element.dataset.testid = id;
  if (value) element.dataset.target = targetKey(value);
  return element;
}
export async function api(path, { body, method = body === undefined ? 'GET' : 'POST', onResponse, ...options } = {}) {
  let res;
  const started = performance.now();
  try {
    try {
      res = await fetch(`/api/v1/${path}`, { ...options, method, credentials: 'same-origin',
        headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(method === 'GET' ? {} : { 'X-CSRF-Token': csrf }), ...options.headers },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('无法连接本机工作台服务，请重试。');
    }
    let payload;
    try { payload = await res.json(); } catch {
      if (options.signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
      throw Object.assign(new Error(`服务返回了无效 JSON（HTTP ${res.status}）。`), { status: res.status });
    }
    if (!res.ok || payload?.error) {
      const message = payload?.error?.message;
      throw Object.assign(new Error(message && /[\u3400-\u9fff]/.test(message) ? message : `请求失败（HTTP ${res.status}），请重试。`),
        { status: res.status, code: payload?.error?.code,
          diagnostic_id: payload?.error?.details?.diagnostic_id || res.headers.get('X-Diagnostic-ID'),
          next_action: payload?.error?.next_action, retry: payload?.error?.details?.retry, details: payload?.error?.details });
    }
    if (!payload || typeof payload !== 'object' || !Object.hasOwn(payload, 'data') || payload.data === null) {
      throw new Error('服务响应缺少有效 data，请检查接口。');
    }
    onResponse?.(res);
    return payload.data;
  } finally {
    record('request', path, performance.now() - started, res?.status, res?.headers.get('X-Diagnostic-ID'));
  }
}
