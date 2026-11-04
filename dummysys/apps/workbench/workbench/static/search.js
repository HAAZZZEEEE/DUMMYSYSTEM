// 主区顶部全局搜索：同时搜 项目/任务/运行/文件 的搜索条。
// 聚焦/输入展开内联下拉，空查询显示最近访问，结果按 p/t/r/文件 分组 + 过滤按钮。
// 左侧导航栏顶部的「快速跳转」（quickaccess.js）负责项目/固定/最近，与本搜索互补。
import { api, target, targetKey } from './api.js';
import { revealOption } from './interaction.js';

const $ = (id) => document.getElementById(id);
const TYPE_LABELS = { project: '项目', task: '任务', run: '运行', file: '其它' };
const FILTERS = [
  { type: null, label: '全部' },
  { type: 'project', label: '项目' },
  { type: 'task', label: '任务' },
  { type: 'run', label: '运行' },
  { type: 'file', label: '文件' },
];
const DEBOUNCE_MS = 120;

export function createSearch(nav, session, flash, qa, preview) {
  const input = $('global-search');
  const wrap = $('search-wrap');
  const popover = $('search-popover');
  const filters = $('search-filters');
  const resultsHost = $('search-results');
  const label = qa.helpers.label;
  const meta = qa.helpers.meta;
  const validLocations = qa.helpers.validLocations;
  const rootName = qa.helpers.rootName;
  let types = null; // null = 全部
  let results = [];
  let selected = 0;
  let generation = 0;
  let timer = null;
  let open = false;
  let controller = null;

  function openPopover() {
    open = true;
    popover.classList.add('open');
    input.setAttribute('aria-expanded', 'true');
    render();
  }
  function closePopover() {
    open = false;
    popover.classList.remove('open');
    selected = 0;
    generation += 1;
    clearTimeout(timer);
    controller?.abort();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  function toggleOpen() { open ? closePopover() : openPopover(); }

  function buildQuery() {
    const params = new URLSearchParams();
    const q = input.value.trim();
    if (q) params.set('q', q);
    if (types) params.set('types', types);
    return params.toString();
  }

  async function runSearch() {
    const gen = ++generation;
    const params = buildQuery();
    controller?.abort();
    controller = new AbortController();
    try {
      const data = await api(`search?${params}`, { signal: controller.signal });
      if (gen !== generation || !open) return;
      results = data.results || [];
      selected = 0;
      renderResults();
    } catch (error) {
      if (gen !== generation || !open || error.name === 'AbortError') return;
      flash(`搜索失败：${error.message}`);
    }
  }

  function debouncedSearch() {
    clearTimeout(timer);
    generation += 1;
    controller?.abort();
    results = [];
    timer = setTimeout(() => { if (open) void runSearch(); }, DEBOUNCE_MS);
  }

  // ---- 渲染 ----

  function resultRow(item, index) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'search-result';
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(index === selected));
    row.dataset.index = String(index);
    row.tabIndex = -1;
    const badge = document.createElement('span');
    badge.className = `search-badge type-${item.type}`;
    badge.textContent = TYPE_LABELS[item.type] || item.type;
    const body = document.createElement('span');
    body.className = 'search-result-body';
    const title = document.createElement('span');
    title.className = 'search-result-title';
    title.textContent = item.title || item.name;
    const detail = document.createElement('span');
    detail.className = 'search-result-meta';
    detail.textContent = item.meta || item.project_title || '';
    body.append(title, detail);
    row.append(badge, body);
    row.onmouseenter = () => { selected = index; highlight(); };
    row.onclick = () => { select(index); };
    return row;
  }

  function renderResults() {
    const host = resultsHost;
    host.replaceChildren();
    input.removeAttribute('aria-activedescendant');
    if (!results.length) {
      const empty = document.createElement('p');
      empty.className = 'search-empty';
      empty.textContent = '没有匹配的 项目 / 任务 / 运行 / 文件。';
      host.append(empty);
      return;
    }
    let currentType = null;
    for (let i = 0; i < results.length; i += 1) {
      const item = results[i];
      if (item.type !== currentType) {
        currentType = item.type;
        const group = document.createElement('div');
        group.className = 'search-group';
        const caption = document.createElement('div');
        caption.className = 'search-caption';
        caption.textContent = TYPE_LABELS[item.type] || item.type;
        group.append(caption, resultRow(item, i));
        host.append(group);
      } else {
        host.lastElementChild.append(resultRow(item, i));
      }
    }
    highlight();
  }

  function renderRecents() {
    const host = resultsHost;
    host.replaceChildren();
    input.removeAttribute('aria-activedescendant');
    const values = validLocations('recent_locations');
    if (!values.length) {
      const empty = document.createElement('p');
      empty.className = 'search-empty';
      empty.textContent = '还没有最近访问。输入关键词搜索项目、任务、运行或文件。';
      host.append(empty);
      return;
    }
    const group = document.createElement('div');
    group.className = 'search-group';
    const caption = document.createElement('div');
    caption.className = 'search-caption';
    caption.textContent = '最近访问';
    group.append(caption);
    values.forEach((value, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'search-result';
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(index === selected));
      row.dataset.index = String(index);
      row.tabIndex = -1;
      const badge = document.createElement('span');
      badge.className = 'search-badge type-loc';
      badge.textContent = rootName(value.root_id) || '项目';
      const body = document.createElement('span');
      body.className = 'search-result-body';
      const title = document.createElement('span');
      title.className = 'search-result-title';
      title.textContent = label(value);
      const detail = document.createElement('span');
      detail.className = 'search-result-meta';
      detail.textContent = meta(value);
      body.append(title, detail);
      row.append(badge, body);
      row.onmouseenter = () => { selected = index; highlight(); };
      row.onclick = () => { selectRecent(value); };
      group.append(row);
    });
    host.append(group);
    highlight();
  }

  function render() {
    const query = input.value.trim();
    if (!open) return;
    renderFilters();
    if (!query) { results = []; selected = 0; renderRecents(); }
    else renderResults();
  }

  function renderFilters() {
    filters.replaceChildren();
    for (const spec of FILTERS) {
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = `search-filter${(spec.type === types) ? ' active' : ''}`;
      pill.textContent = spec.label;
      pill.dataset.type = spec.type === null ? 'all' : spec.type;
      pill.setAttribute('aria-pressed', String(spec.type === types));
      pill.onclick = () => {
        types = spec.type;
        selected = 0;
        if (input.value.trim()) debouncedSearch();
        else { results = []; renderRecents(); }
        renderFilters();
        filters.querySelector(`[data-type="${spec.type || 'all'}"]`)?.focus();
      };
      filters.append(pill);
    }
  }

  function highlight() {
    if (!open) return;
    const options = [...resultsHost.querySelectorAll('[role="option"]')];
    options.forEach((item, index) => item.setAttribute('aria-selected', String(index === selected)));
    if (options[selected]) {
      input.setAttribute('aria-activedescendant', `search-option-${selected}`);
      options[selected].id = `search-option-${selected}`;
      revealOption(resultsHost, options[selected]);
    }
  }

  async function select(index) {
    const item = results[index];
    if (!item) return;
    closePopover();
    if (item.kind !== 'file') { nav.go(item.target); return; }
    // 文件不是目录：先定位父目录，成功后才预览，晚到操作不得跨导航打开。
    const value = target(item.target);
    const parent = { ...value, relative_path: value.relative_path.split('/').slice(0, -1).join('/') };
    const pending = nav.go(parent);
    const ctx = nav.context();
    await pending;
    if (!ctx.valid() || nav.state.error) return;
    const row = [...document.querySelectorAll('[data-testid="directory-entry"]')]
      .find(el => el.dataset.target === targetKey(value));
    row?.focus({ preventScroll: true });
    if (preview?.canPreview(item)) {
      if ($('btn-focus')?.getAttribute('aria-pressed') === 'true') $('btn-focus').click();
      await preview.open(value, item);
    } else flash(`已定位所在目录：${item.name || item.title}`);
  }
  function selectRecent(value) {
    closePopover();
    nav.go(value);
  }

  // ---- 事件 ----

  function wire() {
    renderFilters();
    wrap.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return;
      event.preventDefault();
      input.focus();
      closePopover();
    });
    input.addEventListener('focus', openPopover);
    input.addEventListener('input', () => { selected = 0; openPopover(); debouncedSearch(); });
    input.addEventListener('keydown', (event) => {
      if (event.isComposing) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const total = input.value.trim() ? results.length : validLocations('recent_locations').length;
        if (!total) return;
        selected = (selected + (event.key === 'ArrowDown' ? 1 : -1) + total) % total;
        highlight();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (!open) return;
        if (input.value.trim()) select(selected);
        else {
          const recents = validLocations('recent_locations');
          if (recents[selected]) selectRecent(recents[selected]);
        }
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closePopover();
        input.blur();
      } else if (event.key === 'Tab') {
        closePopover();
      }
    });
    document.addEventListener('pointerdown', (event) => {
      if (open && !wrap.contains(event.target)) closePopover();
    });

    // Ctrl+Shift+F 聚焦主区全局搜索（Ctrl+K 由左侧快速跳转 quickaccess.js 接管）。
    document.addEventListener('keydown', (event) => {
      if (event.defaultPrevented || event.altKey || event.metaKey) return;
      if (event.key === 'Escape' && open && !document.querySelector('dialog[open]')) {
        event.preventDefault();
        closePopover();
        return;
      }
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'f') {
        if (document.querySelector('dialog[open]')) return;
        event.preventDefault();
        if (!open) openPopover();
        input.focus();
      }
    });

    nav.subscribe(() => { if (open && !input.value.trim()) renderRecents(); });
    session.subscribe(() => { if (open && !input.value.trim()) renderRecents(); });
  }

  return { wire };
}
