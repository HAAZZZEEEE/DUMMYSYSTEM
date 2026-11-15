import { api, mark, target } from './api.js';
import { metadata } from './actions.js';
import { fileIcon, icon } from './icons.js';
import { recordDirectoryLabel } from './record-label.js';
import { directorySorts, formatBytes } from './workspace-tools.js';

const columns = {
  type: { label: '类型', value: (entry, info) =>
    info.available === false ? '不可用' : info.navigation_only ? '仅浏览目录' : entry.kind === 'dir' ? '文件夹' : '文件' },
  modified: { label: '修改时间', value: entry => entry.modified_at?.replace('T', ' ').slice(0, 16) },
  size: { label: '大小', hint: '文件大小', value: entry => entry.size == null ? null : formatBytes(entry.size) },
  file_count: { label: '文件数', hint: '目录内直属文件的数量', value: entry => entry.file_count },
};

export function createDirectory(nav, session, actions, flash, preview) {
  const body = document.getElementById('entries-body');
  const header = body.closest('table').tHead.rows[0];
  const columnMenu = document.getElementById('directory-columns');
  let visibleColumns = [];
  let rendered = null;
  let rowGeneration = -1;
  function sortHeader(cell, label) {
    const [[ascending], [descending]] = directorySorts[cell.dataset.column];
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'directory-sort-header';
    button.textContent = label;
    button.setAttribute('aria-label', `按${label}排序`);
    button.title = cell.dataset.column === 'type' ? '按扩展名排序' : `按${label}排序`;
    button.onclick = () => nav.options({ sort: nav.state.sort === ascending ? descending : ascending });
    cell.replaceChildren(button);
  }
  sortHeader(header.querySelector('[data-column="name"]'), '名称');
  function syncPreviewSelection(value) {
    const key = value && JSON.stringify(value);
    for (const row of body.querySelectorAll('tr[data-target]')) {
      if (row.dataset.target === key) row.setAttribute('aria-current', 'true');
      else row.removeAttribute('aria-current');
    }
  }
  preview.subscribe(syncPreviewSelection);
  function render(state, layoutChanged = false) {
    if ((!state.target || state.target.root_id === 'homepage' || state.error) && columnMenu.matches(':popover-open')) {
      columnMenu.hidePopover();
    }
    for (const cell of header.querySelectorAll('[data-column]')) {
      const [[ascending], [descending]] = directorySorts[cell.dataset.column];
      if (state.sort === ascending) cell.setAttribute('aria-sort', 'ascending');
      else if (state.sort === descending) cell.setAttribute('aria-sort', 'descending');
      else cell.removeAttribute('aria-sort');
    }
    if (!layoutChanged && rendered === state.entries && rowGeneration === state.generation) {
      for (const row of body.querySelectorAll('tr[data-target]')) row.setAttribute('aria-disabled', String(state.loading));
      for (const button of body.querySelectorAll('button')) button.disabled = state.loading;
      return;
    }
    rendered = state.entries;
    rowGeneration = state.generation;
    body.replaceChildren();
    const ctx = nav.context();
    for (const entry of state.entries) {
      const snapshot = target({ ...ctx.target, relative_path: entry.relative_path });
      const info = metadata(entry);
      const row = mark(document.createElement('tr'), 'directory-entry', snapshot);
      row.className = entry.kind === 'dir' ? 'dir-row' : 'file-row';
      row.tabIndex = 0;
      row.setAttribute('aria-label', `${entry.kind === 'dir' ? '目录' : '文件'}：${entry.name}`);
      row.setAttribute('aria-disabled', String(state.loading || info.available === false));
      row.title = info.reason || (entry.kind === 'dir' ? '点击进入目录' : '按默认方式打开');
      const activate = () => {
        if (!ctx.valid() || nav.state.loading) return;
        if (info.available === false) { flash(info.reason || '此目标不可用'); return; }
        if (entry.kind === 'dir') nav.go(snapshot);
        else if (preview?.canPreview(info)) preview.open(snapshot, info);
        else actions.open(snapshot, null, info);
      };
      row.onclick = activate;
      row.onkeydown = (event) => {
        if (event.target !== row) return;
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
        if (event.key === 'ArrowDown') { event.preventDefault(); row.nextElementSibling?.focus(); }
        if (event.key === 'ArrowUp') { event.preventDefault(); row.previousElementSibling?.focus(); }
      };
      const name = document.createElement('td');
      const cell = document.createElement('div');
      cell.className = 'name-cell';
      const icon = document.createElement('span');
      icon.className = entry.kind === 'dir' ? 'folder-icon' : 'file-icon';
      icon.append(fileIcon(entry));
      icon.setAttribute('aria-hidden', 'true');
      const text = document.createElement('span');
      text.className = 'name-text';
      const record = entry.kind === 'dir' ? recordDirectoryLabel(entry.name) : null;
      text.textContent = record?.title || entry.name;
      text.title = entry.name;
      const nameDetails = document.createElement('span');
      nameDetails.className = 'entry-name';
      nameDetails.append(text);
      if (record) {
        const details = document.createElement('span');
        details.className = 'entry-record-meta';
        details.textContent = record.metadata;
        nameDetails.append(details);
      }
      cell.append(icon, nameDetails);
      name.append(cell);
      row.append(name);
      for (const key of visibleColumns) {
        const detail = document.createElement('td');
        detail.className = 'directory-detail';
        detail.dataset.column = key;
        detail.textContent = columns[key].value(entry, info) ?? '—';
        row.append(detail);
      }
      const menu = document.createElement('td');
      menu.className = 'col-act';
      const menuButton = actions.menuButton(snapshot, info, entry.name, entry.kind === 'dir'
        ? [{ id: 'browse-target', label: '进入目录', onClick: () => nav.go(snapshot),
            disabled: info.available === false, reason: info.reason }, { separator: true }]
        : preview?.canPreview(info)
          ? [{ id: 'preview-target', label: '预览文件', onClick: () => preview.open(snapshot, info),
              disabled: info.available === false, reason: info.reason }, { separator: true }]
          : []);
      menu.append(menuButton);
      row.append(menu);
      actions.bindContextMenu(row, menuButton);
      body.append(row);
    }
    syncPreviewSelection(preview.current);
    if (!state.loading && !state.error && state.target && !state.entries.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = visibleColumns.length + 2;
      cell.className = 'empty-cell';
      cell.textContent = state.filter ? '没有匹配的文件或目录' : '此目录为空';
      row.append(cell);
      body.append(row);
    }
  }
  nav.subscribe(render);
  mountColumnSettings(session, flash, visible => {
    const needCounts = visible.includes('file_count') && !visibleColumns.includes('file_count');
    visibleColumns = visible;
    header.querySelectorAll('.directory-detail').forEach(cell => cell.remove());
    for (const key of visibleColumns) {
      const cell = document.createElement('th');
      cell.scope = 'col';
      cell.className = 'directory-detail';
      cell.dataset.column = key;
      sortHeader(cell, columns[key].label);
      if (columns[key].hint) cell.title = columns[key].hint;
      header.lastElementChild.before(cell);
    }
    render(nav.state, true);
    if (needCounts && nav.state.target?.root_id && nav.state.target.root_id !== 'homepage' && !nav.state.error) {
      void nav.reload();
    }
  });
  async function load(ctx, append = false) {
    const state = nav.state;
    const request = { target: ctx.target, filter: state.filter, sort: state.sort, kind: state.kind, limit: 200 };
    if (visibleColumns.includes('file_count')) request.include_file_counts = true;
    try {
      let result;
      try {
        result = await api('list', { body: { ...request, ...(append ? { cursor: state.cursor } : {}) }, signal: ctx.signal });
      } catch (error) {
        if (!ctx.valid()) return;
        if (error.code !== 'STALE_CURSOR') throw error;
        append = false;
        state.entries = [];
        state.cursor = null;
        nav.emit();
        flash('目录分页已失效，已清空旧页并重新加载第一页。');
        result = await api('list', { body: request, signal: ctx.signal });
      }
      if (!ctx.valid()) return;
      if (!Array.isArray(result.entries)) throw new Error('目录响应缺少有效 entries。');
      state.entries = append ? [...state.entries, ...result.entries] : result.entries;
      state.resolved = { ...result, ...result.target };
      state.cursor = result.next_cursor || null;
      state.loading = false;
      state.error = null;
      nav.emit();
      session.save({ last_location: ctx.target }, ctx.valid).catch((error) => {
        if (ctx.valid()) flash(`位置保存失败：${error.message}`);
      });
    } catch (error) {
      if (!ctx.valid()) return;
      state.entries = [];
      state.cursor = null;
      state.error = error;
      state.loading = false;
      nav.emit();
    }
  }
  return { load };
}

function mountColumnSettings(session, flash, onChange) {
  const trigger = document.getElementById('directory-columns-toggle');
  const panel = document.getElementById('directory-columns');
  const options = document.getElementById('directory-column-options');
  const reset = document.getElementById('directory-columns-reset');
  const rows = new Map();
  let previous = '';
  const firstChoice = () => options.querySelector('input:not(:disabled)');

  function apply(prefs, force = false) {
    const selected = prefs.directory_columns || [];
    const key = selected.join(',');
    if (key === previous && !force) return;
    const focus = options.contains(document.activeElement) ? document.activeElement : null;
    const order = [...selected, ...[...rows.keys()].filter(name => !selected.includes(name))];
    for (const name of order) {
      const { row, check, up, down } = rows.get(name);
      const position = selected.indexOf(name);
      check.checked = position >= 0;
      up.disabled = position <= 0;
      down.disabled = position < 0 || position === selected.length - 1;
      options.append(row);
    }
    if (focus) {
      const next = focus.disabled ? focus.closest('.directory-column-option').querySelector('input') : focus;
      next.focus({ preventScroll: true });
    }
    const resetFocused = document.activeElement === reset;
    reset.disabled = !selected.length;
    if (resetFocused && reset.disabled) firstChoice().focus({ preventScroll: true });
    if (key !== previous) onChange(selected);
    previous = key;
  }

  function save(change) {
    session.save(prefs => ({ directory_columns: change(prefs.directory_columns || []) })).catch(error => {
      apply(session.preferences, true);
      flash(`目录列未保存：${error.message}`);
    });
  }

  for (const [key, column] of Object.entries(columns)) {
    const row = document.createElement('div');
    row.className = 'directory-column-option';
    const label = document.createElement('label');
    if (column.hint) label.title = column.hint;
    const check = document.createElement('input');
    check.type = 'checkbox';
    label.append(check, column.label);
    check.onchange = () => {
      const checked = check.checked;
      save(order => checked ? [...new Set([...order, key])] : order.filter(name => name !== key));
    };
    const move = (offset, text) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = offset < 0 ? 'icon-btn column-up' : 'icon-btn column-down';
      button.setAttribute('aria-label', `${column.label}${text}`);
      button.title = button.getAttribute('aria-label');
      button.append(icon('up'));
      button.onclick = () => save(order => {
        const from = order.indexOf(key);
        const to = from + offset;
        if (from < 0 || to < 0 || to >= order.length) return order;
        const next = [...order];
        next.splice(from, 1);
        next.splice(to, 0, key);
        return next;
      });
      return button;
    };
    const up = move(-1, '上移');
    const down = move(1, '下移');
    const moves = document.createElement('span');
    moves.className = 'column-moves';
    moves.append(up, down);
    row.append(label, moves);
    rows.set(key, { row, check, up, down });
  }
  reset.onclick = () => save(() => []);
  trigger.append(icon('config'));
  function positionPanel() {
    const anchor = trigger.getBoundingClientRect();
    const width = Math.min(260, window.innerWidth - 24);
    const below = window.innerHeight - anchor.bottom - 18;
    const above = below < 240 && anchor.top > below;
    panel.style.width = `${width}px`;
    panel.style.left = `${Math.max(12, Math.min(anchor.right - width, window.innerWidth - width - 12))}px`;
    panel.style.top = above ? 'auto' : `${anchor.bottom + 6}px`;
    panel.style.bottom = above ? `${window.innerHeight - anchor.top + 6}px` : 'auto';
    panel.style.maxHeight = `${Math.max(60, above ? anchor.top - 18 : below)}px`;
  }
  trigger.onclick = () => {
    if (panel.matches(':popover-open')) {
      panel.hidePopover();
      return;
    }
    positionPanel();
    panel.showPopover();
    firstChoice().focus({ preventScroll: true });
  };
  panel.addEventListener('toggle', () => {
    trigger.setAttribute('aria-expanded', String(panel.matches(':popover-open')));
  });
  panel.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    panel.hidePopover();
    trigger.focus({ preventScroll: true });
  });
  window.addEventListener('resize', () => {
    if (panel.matches(':popover-open')) positionPanel();
  });
  apply(session.preferences, true);
  session.subscribe(apply);
}
