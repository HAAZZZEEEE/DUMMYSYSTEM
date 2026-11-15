import { commandPressed, primaryKey, isMac } from './platform-ui.js';
// 左侧导航栏顶部「快速跳转」：输入框聚焦/输入展开下拉，候选 = 项目 + 固定目录 + 最近访问。
// 不含 task/run/文件 搜索（那在主区顶部的全局搜索 search.js）。保留图钉、首页网格、最近记录。
import { target, targetKey, mark } from './api.js';
import { icon } from './icons.js';
import { isEditing as editable, revealOption } from './interaction.js';

const $ = (id) => document.getElementById(id);
const locations = (prefs, field) => Array.isArray(prefs[field]) ? prefs[field] : [];

export function createQuickAccess(nav, session, flash) {
  let projects = [];
  let saving = false;
  let lastSuccess = null;
  let selected = 0;
  let results = [];
  let open = false;
  const wrap = $('quick-wrap');
  const input = $('project-search');
  const popover = $('quick-popover');
  const resultsHost = $('quick-results');

  function known(value) { return projects.find((item) => item.project_id === value.project_id); }
  const rootName = (root) => ({ docs: '文档', resources: '资源', code: '代码' })[root]
    || (root?.startsWith('repo:') ? `代码 ${root.slice(5)}` : root);
  function label(value) {
    const project = known(value);
    const name = project?.title || value.project_id;
    return value.relative_path?.split('/').at(-1) || (value.root_id ? `${name} · ${rootName(value.root_id)}` : name);
  }
  function meta(value) { return `${known(value)?.title || value.project_id} / ${rootName(value.root_id) || '项目'}${value.relative_path ? ' / ' + value.relative_path : ''}`; }
  function validLocations(field) { return locations(session.preferences, field); }

  function candidates() {
    const projectItems = projects.map((project) => ({ value: target({ project_id: project.project_id, root_id: '', relative_path: '' }), category: '项目' }));
    const seen = new Set(projectItems.map((item) => targetKey(item.value)));
    const extra = [];
    for (const [field, category] of [['pinned_locations', '固定'], ['recent_locations', '最近']]) {
      for (const value of validLocations(field)) {
        const key = targetKey(value);
        if (seen.has(key)) continue;
        seen.add(key); extra.push({ value, category });
      }
    }
    return [...projectItems, ...extra];
  }
  function renderResults() {
    const query = input.value.trim().toLocaleLowerCase();
    results = candidates().filter(({ value, category }) =>
      `${category} ${label(value)} ${meta(value)} ${(known(value)?.aliases || []).join(' ')}`.toLocaleLowerCase().includes(query));
    selected = Math.min(selected, Math.max(0, results.length - 1));
    resultsHost.replaceChildren();
    input.removeAttribute('aria-activedescendant');
    if (!results.length) {
      const empty = document.createElement('p');
      empty.className = 'quick-empty';
      empty.textContent = '没有匹配的项目或位置。';
      resultsHost.append(empty);
      return;
    }
    results.forEach(({ value, category }, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'quick-result';
      mark(row, 'quick-result', value);
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(index === selected));
      row.tabIndex = -1;
      row.id = `quick-option-${index}`;
      row.onmouseenter = () => { selected = index; highlight(); };
      row.onclick = () => { select(value); };
      const title = document.createElement('span');
      title.textContent = `${category} · ${label(value)}`;
      const detail = document.createElement('span');
      detail.className = 'quick-result-meta';
      detail.textContent = meta(value);
      row.title = detail.textContent;
      row.append(title, detail);
      resultsHost.append(row);
    });
    highlight();
  }
  function highlight() {
    if (!results.length) { input.removeAttribute('aria-activedescendant'); return; }
    [...resultsHost.querySelectorAll('[role="option"]')].forEach((item, index) => item.setAttribute('aria-selected', String(index === selected)));
    input.setAttribute('aria-activedescendant', `quick-option-${selected}`);
    if (open) revealOption(resultsHost, resultsHost.querySelector(`#quick-option-${selected}`));
  }
  function openPopover() {
    if ([...document.querySelectorAll('dialog[open]')].length) return;
    open = true;
    selected = 0;
    renderResults();
    popover.classList.add('open');
    input.setAttribute('aria-expanded', 'true');
    $('btn-quick-switch')?.setAttribute('aria-expanded', 'true');
  }
  function closePopover() {
    open = false;
    popover.classList.remove('open');
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    $('btn-quick-switch')?.setAttribute('aria-expanded', 'false');
  }
  function select(value) {
    closePopover();
    input.value = '';
    input.blur();
    nav.go(value);
  }
  function renderHome() {
    const host = $('quick-home');
    if (!host) return;
    host.replaceChildren();
    for (const [field, heading, empty] of [
      ['pinned_locations', '固定目录', '还没有固定目录。进入目录后点击图钉即可固定。'],
      ['recent_locations', '最近访问', '还没有访问记录。从左侧先选择一个项目。'],
    ]) {
      const section = document.createElement('section');
      section.className = 'access-section';
      const title = document.createElement('h3');
      title.className = 'access-heading';
      title.textContent = heading;
      section.append(title);
      if (field === 'recent_locations' && locations(session.preferences, field).length) {
        const clear = document.createElement('button');
        clear.type = 'button'; clear.className = 'access-remove'; clear.textContent = '清空最近';
        clear.dataset.testid = 'clear-recent';
        clear.onclick = async () => {
          clear.disabled = true;
          try { await session.save(() => ({ recent_locations: [] })); lastSuccess = null; render(); }
          catch (error) { flash(error.message); clear.disabled = false; }
        };
        section.append(clear);
      }
      const grid = document.createElement('div');
      grid.className = 'access-grid';
      const values = validLocations(field);
      if (!values.length) {
        const hint = document.createElement('p'); hint.className = 'access-empty'; hint.textContent = empty;
        grid.append(hint);
      }
      for (const value of values) {
        const card = document.createElement('div'); card.className = 'access-card';
        const link = document.createElement('button'); link.type = 'button';
        link.className = 'access-title';
        mark(link, field === 'pinned_locations' ? 'pinned-location-link' : 'recent-link', value);
        if (field === 'pinned_locations') link.append(icon('pin', true));
        link.append(document.createTextNode(label(value)));
        link.onclick = () => nav.go(value);
        const detail = document.createElement('span'); detail.className = 'access-meta'; detail.textContent = meta(value);
        link.title = detail.textContent; detail.title = detail.textContent;
        card.append(link, detail);
        if (field === 'pinned_locations') {
          const remove = document.createElement('button');
          remove.type = 'button'; remove.className = 'access-remove'; remove.textContent = '移除';
          mark(remove, 'unpin-location', value);
          remove.onclick = async () => {
            remove.disabled = true;
            try { await session.save((prefs) => ({ pinned_locations: locations(prefs, field).filter((item) => targetKey(item) !== targetKey(value)) })); render(); }
            catch (error) { flash(error.message); remove.disabled = false; }
          };
          card.append(remove);
        }
        grid.append(card);
      }
      section.append(grid); host.append(section);
    }
  }
  function render() {
    const state = nav.state;
    const value = state.target;
    const enabled = !!value && !state.loading && !state.error && !!state.resolved && !saving;
    const pinned = !!value && locations(session.preferences, 'pinned_locations').some((item) => targetKey(item) === targetKey(value));
    const pin = $('btn-pin-directory');
    if (pin) {
      pin.disabled = !enabled;
      pin.replaceChildren(icon('pin', pinned));
      pin.title = pinned ? '取消固定当前目录' : '固定当前目录';
      pin.setAttribute('aria-label', pin.title);
      pin.setAttribute('aria-pressed', String(pinned));
    }
    renderHome();
    if (open) renderResults();
  }
  function wire() {
    const pin = $('btn-pin-directory');
    if (pin) {
      pin.onclick = async () => {
        const ctx = nav.context();
        if (saving || nav.state.loading || nav.state.error || !nav.state.resolved || !ctx.target) return;
        const value = target(ctx.target);
        const remove = locations(session.preferences, 'pinned_locations').some((item) => targetKey(item) === targetKey(value));
        saving = true; render();
        try {
          let full = false;
          await session.save((prefs) => {
            const current = locations(prefs, 'pinned_locations');
            const exists = current.some((item) => targetKey(item) === targetKey(value));
            if (!remove && exists) return null;
            if (!remove && current.length >= 30) { full = true; return null; }
            return { pinned_locations: remove
              ? current.filter((item) => targetKey(item) !== targetKey(value))
              : [value, ...current] };
          });
          if (full) flash('最多固定 30 个目录，请先取消固定一个目录。');
        } catch (error) { flash(error.message); }
        finally { saving = false; render(); }
      };
    }
    const btnSwitch = $('btn-quick-switch');
    if (btnSwitch) {
      btnSwitch.onclick = (event) => {
        event.preventDefault();
        if (!open) openPopover();
        input.focus();
      };
    }
    input.addEventListener('focus', openPopover);
    input.addEventListener('input', () => { selected = 0; openPopover(); });
    input.addEventListener('keydown', (event) => {
      if (event.isComposing) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (results.length) selected = (selected + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length;
        highlight();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (open && results[selected]) select(results[selected].value);
      } else if (event.key === 'Tab') {
        closePopover();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closePopover();
        input.blur();
      }
    });
    document.addEventListener('pointerdown', (event) => {
      if (open && !wrap.contains(event.target)) closePopover();
    });
    document.addEventListener('keydown', (event) => {
      if (event.defaultPrevented || event.altKey || (event.metaKey && !isMac)) return;
      // Ctrl+K 聚焦快速跳转（Ctrl+Shift+F 聚焦全局搜索，见 search.js）。
      if (commandPressed(event) && !event.shiftKey && event.key.toLowerCase() === 'k') {
        if ([...document.querySelectorAll('dialog[open]')].length) return;
        event.preventDefault();
        if (!open) openPopover();
        input.focus();
      } else if (!commandPressed(event) && !event.shiftKey && event.key === '/' && !open && !editable(event.target)) {
        if (document.querySelector('dialog[open]')) return;
        if ($('dir-filter').disabled || $('pane-toolbar').classList.contains('hidden')) return;
        event.preventDefault();
        const showBrowser = $('btn-show-browser');
        if (showBrowser.getClientRects().length) showBrowser.click();
        const files = $('btn-files-toggle');
        if (files.getAttribute('aria-expanded') === 'false') files.click();
        $('dir-filter').focus();
      }
    });
  }
  nav.subscribe((state) => {
    if (!state.loading && !state.error && state.resolved && state.target && known(state.target)) {
      const value = target(state.target);
      const key = targetKey(value);
      if (key !== lastSuccess) {
        lastSuccess = key;
        session.save((prefs) => {
          const current = locations(prefs, 'recent_locations');
          if (current.length && targetKey(current[0]) === key) return null;
          return { recent_locations: [value, ...current.filter((item) => targetKey(item) !== key)].slice(0, 8) };
        })
          .then(render).catch((error) => flash(`最近访问保存失败：${error.message}`));
      }
    }
    render();
  });
  session.subscribe(render);
  return {
    helpers: { label, meta, rootName, validLocations, candidates },
    catalog(data) { projects = data.projects || []; render(); },
    wire,
  };
}
