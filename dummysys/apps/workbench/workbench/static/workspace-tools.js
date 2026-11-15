import { commandPressed, primaryKey, isMac } from './platform-ui.js';
// 工作区效率控件；导航数据仍由 navigation/directory 拥有。
import { isEditing } from './interaction.js';
import { icon } from './icons.js';

const $ = (id) => document.getElementById(id);
function button(id, text, action) {
  const el = document.createElement('button');
  el.type = 'button'; el.id = id; el.className = 'btn ghost';
  el.textContent = text; el.onclick = action;
  return el;
}
function select(id, label, options, change) {
  const el = document.createElement('select');
  el.id = id; el.setAttribute('aria-label', label); el.title = label;
  for (const [value, text] of options) el.add(new Option(text, value));
  el.onchange = () => change(el.value);
  return el;
}
export function formatBytes(value) {
  for (const [unit, factor] of [['TB', 1024 ** 4], ['GB', 1024 ** 3], ['MB', 1024 ** 2], ['KB', 1024]]) {
    if (value >= factor) return `${(value / factor).toFixed(1)} ${unit}`;
  }
  return `${value} B`;
}

export function createWorkspaceTools(nav, session, flash) {
  const tools = document.createElement('div');
  tools.className = 'directory-tools'; tools.id = 'directory-tools';
  tools.setAttribute('role', 'group'); tools.setAttribute('aria-label', '目录显示选项');
  const kind = select('directory-kind', '筛选条目类型', [['all', '全部类型'], ['dir', '仅文件夹'], ['file', '仅文件']],
    value => nav.options({ kind: value }));
  const sort = select('directory-sort', '目录排序', [['name', '名称 A → Z'], ['name_desc', '名称 Z → A'],
    ['modified', '最近修改优先'], ['type', '文件类型']], value => nav.options({ sort: value }));
  const reset = button('directory-reset', '清除筛选', () => {
    nav.options({ kind: 'all', filter: '' }); $('dir-filter').focus();
  });
  reset.className = 'icon-btn hidden';
  reset.setAttribute('aria-label', '清除筛选');
  reset.title = '清除筛选';
  reset.replaceChildren(icon('xmark'));
  tools.append(kind, sort);
  $('pane-toolbar').prepend(tools);
  $('dir-filter').after(reset);
  $('dir-filter-icon').append(icon('search'));
  const status = document.createElement('div');
  status.id = 'directory-status'; status.className = 'directory-status';
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  $('dir-view').after(status);
  nav.subscribe(state => {
    const available = !!state.target && state.target.root_id !== 'homepage' && !state.error;
    tools.classList.toggle('hidden', !available);
    status.classList.toggle('hidden', !available);
    kind.value = state.kind; sort.value = state.sort;
    kind.disabled = sort.disabled = !available || state.loading;
    reset.classList.toggle('hidden', !state.filter && state.kind === 'all');
    const counts = state.resolved?.summary;
    status.textContent = state.loading ? '正在读取目录…' : counts
      ? `${state.entries.length} / ${counts.total} 项 · ${counts.directories} 个文件夹 · ${counts.files} 个文件 · ${formatBytes(counts.bytes)}${state.cursor ? ' · 还有更多' : ''}` : '';
    status.title = '当前筛选结果的总计；文件大小只统计本层文件，不递归计算子目录。';
  });

  let focus = false;
  const toggleFocus = () => {
    focus = !focus;
    document.body.classList.toggle('workspace-focus', focus);
    if (focus) $('workspace-layout').dataset.mobileView = 'browser';
    focusButton.setAttribute('aria-label', focus ? '退出专注' : '专注');
    focusButton.setAttribute('aria-pressed', String(focus));
    focusButton.focus();
  };
  const focusButton = button('btn-focus', '专注', toggleFocus);
  focusButton.title = `专注模式：收起导航与预览（${primaryKey}+Shift+L）`;
  focusButton.setAttribute('aria-pressed', 'false');
  focusButton.setAttribute('aria-label', '专注');
  focusButton.className = 'icon-btn';
  focusButton.replaceChildren(icon('focus'));
  const helpButton = button('btn-shortcuts', '?', () => {
    if (document.querySelector('dialog[open]')) return;
    help.showModal(); helpClose.focus();
  });
  helpButton.setAttribute('aria-label', '键盘快捷键');
  helpButton.title = '键盘快捷键（?）';
  helpButton.className = 'icon-btn';
  document.querySelector('.app-actions').prepend(helpButton);
  $('btn-showcase-toggle').before(focusButton);
  const help = document.createElement('dialog');
  help.id = 'shortcuts-dialog'; help.className = 'shortcuts-dialog';
  help.setAttribute('aria-labelledby', 'keyboard-shortcuts-title');
  const title = document.createElement('h2'); title.id = 'keyboard-shortcuts-title'; title.textContent = '键盘快捷键';
  help.append(title);
  const list = document.createElement('dl');
  for (const [keys, label] of [[`${primaryKey} + K`, '快速跳转'], [`${primaryKey} + Shift + F`, '全局搜索'],
    ['/', '筛选当前目录'], [`${primaryKey} + Shift + L`, '切换专注模式'], ['↑ / ↓、Enter', '选择并打开条目'],
    ['Esc', '关闭搜索或对话框'], ['?', '查看快捷键']]) {
    const term = document.createElement('dt'); term.textContent = label;
    const detail = document.createElement('dd'); const key = document.createElement('kbd'); key.textContent = keys;
    detail.append(key); list.append(term, detail);
  }
  help.append(list);
  const helpClose = button('shortcuts-close', '知道了', () => help.close());
  help.append(helpClose); document.body.append(help);
  help.addEventListener('close', () => helpButton.focus());
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing || document.querySelector('dialog[open]')) return;
    if (commandPressed(event) && event.shiftKey && event.key.toLowerCase() === 'l') {
      event.preventDefault(); toggleFocus();
    } else if (event.key === '?' && !commandPressed(event) && !event.altKey && !event.metaKey && !isEditing(event.target)) {
      event.preventDefault(); helpButton.click();
    } else if (focus && commandPressed(event) && !event.shiftKey && event.key.toLowerCase() === 'k') {
      // 先恢复导航，让随后由 quickaccess 接管的快捷键有可见输入框。
      toggleFocus();
    }
  });
  const densityRow = document.createElement('label'); densityRow.className = 'density-setting';
  densityRow.textContent = '目录行距';
  const density = select('density-select', '目录行距', [['comfortable', '舒适'], ['compact', '紧凑']], async value => {
    density.disabled = true;
    try { await session.save({ density: value }); }
    catch (error) { flash(`行距未保存：${error.message}`); applyDensity(session.preferences); }
    finally { density.disabled = false; }
  });
  densityRow.append(density);
  $('settings-close').before(densityRow);
  function applyDensity(prefs) {
    density.value = prefs.density || 'comfortable';
    document.documentElement.dataset.density = density.value;
  }
  session.subscribe(applyDensity); applyDensity(session.preferences);
}
