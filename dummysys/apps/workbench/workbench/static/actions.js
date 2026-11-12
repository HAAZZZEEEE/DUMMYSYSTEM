import { fileManager } from './platform-ui.js';
import { api, target, mark } from './api.js';

const labels = { obsidian_open: '用 Obsidian 打开', vscode_open: '用 VS Code 打开',
  explorer_open: `在 ${fileManager} 打开`, explorer_reveal: `在 ${fileManager} 定位`, system_open: '系统默认应用打开' };
const actionId = (action) => typeof action === 'string' ? action : action.action || action.id;
export function metadata(value) {
  const { target: resolved, ...fields } = value || {};
  return { ...fields, ...(resolved && typeof resolved === 'object' ? resolved : {}) };
}

export function createActions(nav, flash) {
  let menu = null;
  let trigger = null;
  let triggerScope = null;
  let triggerTarget = null;
  let menuVersion = 0;
  let generation = -1;
  const dialog = document.getElementById('copy-dialog');
  const input = document.getElementById('copy-path');
  function syncMenu() {
    if (!menu || !triggerTarget) return;
    if (!trigger?.isConnected) {
      trigger = [...document.querySelectorAll('[data-testid="target-menu"]')].find((button) =>
        button.dataset.target === triggerTarget && !!button.closest('.project-tree') === triggerScope) || null;
    }
    trigger?.setAttribute('aria-expanded', 'true');
    trigger?.classList.add('open');
  }
  function closeMenu(focus = false) {
    syncMenu();
    menuVersion += 1;
    menu?.remove();
    trigger?.setAttribute('aria-expanded', 'false');
    trigger?.classList.remove('open');
    if (focus && trigger?.isConnected) trigger.focus();
    menu = null;
    trigger = null;
    triggerTarget = null;
  }
  nav.subscribe((state) => {
    if (generation !== state.generation) {
      generation = state.generation;
      closeMenu();
      if (dialog.open) dialog.close();
    } else if (state.loading) closeMenu();
  });
  document.addEventListener('click', (event) => {
    if (!menu?.contains(event.target) && !trigger?.contains(event.target)) closeMenu();
  });
  document.addEventListener('focusin', (event) => {
    if (menu && !menu.contains(event.target) && !trigger?.contains(event.target)) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && (menu || trigger)) { event.preventDefault(); closeMenu(true); }
  });
  document.getElementById('copy-close').onclick = () => dialog.close();
  input.onclick = () => input.select();

  async function resolve(value, ctx) {
    return api('actions', { body: { target: target(value) }, signal: ctx.signal });
  }
  async function copy(value, known = {}) {
    const snapshot = target(value);
    const ctx = nav.context();
    let info = metadata(known);
    try {
      if (!info.native_path) {
        const result = await resolve(snapshot, ctx);
        if (!ctx.valid()) return;
        info = { ...info, ...metadata(result) };
      }
      const path = info.native_path;
      if (typeof path !== 'string' || !path) throw new Error('服务未提供本机绝对路径，无法复制。');
      if (!ctx.valid()) return;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('剪贴板不可用');
        await navigator.clipboard.writeText(path);
        if (ctx.valid()) flash('已复制完整路径');
      } catch {
        if (!ctx.valid()) return;
        input.value = path;
        mark(dialog, 'copy-dialog', snapshot);
        dialog.showModal();
        input.focus();
        input.select();
      }
    } catch (error) { if (ctx.valid()) flash(error.message); }
  }
  async function open(value, action = null, known = {}) {
    if (nav.state.loading) return;
    const snapshot = target(value);
    const ctx = nav.context();
    const original = metadata(known);
    try {
      if (original.available === false || original.navigation_only) throw new Error(original.reason || '此目标仅供浏览，不能外部打开。');
      const result = await resolve(snapshot, ctx);
      if (!ctx.valid()) return;
      const info = metadata(result);
      if (info.available === false || info.navigation_only) throw new Error(info.reason || '此目标不能外部打开。');
      const selected = action || result.default_action;
      const available = (result.available_actions || []).find((item) => actionId(item) === selected);
      if (!selected || selected === 'browse' || !available || available.available === false) {
        throw new Error(available?.reason || '此目标没有可用的打开方式。');
      }
      // 最后一个 await 后再次检查；切导航后不发送尚未发出的打开。
      if (!ctx.valid()) return;
      await api('open', { body: { target: snapshot, action: selected, request_id: crypto.randomUUID() }, signal: ctx.signal });
      if (ctx.valid()) flash('已请求本机应用打开');
    } catch (error) { if (ctx.valid()) flash(error.message); }
  }
  function menuButton(value, known, name, extraItems = []) {
    const snapshot = target(value);
    const info = metadata(known);
    const button = mark(document.createElement('button'), 'target-menu', snapshot);
    button.type = 'button';
    button.className = 'more-btn';
    button.textContent = '⋯';
    button.setAttribute('aria-label', `操作：${name}`);
    button.setAttribute('aria-haspopup', 'menu');
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('keydown', (event) => event.stopPropagation());
    button.onclick = (event) => { event.stopPropagation(); showMenu(button, snapshot, info, extraItems); };
    button.openContextMenu = (event) => showMenu(button, snapshot, info, extraItems,
      { x: event.clientX, y: event.clientY });
    return button;
  }
  function bindContextMenu(element, button) {
    element.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (button.disabled || nav.state.loading) return;
      button.openContextMenu(event);
    });
  }
  async function showMenu(button, snapshot, known, extraItems = [], position = null) {
    if (nav.state.loading) return;
    if (trigger === button && !position) { closeMenu(true); return; }
    closeMenu();
    trigger = button;
    triggerScope = !!button.closest('.project-tree');
    triggerTarget = button.dataset.target;
    const version = menuVersion;
    const ctx = nav.context();
    const valid = () => {
      if (!ctx.valid() || menuVersion !== version) return false;
      syncMenu();
      return !!trigger?.isConnected;
    };
    menu = mark(document.createElement('div'), 'target-actions', snapshot);
    menu.className = 'menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', '目标操作');
    button.setAttribute('aria-expanded', 'true');
    button.classList.add('open');
    const box = button.getBoundingClientRect();
    const placeMenu = () => {
      const bounds = menu.getBoundingClientRect();
      const x = position?.x ?? box.right - bounds.width;
      const y = position?.y ?? box.bottom + 4;
      menu.style.left = `${Math.max(8, Math.min(x, innerWidth - bounds.width - 8))}px`;
      menu.style.top = `${Math.max(8, Math.min(y, innerHeight - bounds.height - 8))}px`;
    };
    const localMenu = menu;
    function item(label, id, fn, disabled = false, reason = '') {
      const element = mark(document.createElement('button'), id, snapshot);
      element.type = 'button';
      element.className = 'menu-item';
      element.textContent = label;
      element.setAttribute('role', 'menuitem');
      element.disabled = disabled;
      element.title = reason;
      element.onclick = (event) => { event.stopPropagation(); closeMenu(true); fn(); };
      localMenu.append(element);
      return element;
    }
    // 治理动作排在最前，其次复制，最后打开方式；置灰项保留原因，让缺口可见。
    // 分组横线：extra.separator === true 时插一条分割线。
    for (const extra of extraItems) {
      if (extra.separator) {
        const hr = document.createElement('hr');
        hr.className = 'menu-separator';
        localMenu.append(hr);
        continue;
      }
      item(extra.label, extra.id, extra.onClick || (() => {}), !!extra.disabled, extra.reason || '');
    }
    const copyItem = item('复制完整路径', 'copy-target', () => copy(snapshot, known));
    localMenu.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const items = [...localMenu.querySelectorAll('button:not(:disabled)')];
        const index = items.indexOf(document.activeElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 :
          (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
        items[next]?.focus();
      }
    });
    document.body.append(localMenu);
    placeMenu();
    copyItem.focus();
    try {
      const result = await resolve(snapshot, ctx);
      if (!valid()) return;
      const info = { ...known, ...metadata(result) };
      copyItem.onclick = (event) => { event.stopPropagation(); closeMenu(true); copy(snapshot, info); };
      for (const action of result.available_actions || []) {
        const id = actionId(action);
        if (!id || id === 'browse') continue;
        item(labels[id] || '打开目标', `action-${id}`, () => open(snapshot, id, info),
          info.available === false || !!info.navigation_only || action.available === false,
          action.reason || info.reason || '');
      }
      if (info.reason) {
        const note = document.createElement('p');
        note.className = 'menu-note';
        note.textContent = info.reason;
        localMenu.append(note);
      }
      placeMenu();
    } catch (error) {
      if (!valid()) return;
      const note = document.createElement('p');
      note.className = 'menu-note';
      note.textContent = error.message;
      localMenu.append(note);
      placeMenu();
    }
  }
  return { copy, open, menuButton, bindContextMenu, closeMenu, syncMenu };
}
