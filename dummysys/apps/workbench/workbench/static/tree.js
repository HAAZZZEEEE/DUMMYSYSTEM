import { api, mark, target, targetKey } from './api.js';
import { metadata } from './actions.js';
import { fileIcon, icon } from './icons.js';
import { preserveNavScroll } from './interaction.js';

const canonical = (value) => typeof value === 'string' ? value.replaceAll('\\', '/').replace(/\/+$/, '').toLowerCase() : '';
const hideKey = (rootId, name) => `${rootId}\x1f${name}`;
export function createTree(nav, actions, flash, preview) {
  const host = mark(document.createElement('div'), 'project-tree');
  host.className = 'project-tree';
  host.setAttribute('role', 'tree');
  host.setAttribute('aria-label', '项目目录树');
  let project = null;
  let roots = [];
  let generation = -1;
  let syncing = -1;
  let hidden = new Set();
  const nodes = new Map();
  let sort = 'name';
  function nodeFor(value, info, parent = null) {
    const snapshot = target(value);
    const key = targetKey(snapshot);
    let node = nodes.get(key);
    if (!node) {
      node = { target: snapshot, key, parent, info: {}, children: [], expanded: false,
        loaded: false, loading: false, cursor: null, error: null, controller: null, version: 0 };
      nodes.set(key, node);
    }
    node.info = { ...node.info, ...metadata(info) };
    node.parent = parent;
    return node;
  }
  function loop(node) {
    const path = canonical(node.info.canonical_path);
    if (!path) return false;
    for (let parent = node.parent; parent; parent = parent.parent) {
      if (path === canonical(parent.info.canonical_path)) return true;
    }
    return false;
  }
  function cancel(node) {
    node.controller?.abort();
    node.version += 1;
    node.loading = false;
  }
  async function load(node, more = false) {
    if (node.loading || loop(node) || node.info.available === false) return;
    cancel(node);
    const controller = new AbortController();
    node.controller = controller;
    const version = node.version;
    const ctx = nav.context();
    const valid = () => ctx.valid() && node.version === version && !controller.signal.aborted && nodes.get(node.key) === node;
    node.loading = true;
    node.error = null;
    render();
    try {
      let data;
      try {
        data = await api('list', { body: { target: node.target, sort, limit: 200, ...(more ? { cursor: node.cursor } : {}) }, signal: controller.signal });
      } catch (error) {
        if (!valid()) return;
        if (error.code !== 'STALE_CURSOR') throw error;
        more = false;
        node.children = [];
        node.cursor = null;
        node.loaded = false;
        render();
        flash('树目录分页已失效，正在重新加载第一页。');
        data = await api('list', { body: { target: node.target, sort, limit: 200 }, signal: controller.signal });
      }
      if (!valid()) return;
      if (!Array.isArray(data.entries)) throw new Error('树目录响应缺少有效 entries。');
      node.info = { ...node.info, ...metadata(data) };
      if (loop(node)) {
        node.children = [];
        node.cursor = null;
      } else {
        const entries = data.entries.filter((entry) =>
          !hidden.has(hideKey(node.target.root_id, entry.relative_path)));
        const children = entries.map((entry) => nodeFor({ ...node.target, relative_path: entry.relative_path }, entry, node));
        node.children = more ? [...new Map([...node.children, ...children].map((child) => [child.key, child])).values()] : children;
        node.cursor = data.next_cursor || null;
      }
      node.loaded = true;
    } catch (error) {
      if (!valid()) return;
      node.error = error.message;
    } finally {
      if (valid()) { node.loading = false; render(); }
    }
  }
  async function expand(node) {
    if (loop(node) || node.info.available === false) return;
    node.expanded = true;
    render();
    if (!node.loaded && !node.loading) await load(node);
  }
  function collapse(node) {
    node.expanded = false;
    const cancelBranch = (item) => { cancel(item); item.children.forEach(cancelBranch); };
    cancelBranch(node);
    render();
  }
  function activate(node) {
    if (nav.state.loading) return;
    if (node.info.available === false) { flash(node.info.reason || '此目标不可用'); return; }
    if (node.info.kind === 'dir') {
      const selected = nav.state.target && targetKey(nav.state.target) === node.key;
      // 高亮（当前）目录再次点击折叠/展开，不再重复导航。
      if (selected) { node.expanded ? collapse(node) : expand(node); return; }
      nav.go(node.target);
      return;
    }
    if (preview?.canPreview(node.info)) { preview.open(node.target, node.info); return; }
    actions.open(node.target, null, node.info);
  }
  function focusNode(key) {
    [...host.querySelectorAll('[role="treeitem"]')].find((row) => row.dataset.target === key)?.focus();
  }
  function render() {
    preserveNavScroll(host, renderContent);
  }

  function renderContent() {
    const focused = host.contains(document.activeElement) ? document.activeElement : null;
    const focusKey = focused?.dataset.target;
    const focusTest = focused?.dataset.testid;
    host.replaceChildren();
    const selected = nav.state.target && targetKey(nav.state.target);
    function branch(node, depth) {
      const wrap = document.createElement('div');
      wrap.setAttribute('role', 'none');
      const row = mark(document.createElement('div'), 'tree-node', node.target);
      row.setAttribute('role', 'treeitem');
      row.setAttribute('aria-level', String(depth));
      row.setAttribute('aria-selected', String(node.key === selected));
      row.setAttribute('aria-label', `${node.info.kind === 'dir' ? '目录' : '文件'}：${node.info.name || node.info.label}`);
      row.className = 'tree-row';
      row.tabIndex = node.key === selected ? 0 : -1;
      if (node.info.kind === 'dir') row.setAttribute('aria-expanded', String(node.expanded));
      row.setAttribute('aria-busy', String(node.loading));
      row.setAttribute('aria-disabled', String(node.info.available === false));
      row.style.setProperty('--tree-depth', depth - 1);
      const arrow = mark(document.createElement('button'), 'tree-toggle', node.target);
      arrow.type = 'button';
      arrow.className = 'tree-toggle';
      if (node.info.kind === 'dir') arrow.append(icon('chevron'));
      arrow.setAttribute('aria-label', `${node.expanded ? '折叠' : '展开'}：${node.info.name || node.info.label}`);
      arrow.disabled = node.info.kind !== 'dir' || loop(node) || node.info.available === false;
      arrow.tabIndex = -1;
      arrow.onclick = (event) => { event.stopPropagation(); node.expanded ? collapse(node) : expand(node); };
      arrow.onkeydown = (event) => event.stopPropagation();
      const label = document.createElement('span');
      label.className = 'tree-label';
      label.textContent = node.info.name || node.info.label || node.target.root_id;
      label.prepend(fileIcon(node.info));
      row.title = loop(node) ? '目录链接指向祖先，已停止重复展开' : node.info.reason || node.info.native_path || label.textContent;
      const menu = actions.menuButton(node.target, node.info, label.textContent,
        node.info.kind === 'dir'
          ? [{ id: 'browse-target', label: '进入目录', onClick: () => activate(node),
              disabled: node.info.available === false, reason: node.info.reason }, { separator: true }]
          : preview?.canPreview(node.info)
            ? [{ id: 'preview-target', label: '预览文件', onClick: () => preview.open(node.target, node.info),
                disabled: node.info.available === false, reason: node.info.reason }, { separator: true }]
            : []);
      menu.disabled = nav.state.loading;
      row.append(arrow, label, menu);
      actions.bindContextMenu(row, menu);
      row.onclick = (event) => { event.stopPropagation(); activate(node); };
      row.onkeydown = async (event) => {
        if (event.target !== row) return;
        const rows = [...host.querySelectorAll('[role="treeitem"]')];
        const index = rows.indexOf(row);
        if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Enter', ' ', 'Home', 'End'].includes(event.key)) event.preventDefault();
        if (event.key === 'ArrowDown') rows[index + 1]?.focus();
        if (event.key === 'ArrowUp') rows[index - 1]?.focus();
        if (event.key === 'Home') rows[0]?.focus();
        if (event.key === 'End') rows.at(-1)?.focus();
        if (event.key === 'ArrowLeft') {
          if (node.expanded) collapse(node);
          else if (node.parent) focusNode(node.parent.key);
        }
        if (event.key === 'ArrowRight' && node.info.kind === 'dir') {
          if (!node.expanded) await expand(node);
          else if (node.children[0]) focusNode(node.children[0].key);
        }
        if (event.key === 'Enter') activate(node);
        if (event.key === ' ') {
          if (node.info.kind === 'dir') node.expanded ? collapse(node) : expand(node);
          else activate(node);
        }
      };
      wrap.append(row);
      if (node.expanded) {
        const group = document.createElement('div');
        group.setAttribute('role', 'group');
        row.append(group);
        // group 属于 treeitem；视觉行与子树使用 CSS grid 分隔。
        for (const child of node.children) group.append(branch(child, depth + 1));
        if (node.loading || node.error || loop(node) || (node.loaded && !node.children.length)) {
          const status = mark(document.createElement('div'), 'tree-status', node.target);
          status.className = 'tree-status';
          status.setAttribute('role', node.error ? 'alert' : 'status');
          status.textContent = node.loading ? '加载中…' : node.error || (loop(node) ? '已阻止祖先循环' : '空目录');
          group.append(status);
        }
        if (node.error || node.cursor) {
          const more = mark(document.createElement('button'), node.error ? 'tree-retry' : 'tree-more', node.target);
          more.type = 'button';
          more.className = 'tree-more';
          more.textContent = node.error ? '重试' : '加载更多';
          more.setAttribute('aria-label', `${more.textContent}：${label.textContent}`);
          more.disabled = node.loading;
          more.onclick = (event) => { event.stopPropagation(); load(node, !!node.cursor); };
          more.onkeydown = (event) => event.stopPropagation();
          group.append(more);
        }
      }
      return wrap;
    }
    for (const root of roots) host.append(branch(root, 1));
    actions.syncMenu();
    if (!host.querySelector('[role="treeitem"][tabindex="0"]')) host.querySelector('[role="treeitem"]')?.setAttribute('tabindex', '0');
    if (focusKey) [...host.querySelectorAll('[data-target]')].find((row) => row.dataset.target === focusKey && row.dataset.testid === focusTest)?.focus({ preventScroll: true });
    // 供工具栏单按钮同步展开/折叠态。
    host.dispatchEvent(new CustomEvent('nav-expand-state', { bubbles: true }));
  }
  async function reveal(ctx) {
    let node = roots.find((item) => item.target.root_id === ctx.target.root_id);
    if (!node) return;
    const parts = ctx.target.relative_path.split('/').filter(Boolean);
    for (let index = 0; index <= parts.length; index += 1) {
      if (!ctx.valid() || !node || loop(node)) return;
      await expand(node);
      if (!ctx.valid() || node.error || node.loading || index === parts.length) return;
      const path = parts.slice(0, index + 1).join('/');
      let child = node.children.find((item) => item.target.relative_path === path);
      while (!child && node.cursor && ctx.valid()) {
        const cursor = JSON.stringify(node.cursor);
        await load(node, true);
        if (node.error || node.loading || !ctx.valid()) return;
        child = node.children.find((item) => item.target.relative_path === path);
        if (cursor === JSON.stringify(node.cursor)) break;
      }
      node = child;
    }
  }
  nav.subscribe((state) => {
    if (generation !== state.generation) {
      generation = state.generation;
      syncing = -1;
      nodes.forEach(cancel);
    }
    if (project !== state.target?.project_id || !state.roots.length) {
      nodes.forEach(cancel);
      nodes.clear();
      roots = [];
      project = state.target?.project_id;
    }
    if (state.target && state.roots.length) roots = state.roots.map((root) => nodeFor({ project_id: project, root_id: root.root_id, relative_path: '' }, { ...root, kind: 'dir' }));
    render();
    if (state.target && !state.loading && !state.error && syncing !== generation) {
      syncing = generation;
      const ctx = nav.context();
      reveal(ctx).then(() => {
        if (!ctx.valid()) return;
        // 导航取消过的已展开节点使用各自请求恢复，不共享主目录控制器。
        for (const node of nodes.values()) {
          let visible = true;
          for (let parent = node.parent; parent; parent = parent.parent) {
            if (!parent.expanded) visible = false;
          }
          if (visible && node.expanded && !node.loaded && !node.loading && !node.error) load(node);
        }
      });
    }
  });
  return { host, invalidate(value) {
    const node = nodes.get(targetKey(value));
    if (node) { cancel(node); node.children = []; node.cursor = null; node.loaded = false; node.error = null; }
  },
  setSort(mode) {
    const next = { default: 'name', name: 'name', name_desc: 'name_desc', newest: 'modified', oldest: 'modified_asc' }[mode] || 'name';
    if (sort === next) return;
    sort = next;
    for (const node of nodes.values()) { cancel(node); node.children = []; node.cursor = null; node.loaded = false; node.error = null; }
    syncing = -1;
    nav.emit();
  },
  setHidden(list) {
    hidden = new Set((list || []).map((item) => hideKey(item.root_id, item.relative_path)));
    for (const node of nodes.values()) { node.loaded = false; node.children = []; node.cursor = null; }
    render();
  },
  expandAll() {
    for (const node of nodes.values()) {
      if (node.info.kind === 'dir' && !loop(node) && node.info.available !== false) node.expanded = true;
    }
    render();
  },
  collapseAll() {
    for (const node of nodes.values()) node.expanded = false;
    render();
  },
  hasExpanded() {
    for (const node of nodes.values()) if (node.expanded) return true;
    return false;
  } };
}
