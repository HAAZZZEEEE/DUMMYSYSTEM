import { api, mark, target } from './api.js';
import { metadata } from './actions.js';
import { fileIcon } from './icons.js';
import { recordDirectoryLabel } from './record-label.js';

export function createDirectory(nav, session, actions, flash, preview) {
  const body = document.getElementById('entries-body');
  let rendered = null;
  let rowGeneration = -1;
  function syncPreviewSelection(value) {
    const key = value && JSON.stringify(value);
    for (const row of body.querySelectorAll('tr[data-target]')) {
      if (row.dataset.target === key) row.setAttribute('aria-current', 'true');
      else row.removeAttribute('aria-current');
    }
  }
  preview.subscribe(syncPreviewSelection);
  function render(state) {
    if (rendered === state.entries && rowGeneration === state.generation) {
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
      const type = document.createElement('td');
      type.className = 'type';
      type.textContent = info.available === false ? '不可用' : info.navigation_only ? '仅浏览目录' : entry.kind === 'dir' ? '文件夹' : '文件';
      const modified = document.createElement('td');
      modified.className = 'mod';
      modified.textContent = (entry.modified_at || '').replace('T', ' ').slice(0, 16);
      const compactInfo = document.createElement('span');
      compactInfo.className = 'entry-compact-meta';
      compactInfo.textContent = [type.textContent, modified.textContent].filter(Boolean).join(' · ');
      nameDetails.append(compactInfo);
      const menu = document.createElement('td');
      const menuButton = actions.menuButton(snapshot, info, entry.name, entry.kind === 'dir'
        ? [{ id: 'browse-target', label: '进入目录', onClick: () => nav.go(snapshot),
            disabled: info.available === false, reason: info.reason }, { separator: true }]
        : preview?.canPreview(info)
          ? [{ id: 'preview-target', label: '预览文件', onClick: () => preview.open(snapshot, info),
              disabled: info.available === false, reason: info.reason }, { separator: true }]
          : []);
      menu.append(menuButton);
      row.append(name, type, modified, menu);
      actions.bindContextMenu(row, menuButton);
      body.append(row);
    }
    syncPreviewSelection(preview.current);
    if (!state.loading && !state.error && state.target && !state.entries.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 4;
      cell.className = 'empty-cell';
      cell.textContent = state.filter ? '没有匹配的文件或目录' : '此目录为空';
      row.append(cell);
      body.append(row);
    }
  }
  nav.subscribe(render);
  async function load(ctx, append = false) {
    const state = nav.state;
    try {
      let result;
      try {
        result = await api('list', { body: { target: ctx.target, filter: state.filter,
          sort: state.sort, kind: state.kind,
          limit: 200, ...(append ? { cursor: state.cursor } : {}) }, signal: ctx.signal });
      } catch (error) {
        if (!ctx.valid()) return;
        if (error.code !== 'STALE_CURSOR') throw error;
        append = false;
        state.entries = [];
        state.cursor = null;
        nav.emit();
        flash('目录分页已失效，已清空旧页并重新加载第一页。');
        result = await api('list', { body: { target: ctx.target, filter: state.filter,
          sort: state.sort, kind: state.kind, limit: 200 }, signal: ctx.signal });
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
