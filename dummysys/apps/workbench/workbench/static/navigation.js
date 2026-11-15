import { api, target } from './api.js';

export function readLocation() {
  const query = new URLSearchParams(location.search);
  if (!['project_id', 'root_id', 'relative_path'].some((key) => query.has(key))) return null;
  return target({ project_id: query.get('project_id') || '', root_id: query.get('root_id') || '',
    relative_path: query.get('relative_path') || '' });
}
export function locationURL(value) {
  const url = new URL(location.href);
  url.hash = '';
  for (const key of ['project_id', 'root_id', 'relative_path']) {
    if (value) url.searchParams.set(key, value[key] ?? '');
    else url.searchParams.delete(key);
  }
  return url.pathname + url.search;
}
export function createNavigation() {
  const listeners = new Set();
  let controller = new AbortController();
  let loader;
  let tasks = [];
  const locations = new Map();
  const pairedLocations = new Map();
  const contentLocations = new Map();
  const isPaired = (rootId) => ['docs', 'resources'].includes(rootId);
  const locationKey = (value) => JSON.stringify([value.project_id, value.root_id]);
  const state = { generation: 0, target: null, roots: [], homepage: null, loading: false, error: null,
    resolved: null, entries: [], cursor: null, filter: '', sort: 'name', kind: 'all' };
  const emit = () => listeners.forEach((fn) => fn(state));
  const context = () => {
    const generation = state.generation;
    const signal = controller.signal;
    return { generation, signal, target: state.target && target(state.target),
      valid: () => generation === state.generation && !signal.aborted };
  };
  const begin = () => {
    controller.abort();
    controller = new AbortController();
    state.generation += 1;
    return context();
  };
  function rootTarget(rootId) {
    const current = state.target;
    if (!current) return null;
    if (rootId === current.root_id) return target(current);
    const saved = locations.get(locationKey({ ...current, root_id: rootId }));
    if (!isPaired(rootId)) return saved || target({ ...current, root_id: rootId, relative_path: '' });
    const source = isPaired(current.root_id) ? current : pairedLocations.get(current.project_id);
    if (!source) return saved || target({ ...current, root_id: rootId, relative_path: '' });
    let relative = source.relative_path;
    const side = source.root_id === 'docs' ? 'docs' : 'resource';
    const other = rootId === 'docs' ? 'docs' : 'resource';
    // 已归档 Task 的文档与资源前缀可能不同，使用目录登记的配对关系。
    const task = tasks.find((item) => item[side] &&
      (relative === item[side].relative_path || relative.startsWith(`${item[side].relative_path}/`)));
    if (task?.[other]) relative = task[other].relative_path + relative.slice(task[side].relative_path.length);
    return target({ ...current, root_id: rootId, relative_path: relative });
  }
  function rememberLocation(value) {
    locations.set(locationKey(value), value);
    if (isPaired(value.root_id)) pairedLocations.set(value.project_id, value);
    if (value.root_id !== 'homepage') contentLocations.set(value.project_id, value);
  }
  function contentTarget() {
    const saved = contentLocations.get(state.target?.project_id);
    if (saved && state.roots.some((root) => root.root_id === saved.root_id)) return target(saved);
    const root = state.roots.find((item) => item.kind === 'docs') || state.roots[0];
    return root ? rootTarget(root.root_id) : null;
  }
  async function go(value, { historyMode = 'push', filter = '', refresh = false, preferHomepage = false } = {}) {
    if (historyMode !== 'none') state.kind = 'all';
    const oldProject = state.target?.project_id;
    begin();
    state.target = value ? target(value) : null;
    Object.assign(state, { loading: !!value, error: null, resolved: null, entries: [], cursor: null, filter });
    if (oldProject !== value?.project_id) tasks = [];
    if (oldProject !== value?.project_id || refresh || (value && !value.root_id)) { state.roots = []; state.homepage = null; }
    if (state.target?.root_id) rememberLocation(state.target);
    const ctx = context();
    if (historyMode !== 'none') history[`${historyMode}State`]({ workbench: true }, '', locationURL(state.target));
    emit();
    if (!value) return;
    try {
      if (!value.project_id) throw new Error('当前位置缺少项目标识，请返回首页选择项目。');
      if (refresh) {
        const catalog = await api('projects/refresh', { body: {}, signal: ctx.signal });
        if (!ctx.valid()) return;
        await nav.onCatalog?.(catalog);
        if (!ctx.valid()) return;
      }
      if (!state.roots.length) {
        const data = await api(`roots?project_id=${encodeURIComponent(value.project_id)}`, { signal: ctx.signal });
        if (!ctx.valid()) return;
        state.roots = data.roots || [];
        state.homepage = data.homepage || null;
      }
      if (!state.target.root_id || (preferHomepage && (state.homepage || state.target.root_id === 'homepage'))) {
        const root = state.homepage ? { root_id: 'homepage' }
          : state.roots.find((item) => item.kind === 'docs') || state.roots[0];
        if (!root) throw new Error('该项目没有可浏览的根目录。');
        state.target = target({ ...state.target, root_id: root.root_id, relative_path: '' });
        rememberLocation(state.target);
        ctx.target = state.target;
        history.replaceState({ workbench: true }, '', locationURL(state.target));
      }
      emit();
      if (!(state.target.root_id === 'homepage' && state.homepage)
          && !state.roots.some((root) => root.root_id === state.target.root_id)) throw new Error('本次目标的根目录不存在或已取消登记。');
      await loader(ctx);
    } catch (error) {
      if (!ctx.valid()) return;
      state.error = error;
      state.loading = false;
      emit();
    }
  }
  const nav = { state, context, emit, go, rootTarget, contentTarget,
    scopeTarget() { return isPaired(state.target?.root_id) ? state.target : pairedLocations.get(state.target?.project_id); },
    setTasks(value) { tasks = value; },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    setLoader(fn) { loader = fn; },
    up() { if (state.target?.relative_path) return go({ ...state.target, relative_path: state.target.relative_path.split('/').slice(0, -1).join('/') }); },
    reload(refresh = false) { return go(state.target, { historyMode: 'none', filter: state.filter, refresh }); },
    filter(value) { return go(state.target, { historyMode: 'none', filter: value }); },
    options(options) {
      Object.assign(state, options);
      return go(state.target, { historyMode: 'none', filter: state.filter });
    },
    async more() {
      if (state.loading || !state.cursor) return;
      const ctx = context();
      state.loading = true;
      emit();
      await loader(ctx, true);
    },
    start(last) {
      window.addEventListener('popstate', () => go(readLocation(), { historyMode: 'none' }));
      const explicit = readLocation();
      return go(explicit || last || null, { historyMode: 'replace', preferHomepage: !explicit });
    },
  };
  return nav;
}
