import { api, mark, target } from './api.js';
import { locationURL } from './navigation.js';
import { icon } from './icons.js';
import { createWorkspaceTools } from './workspace-tools.js';
import { preserveNavScroll } from './interaction.js';
import { sortNav } from './navsort.js';
import { recordDirectoryLabel } from './record-label.js';

export const $ = (id) => document.getElementById(id);
let flashTimer;
export function flash(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => toast.classList.add('hidden'), 6000);
}
export function fatal(error) {
  $('bootstrap').replaceChildren();
  const heading = document.createElement('h1');
  heading.textContent = '工作台加载失败';
  const message = document.createElement('p');
  message.textContent = error.status === 401 ? '会话已失效，请重新启动工作台入口。' : error.message;
  const retry = document.createElement('button');
  retry.className = 'btn primary';
  retry.textContent = '重新加载';
  retry.onclick = () => location.reload();
  $('bootstrap').append(heading, message, retry);
}
export function createView(nav, session, actions, tree, navPanel, preview) {
  const layout = $('workspace-layout');
  const stage = $('project-stage');
  const stageScroll = $('project-navigation');
  stageScroll.append(navPanel.host);
  const homeTab = $('btn-project-home'), contentTab = $('btn-project-content');
  const showcaseToggle = $('btn-showcase-toggle'), filesToggle = $('btn-files-toggle');
  const content = $('project-content');
  const crumbs = $('crumbs');
  const revealCurrentCrumb = () => { crumbs.scrollLeft = crumbs.scrollWidth; };
  new ResizeObserver(() => {
    if (!crumbs.contains(document.activeElement)) revealCurrentCrumb();
  }).observe(crumbs);
  const rootTabs = $('root-tabs');
  const rootStrip = $('root-tab-strip');
  const previousTabs = $('root-tabs-prev');
  const nextTabs = $('root-tabs-next');
  let tabLocation;
  let tabLayoutFrame;
  let tabScrollLeft = 0;
  let tabStripWidth = rootStrip.clientWidth;
  previousTabs.append(icon('chevron'));
  nextTabs.append(icon('chevron'));
  function updateTabOverflow() {
    // 以整条可用宽度判断，避免按钮显隐改变滚动区宽度后反复抖动。
    const overflow = rootTabs.scrollWidth > rootStrip.clientWidth + 1;
    previousTabs.classList.toggle('hidden', !overflow);
    nextTabs.classList.toggle('hidden', !overflow);
    previousTabs.disabled = !overflow || rootTabs.scrollLeft <= 1;
    nextTabs.disabled = !overflow || rootTabs.scrollLeft + rootTabs.clientWidth >= rootTabs.scrollWidth - 1;
  }
  function revealTab(tab) {
    if (!tab) return;
    const viewport = rootTabs.getBoundingClientRect();
    const item = tab.getBoundingClientRect();
    // 只移动选项卡滚动容器，避免 scrollIntoView 带动页面和内容区。
    if (item.left < viewport.left) rootTabs.scrollLeft -= viewport.left - item.left;
    else if (item.right > viewport.right) rootTabs.scrollLeft += item.right - viewport.right;
  }
  function layoutTabs(reveal) {
    updateTabOverflow();
    if (reveal) revealTab(rootTabs.querySelector('[role="tab"][aria-selected="true"]'));
    updateTabOverflow();
  }
  for (const [button, direction] of [[previousTabs, -1], [nextTabs, 1]]) {
    button.onclick = () => {
      rootTabs.scrollLeft += direction * Math.max(1, rootTabs.clientWidth * 0.8);
      updateTabOverflow();
    };
  }
  rootTabs.addEventListener('scroll', updateTabOverflow, { passive: true });
  rootTabs.addEventListener('focusin', (event) => {
    if (event.target.matches('.root-tab')) { revealTab(event.target); updateTabOverflow(); }
  });
  const tabResizeObserver = new ResizeObserver(() => {
    // 加载中暂时清空根列表只改变高度，不应把用户的滚动位置拉回当前项。
    if (rootStrip.clientWidth === tabStripWidth) return;
    tabStripWidth = rootStrip.clientWidth;
    cancelAnimationFrame(tabLayoutFrame);
    tabLayoutFrame = requestAnimationFrame(() => layoutTabs(true));
  });
  tabResizeObserver.observe(rootStrip);
  const repoMenu = $('repo-root-menu');
  let repoMenuKey;
  function closeRepoMenu(restoreFocus = false) {
    if (repoMenu.matches(':popover-open')) repoMenu.hidePopover();
    $('repo-root-trigger')?.setAttribute('aria-expanded', 'false');
    if (restoreFocus) $('repo-root-trigger')?.focus({ preventScroll: true });
  }
  function positionRepoMenu() {
    const anchor = $('repo-root-trigger')?.getBoundingClientRect();
    if (!anchor) return;
    const width = Math.min(480, window.innerWidth - 24);
    repoMenu.style.width = `${width}px`;
    repoMenu.style.left = `${Math.max(12, Math.min(anchor.left, window.innerWidth - width - 12))}px`;
    const below = window.innerHeight - anchor.bottom - 18;
    const above = below < 120 && anchor.top > below;
    repoMenu.style.top = above ? 'auto' : `${anchor.bottom + 6}px`;
    repoMenu.style.bottom = above ? `${window.innerHeight - anchor.top + 6}px` : 'auto';
    repoMenu.style.maxHeight = `${Math.max(60, Math.min(420, above ? anchor.top - 18 : below))}px`;
  }
  function openRepoMenu(last = false) {
    positionRepoMenu();
    if (!repoMenu.matches(':popover-open')) repoMenu.showPopover();
    $('repo-root-trigger').setAttribute('aria-expanded', 'true');
    const items = [...repoMenu.children];
    const selected = items.find((item) => item.getAttribute('aria-checked') === 'true');
    (last ? items.at(-1) : selected || items[0])?.focus();
  }
  repoMenu.addEventListener('toggle', () => {
    $('repo-root-trigger')?.setAttribute('aria-expanded', String(repoMenu.matches(':popover-open')));
  });
  repoMenu.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault();
      closeRepoMenu(true);
      return;
    }
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const items = [...repoMenu.children];
    const index = items.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
      : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  });
  window.addEventListener('resize', () => {
    if (repoMenu.matches(':popover-open')) positionRepoMenu();
  });
  rootTabs.addEventListener('scroll', () => {
    if (repoMenu.matches(':popover-open')) positionRepoMenu();
  }, { passive: true });
  let projects = [];
  let deletedProjects = [];
  let diagnostics = [];
  let refreshVersion = 0;
  let currentLocation;
  function setShowcaseCollapsed(collapsed) {
    layout.classList.toggle('showcase-collapsed', collapsed);
    showcaseToggle.setAttribute('aria-expanded', String(!collapsed));
    showcaseToggle.title = collapsed ? '展开项目陈列' : '收起项目陈列';
    showcaseToggle.setAttribute('aria-label', showcaseToggle.title);
  }
  function setFilesCollapsed(collapsed) {
    layout.classList.toggle('files-collapsed', collapsed);
    filesToggle.setAttribute('aria-expanded', String(!collapsed));
    filesToggle.title = collapsed ? '展开文件导航' : '收起文件导航';
  }
  function setMobileView(view) {
    layout.dataset.mobileView = view;
  }
  function syncBrowserMode(state, home) {
    const project = !!state.target?.project_id;
    const hasHomepage = project;
    $('project-mode').classList.toggle('hidden', !project || (!hasHomepage && !state.roots.length));
    homeTab.classList.toggle('hidden', !hasHomepage);
    homeTab.setAttribute('aria-selected', String(home));
    contentTab.setAttribute('aria-selected', String(!home));
    homeTab.tabIndex = home ? 0 : -1;
    contentTab.tabIndex = home ? -1 : 0;
    contentTab.disabled = !state.roots.length;
    if (project) {
      content.setAttribute('role', 'tabpanel');
      content.setAttribute('aria-labelledby', contentTab.id);
    } else {
      content.removeAttribute('role');
      content.removeAttribute('aria-labelledby');
    }
    showcaseToggle.classList.toggle('hidden', !home || !hasHomepage);
    if (!home || !hasHomepage) setShowcaseCollapsed(false);
    $('content-navigation').classList.toggle('hidden', !project || home);
    filesToggle.disabled = !!state.error || session.preferences.preview_visible === false;
    if (state.error || session.preferences.preview_visible === false) setFilesCollapsed(false);
  }
  let lastSort = session.preferences.nav_sort || "default";
  session.subscribe((prefs) => {
    const next = prefs.nav_sort || "default";
    if (next !== lastSort) { lastSort = next; sidebar(); }
  });
  function sidebar() {
    preserveNavScroll($('sidebar-scroll'), sidebarContent);
  }
  function sidebarContent() {
    const prefs = session.preferences;
    const order = prefs.project_order || [];
    const pins = new Set(prefs.pinned_project_ids || []);
    const sorted = sortNav([...projects].sort((a, b) => {
      const ia = order.indexOf(a.project_id), ib = order.indexOf(b.project_id);
      return (ia < 0 ? Infinity : ia) - (ib < 0 ? Infinity : ib);
    }), prefs.nav_sort || 'default');
    $('pinned-projects').replaceChildren();
    $('other-projects').replaceChildren();
    for (const project of sorted) {
      const selected = nav.state.target?.project_id === project.project_id;
      const group = document.createElement('div');
      group.className = 'project-group';
      group.classList.toggle('is-selected', selected);
      const row = document.createElement('div');
      row.className = 'project-row';
      const snapshot = target({ project_id: project.project_id, root_id: '', relative_path: '' });
      const link = mark(document.createElement('a'), 'project-link', snapshot);
      link.href = locationURL(snapshot);
      link.dataset.id = project.project_id;
      link.setAttribute('aria-label', `项目：${project.title}`);
      link.classList.toggle('active', selected);
      if (selected) link.setAttribute('aria-current', 'true');
      const title = document.createElement('span');
      title.className = 'title';
      title.textContent = project.title + (project.deleted ? '（已删除）' : '');
      link.append(icon('project'), title);
      link.onclick = (event) => { event.preventDefault(); nav.go(snapshot); };
      const pin = mark(document.createElement('button'), 'project-pin', snapshot);
      pin.className = `pin-btn${pins.has(project.project_id) ? ' pinned' : ''}`;
      pin.append(icon('pin', pins.has(project.project_id)));
      pin.setAttribute('aria-label', `${pins.has(project.project_id) ? '取消固定' : '固定'}项目：${project.title}`);
      pin.setAttribute('aria-pressed', String(pins.has(project.project_id)));
      pin.title = pin.getAttribute('aria-label');
      pin.disabled = !!project.deleted;
      pin.onclick = async () => {
        pin.disabled = true;
        const ctx = nav.context();
        const remove = (session.preferences.pinned_project_ids || []).includes(project.project_id);
        try {
          await session.save((prefs) => {
            const current = prefs.pinned_project_ids || [];
            return { pinned_project_ids: remove ? current.filter((id) => id !== project.project_id)
              : [...new Set([...current, project.project_id])] };
          });
          if (ctx.valid()) sidebar();
        }
        catch (error) { if (ctx.valid()) { flash(error.message); pin.disabled = false; } }
      };
      row.append(link, pin);
      group.append(row);
      (pins.has(project.project_id) ? $('pinned-projects') : $('other-projects')).append(group);
    }
    $('project-diagnostics').classList.toggle('hidden', !diagnostics.length);
    $('project-diagnostics').textContent = diagnostics.map((item) => `${item.project || ''}：${item.message}`).join('\n');
  }
  function chrome(state) {
    const value = state.target;
    const home = value?.root_id === 'homepage';
    document.body.classList.toggle('project-home-active', home);
    const snapshot = value && target(value);
    const project = [...projects, ...deletedProjects].find((item) => item.project_id === value?.project_id);
    const projectName = project?.title || value?.project_id || '';
    const title = $('project-title');
    title.textContent = projectName || 'DUMMYSYS 首页';
    title.title = title.textContent;
    title.classList.toggle('idle', !value);
    $('browser-project-icon').classList.toggle('hidden', !projectName);
    $('stage-title').textContent = projectName;
    stage.classList.toggle('hidden', !projectName);
    layout.classList.toggle('has-project', !!projectName);
    syncBrowserMode(state, home);
    const locationKey = JSON.stringify(snapshot || null);
    if (locationKey !== currentLocation) {
      currentLocation = locationKey;
      setFilesCollapsed(false);
      if (preview.current) preview.clear();
      setMobileView('browser');
    }
    if (rootTabs.childElementCount) tabScrollLeft = rootTabs.scrollLeft;
    const scrollLeft = tabScrollLeft;
    const focusedRoot = rootTabs.contains(document.activeElement) ? document.activeElement.dataset.rootId : null;
    const nextTabLocation = JSON.stringify([value?.project_id, value?.root_id]);
    const changedTab = nextTabLocation !== tabLocation;
    const existingTabs = new Map([...rootTabs.children].map((tab) => [tab.dataset.rootId, tab]));
    $('root-tabs').setAttribute('role', 'tablist');
    const repositories = state.roots.filter((root) => root.kind === 'repo');
    const currentRepo = repositories.find((root) => root.root_id === value?.root_id);
    const nextRepoMenuKey = JSON.stringify([value?.project_id, value?.root_id, value?.relative_path,
      repositories.map((root) => [root.root_id, root.label])]);
    if (nextRepoMenuKey !== repoMenuKey) {
      repoMenuKey = nextRepoMenuKey;
      closeRepoMenu();
      repoMenu.replaceChildren();
      for (const root of repositories) {
        const rootTarget = nav.rootTarget(root.root_id);
        const item = mark(document.createElement('button'), 'repo-root-option', rootTarget);
        item.className = 'repo-root-option';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(root === currentRepo));
        item.tabIndex = -1;
        item.title = root.label;
        item.append(icon('check'));
        const label = document.createElement('span');
        label.textContent = root.label;
        item.append(label);
        item.onclick = () => { closeRepoMenu(true); nav.go(rootTarget); };
        repoMenu.append(item);
      }
    }
    const roots = state.roots.filter((root) => root.kind !== 'repo');
    const tabs = [...roots];
    if (repositories.length) tabs.push({ root_id: 'repositories',
      label: currentRepo ? `代码仓库：${currentRepo.label.replace(/^代码 /, '')}` : `代码仓库（${repositories.length}）` });
    if (tabs.length || !value) tabLocation = nextTabLocation;
    const selectedRoot = currentRepo ? 'repositories' : value?.root_id;
    const tabbableRoot = tabs.find((root) => root.root_id === selectedRoot) || tabs[0];
    for (const [index, root] of tabs.entries()) {
      const repoSelector = root.root_id === 'repositories';
      const rootTarget = repoSelector ? null : nav.rootTarget(root.root_id);
      const existing = existingTabs.get(root.root_id);
      const tab = mark(existing || document.createElement('button'), repoSelector ? 'repo-root-selector' : 'root-tab', rootTarget);
      const wasSelected = tab.classList.contains('active');
      const selected = repoSelector ? !!currentRepo : root.root_id === value?.root_id;
      // 加载进度通知不重建按钮，保留正在播放的伪元素动画和键盘焦点。
      tab.classList.add('root-tab');
      tab.classList.toggle('active', selected);
      if (!selected || (!wasSelected && changedTab)) tab.classList.remove('selection-static');
      // 刷新根列表后恢复同一选中项时，只恢复下划线，不重播选中动画。
      if (!existing && selected && !changedTab) tab.classList.add('selection-static');
      tab.textContent = root.label;
      tab.title = root.label;
      tab.dataset.rootId = root.root_id;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(selected));
      tab.setAttribute('aria-label', repoSelector ? '代码仓库' : `根目录：${root.label}`);
      tab.tabIndex = root === tabbableRoot ? 0 : -1;
      if (repoSelector) {
        tab.id = 'repo-root-trigger';
        tab.classList.add('repo-root-trigger');
        const label = document.createElement('span');
        label.className = 'repo-root-caption';
        label.textContent = root.label;
        tab.replaceChildren(label, icon('chevron'));
        tab.setAttribute('aria-haspopup', 'menu');
        tab.setAttribute('aria-controls', 'repo-root-menu');
        tab.setAttribute('popovertarget', 'repo-root-menu');
        tab.setAttribute('aria-expanded', String(repoMenu.matches(':popover-open')));
      }
      tab.onclick = (event) => {
        if (repoSelector) {
          event.preventDefault();
          if (repoMenu.matches(':popover-open')) closeRepoMenu(true);
          else openRepoMenu();
        } else nav.go(rootTarget);
      };
      tab.onkeydown = (event) => {
        if (repoSelector && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
          event.preventDefault();
          openRepoMenu(event.key === 'ArrowUp');
          return;
        }
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const tabs = [...$('root-tabs').children];
        const index = tabs.indexOf(tab);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[next].focus();
      };
      if (rootTabs.children[index] !== tab) rootTabs.insertBefore(tab, rootTabs.children[index] || null);
    }
    const rootIds = new Set(tabs.map((root) => root.root_id));
    for (const [rootId, tab] of existingTabs) if (!rootIds.has(rootId)) tab.remove();
    rootTabs.scrollLeft = scrollLeft;
    const focusedTab = [...rootTabs.children].find((tab) => tab.dataset.rootId === focusedRoot);
    focusedTab?.focus({ preventScroll: true });
    layoutTabs(changedTab);
    if (focusedTab) { revealTab(focusedTab); updateTabOverflow(); }
    crumbs.replaceChildren();
    if (value) {
      const root = state.roots.find((item) => item.root_id === value.root_id);
      const parts = value.relative_path.split('/').filter(Boolean);
      for (let i = 0; i <= parts.length; i += 1) {
        const crumbTarget = target({ ...value, relative_path: parts.slice(0, i).join('/') });
        const link = mark(document.createElement('a'), 'breadcrumb', crumbTarget);
        link.href = locationURL(crumbTarget);
        const name = parts[i - 1];
        const record = name && recordDirectoryLabel(name);
        link.textContent = i === 0 ? root?.label || value.root_id || '项目根'
          : record?.taskNumber ? `任务 #${record.taskNumber}` : record?.title || name;
        if (name) link.title = name;
        if (i === parts.length) link.setAttribute('aria-current', 'location');
        link.className = i === 0 ? 'root' : '';
        link.onclick = (event) => { event.preventDefault(); nav.go(crumbTarget); };
        if (i) {
          const separator = document.createElement('span');
          separator.className = 'sep';
          separator.append(icon('chevron'));
          crumbs.append(separator);
        }
        crumbs.append(link);
      }
    }
    $('btn-up').disabled = !value?.relative_path;
    $('btn-project-refresh').disabled = state.loading;
    $('btn-refresh').disabled = !value || state.loading;
    const unavailable = !value || state.loading || !!state.error || !state.resolved;
    const externalDisabled = unavailable || state.resolved?.available === false || !!state.resolved?.navigation_only;
    $('btn-open-vscode').disabled = externalDisabled;
    $('btn-open-explorer').disabled = externalDisabled;
    $('btn-copy-directory').disabled = unavailable;
    for (const id of ['btn-open-vscode', 'btn-open-explorer', 'btn-copy-directory']) {
      if (snapshot) mark($(id), id === 'btn-copy-directory' ? 'copy-directory' : id, snapshot);
      else delete $(id).dataset.target;
    }
    const resolved = state.resolved;
    $('btn-open-vscode').onclick = () => actions.open(snapshot, 'vscode_open', resolved);
    $('btn-open-explorer').onclick = () => actions.open(snapshot, 'explorer_open', resolved);
    $('btn-copy-directory').onclick = () => actions.copy(snapshot, resolved);
    $('dir-filter').disabled = !value || home || !!state.error;
    if ($('dir-filter').value !== state.filter) $('dir-filter').value = state.filter;
    // 项目工具栏作用于项目而非目录：选中项目即显示，目录出错也不隐藏。
    $('project-toolbar').classList.toggle('hidden', !value?.project_id);
    $('dir-summary').textContent = state.loading ? '加载中…' : resolved?.native_path || (value ? `${value.root_id} / ${value.relative_path}` : '');
    $('directory-path').title = resolved?.native_path || '';
    revealCurrentCrumb();
    $('dir-view').setAttribute('aria-busy', String(state.loading));
    $('dir-view').classList.toggle('hidden', !value || !!state.error);
    content.classList.toggle('hidden', !value || (home && !state.error));
    $('empty-state').classList.toggle('hidden', !!value);
    $('pager').classList.toggle('hidden', !state.cursor || !!state.error);
    $('btn-more').disabled = state.loading;
    $('error-view').classList.toggle('hidden', !state.error);
    if (state.error) {
      $('error-title').textContent = '无法浏览本次目标';
      $('error-message').textContent = `${state.error.message}\n项目：${value.project_id}\n根：${value.root_id}\n相对路径：${value.relative_path || '（根目录）'}`;
      mark($('error-view'), 'navigation-error', snapshot);
      $('error-copy').onclick = () => actions.copy(snapshot);
      $('error-back').disabled = !value.relative_path;
    }
  }
  let lastSidebarProject;
  nav.subscribe((state) => {
    if (lastSidebarProject !== state.target?.project_id) {
      lastSidebarProject = state.target?.project_id;
      stageScroll.scrollTop = 0;
      sidebar();
    }
    chrome(state);
  });
  function catalog(data) { projects = data.projects || []; deletedProjects = data.deleted_projects || []; diagnostics = data.diagnostics || []; sidebar(); }
  function wire() {
    wireResizer();
    wirePreviewResizer();
    createWorkspaceTools(nav, session, flash);
    $('browser-project-icon').append(icon('project'));
    $('directory-path-icon').append(icon('folder'));
    $('global-search-icon').append(icon('search'));
    for (const [id, glyph] of Object.entries({
      'btn-project-refresh': 'refresh', 'btn-back': 'back', 'btn-refresh': 'refresh',
      'btn-up': 'up', 'btn-open-vscode': 'code', 'btn-open-explorer': 'folder',
      'btn-copy-directory': 'copy', 'btn-pin-directory': 'pin', 'btn-show-browser': 'forward',
      'btn-show-projects': 'panel', 'btn-files-toggle': 'list', 'btn-preview-toggle': 'preview',
      'btn-showcase-toggle': 'panel', 'btn-project-home': 'home', 'btn-project-content': 'folder',
    })) $(id).prepend(icon(glyph));
    homeTab.onclick = () => { if (nav.state.target?.root_id !== 'homepage') nav.go(nav.rootTarget('homepage')); };
    contentTab.onclick = () => {
      const destination = nav.contentTarget();
      if (destination && nav.state.target?.root_id === 'homepage') nav.go(destination);
    };
    $('project-mode').onkeydown = (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = [homeTab, contentTab].filter((tab) => !tab.disabled && !tab.classList.contains('hidden'));
      if (tabs.length < 2) return;
      event.preventDefault();
      (event.key === 'Home' ? homeTab : event.key === 'End' ? contentTab
        : event.target === homeTab ? contentTab : homeTab).focus();
    };
    showcaseToggle.onclick = () => setShowcaseCollapsed(!layout.classList.contains('showcase-collapsed'));
    filesToggle.onclick = () => setFilesCollapsed(!layout.classList.contains('files-collapsed'));
    const narrowPreview = matchMedia('(max-width: 760px)');
    preview.subscribe((value) => {
      if (value && narrowPreview.matches && session.preferences.preview_visible !== false &&
          !document.body.classList.contains('workspace-focus')) setFilesCollapsed(true);
    });
    $('btn-show-browser').onclick = () => { setMobileView('browser'); $('btn-show-projects').focus(); };
    $('btn-show-projects').onclick = () => { setMobileView('showcase'); $('btn-show-browser').focus(); };
    session.subscribe((prefs) => {
      if (prefs.preview_visible === false) setFilesCollapsed(false);
      filesToggle.disabled = prefs.preview_visible === false || !!nav.state.error;
    });
    $('dir-filter').oninput = (event) => nav.filter(event.target.value);
    $('btn-home').onclick = () => nav.go(null);
    $('btn-back').onclick = () => history.back();
    $('btn-up').onclick = () => nav.up();
    $('btn-refresh').onclick = () => { if (nav.state.target) tree.invalidate(nav.state.target); nav.reload(true); };
    $('btn-more').onclick = () => nav.more();
    $('error-back').onclick = () => nav.up();
    $('error-history-back').onclick = () => history.back();
    $('error-retry').onclick = () => nav.reload();
    $('btn-project-refresh').onclick = async () => {
      if (nav.state.target) { await nav.reload(true); return; }
      const ctx = nav.context();
      const version = ++refreshVersion;
      $('btn-project-refresh').disabled = true;
      try {
        const data = await api('projects/refresh', { body: {}, signal: ctx.signal });
        if (ctx.valid() && version === refreshVersion) await nav.onCatalog(data);
      } catch (error) { if (ctx.valid()) flash(error.message); }
      finally { if (ctx.valid() && version === refreshVersion) $('btn-project-refresh').disabled = false; }
    };
  }
  function wireResizer() {
    const handle = $('sidebar-resizer');
    const root = document.documentElement;
    const MIN = 200, MAX = 640, STEP = 16;
    const clamp = (px) => Math.max(MIN, Math.min(MAX, layout.clientWidth - 288, px));
    const width = () => $('sidebar').getBoundingClientRect().width;
    const apply = (px) => {
      const v = px == null ? null : `${Math.round(px)}px`;
      if (v == null) root.style.removeProperty('--sidebar-w');
      else root.style.setProperty('--sidebar-w', v);
      handle.setAttribute('aria-valuenow', String(Math.round(width())));
    };
    let dragging = false, moved = false, startX = 0, startWidth = 0;
    new ResizeObserver(() => {
      if (width()) handle.setAttribute('aria-valuenow', String(Math.round(width())));
    }).observe($('sidebar'));
    let lastWidth = session.preferences.sidebar_width ?? null;
    apply(lastWidth);
    // 仅 sidebar_width 真正变化时才写入，避免切换项目保存 last_location 等触发重置
    session.subscribe?.((prefs) => {
      const w = prefs.sidebar_width ?? null;
      if (w !== lastWidth) { lastWidth = w; if (!dragging) apply(w); }
    });

    function onMove(e) {
      if (!dragging) return;
      e.preventDefault();
      if (Math.abs(e.clientX - startX) > 3) moved = true;
      apply(clamp(startWidth + e.clientX - startX));
    }
    function onUp(e) {
      if (!dragging) return;
      dragging = false;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      delete handle.dataset.dragging;
      document.body.classList.remove('sidebar-resizing');
      if (moved) saveWidth(Math.round(width()));
    }

    handle.addEventListener('pointerdown', (event) => {
      if (event.button) return;
      event.preventDefault();
      dragging = true;
      moved = false;
      startX = event.clientX;
      startWidth = width();
      handle.dataset.dragging = '';
      document.body.classList.add('sidebar-resizing');
      window.addEventListener('pointermove', onMove, { passive: false });
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    });
    function saveWidth(value) {
      session.save({ sidebar_width: value }).catch((error) => {
        apply(session.preferences.sidebar_width ?? null);
        flash(`项目陈列宽度未保存：${error.message}`);
      });
    }
    handle.addEventListener('dblclick', () => {
      if (moved) return;
      apply(null);
      saveWidth(null);
    });
    handle.addEventListener('keydown', (event) => {
      const step = event.key === 'ArrowLeft' ? -STEP : event.key === 'ArrowRight' ? STEP : 0;
      if (!step) return;
      event.preventDefault();
      apply(clamp(width() + step));
      saveWidth(Math.round(width()));
    });
  }
  function wirePreviewResizer() {
    const handle = $('preview-resizer');
    const root = document.documentElement;
    const MIN = 240, MAX = 800, STEP = 16;
    const clamp = (px) => Math.round(Math.max(MIN, Math.min(MAX, $('main-split').clientWidth - 156, px)));
    const width = () => $('preview-pane').getBoundingClientRect().width;
    const apply = (px) => {
      if (px == null) root.style.removeProperty('--preview-w');
      else root.style.setProperty('--preview-w', `${Math.round(px)}px`);
      const value = Math.round(width());
      handle.setAttribute('aria-valuenow', String(value));
      handle.setAttribute('aria-valuetext', `${value} 像素`);
    };
    let dragging = false, moved = false, startX = 0, startWidth = 0;
    apply(session.preferences.preview_width ?? null);
    let pendingSaves = 0;
    session.subscribe?.((prefs) => { if (!dragging && !pendingSaves) apply(prefs.preview_width ?? null); });
    function saveWidth(value) {
      pendingSaves += 1;
      handle.setAttribute('aria-busy', 'true');
      session.save({ preview_width: value }).catch(error => flash(`预览宽度未保存：${error.message}`))
        .finally(() => {
          pendingSaves -= 1;
          if (!pendingSaves) {
            handle.setAttribute('aria-busy', 'false');
            if (!dragging) apply(session.preferences.preview_width ?? null);
          }
        });
    }
    handle.addEventListener('pointerdown', (event) => {
      if (event.button) return;
      dragging = true;
      moved = false;
      startX = event.clientX;
      startWidth = width();
      handle.setPointerCapture(event.pointerId);
      handle.dataset.dragging = '';
      document.body.classList.add('sidebar-resizing');
      event.preventDefault();
    });
    handle.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      if (Math.abs(event.clientX - startX) > 3) moved = true;
      // 从右缘量宽：拖向左侧加宽预览。
      apply(clamp(startWidth + startX - event.clientX));
    });
    const end = (event) => {
      if (!dragging) return;
      dragging = false;
      handle.releasePointerCapture?.(event.pointerId);
      delete handle.dataset.dragging;
      document.body.classList.remove('sidebar-resizing');
      if (moved) saveWidth(clamp(width()));
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => {
      if (moved) return;
      apply(null);
      saveWidth(null);
    });
    handle.addEventListener('keydown', (event) => {
      // 分隔条在预览左缘：右方向键加宽预览。
      const step = event.key === 'ArrowRight' ? STEP : event.key === 'ArrowLeft' ? -STEP : 0;
      if (!step) return;
      event.preventDefault();
      apply(clamp(width() + step));
      saveWidth(clamp(width()));
    });
  }

  return { catalog, wire, show() {
    $('bootstrap').classList.add('hidden');
    $('app').classList.remove('hidden');
  } };
}
