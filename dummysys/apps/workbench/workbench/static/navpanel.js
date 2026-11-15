// 项目导航面板：上组 Task/Run 关系 + 下组非标准路径树；右上角按钮容器可扩展。
import { api, mark, target } from './api.js';
import { icon } from './icons.js';

export function createNavPanel(nav, session, actions, tree, taskView, flash) {
  const host = mark(document.createElement('div'), 'nav-panel');
  host.className = 'nav-panel';
  const toolbar = document.createElement('div');
  toolbar.className = 'nav-toolbar';
  const caption = document.createElement('div');
  caption.className = 'nav-caption nav-task-caption';
  const captionTitle = mark(document.createElement('span'), 'nav-task-title');
  captionTitle.textContent = '任务与运行';
  const summary = mark(document.createElement('span'), 'nav-task-summary');
  summary.className = 'nav-task-summary';
  summary.setAttribute('aria-live', 'polite');
  caption.append(captionTitle, summary);
  const tools = mark(document.createElement('div'), 'nav-tools');
  tools.className = 'nav-actions';
  tools.setAttribute('role', 'toolbar');
  tools.setAttribute('aria-label', '导航操作');
  toolbar.append(caption, tools);
  const taskBlock = document.createElement('div');
  taskBlock.className = 'nav-group';
  const filters = document.createElement('div');
  filters.className = 'task-filters';
  const query = mark(document.createElement('input'), 'task-filter-query');
  query.type = 'search';
  query.placeholder = '筛选任务或运行…';
  query.setAttribute('aria-label', '筛选当前项目的任务或运行');
  query.autocomplete = 'off';
  const status = mark(document.createElement('select'), 'task-filter-status');
  status.setAttribute('aria-label', '任务状态');
  for (const [value, label] of [['all', '全部任务'], ['active', '进行中'], ['completed', '已完成']]) {
    status.add(new Option(label, value));
  }
  const applyFilter = () => taskView.setFilter(query.value, status.value);
  query.oninput = applyFilter;
  status.onchange = applyFilter;
  filters.append(query, status);
  taskBlock.append(toolbar, filters, taskView.host);
  const treeCaption = document.createElement('div');
  treeCaption.className = 'nav-caption';
  treeCaption.textContent = '其他路径';
  const treeBlock = document.createElement('div');
  treeBlock.className = 'nav-group';
  treeBlock.append(treeCaption, tree.host);
  host.append(taskBlock, treeBlock);

  let projectId = null;
  let request = 0;
  let controller;

  function toolButton(spec) {
    // spec: {id, label, title, onClick, isEnabled}
    const button = mark(document.createElement('button'), spec.id);
    button.type = 'button';
    button.className = 'icon-btn nav-tool';
    button.setAttribute('aria-label', spec.label);
    button.title = spec.title || spec.label;
    if (spec.iconName) button.append(icon(spec.iconName));
    else button.textContent = spec.text || '';
    button.onclick = (event) => { event.stopPropagation(); spec.onClick(); };
    button.onkeydown = (event) => event.stopPropagation();
    tools.append(button);
    return button;
  }

  function addButton(spec) {
    return toolButton(spec);
  }

  // 单个切换按钮：按当前展开态决定本次动作与图标，作用范围为当前选中项目。
  const toggleButton = toolButton({
    id: 'nav-toggle-all', label: '全部展开', iconName: 'expandAll',
    onClick: () => {
      if (taskView.hasExpanded() || tree.hasExpanded()) { taskView.collapseAll(); tree.collapseAll(); }
      else { taskView.expandAll(); tree.expandAll(); }
    },
  });
  function syncToggle() {
    const open = taskView.hasExpanded() || tree.hasExpanded();
    toggleButton.replaceChildren(icon(open ? 'collapseAll' : 'expandAll'));
    const label = open ? '全部折叠' : '全部展开';
    toggleButton.setAttribute('aria-label', label);
    toggleButton.title = `${label}当前项目的任务与路径`;
  }
  syncToggle();
  host.addEventListener('nav-expand-state', syncToggle);

  async function loadNav(force = false) {
    const targetState = nav.state.target;
    const nextProject = targetState?.project_id || null;
    if (!force && nextProject === projectId) return;
    controller?.abort();
    controller = new AbortController();
    const version = ++request;
    const changedProject = projectId !== nextProject;
    projectId = nextProject;
    summary.textContent = projectId ? '加载中…' : '';
    summary.removeAttribute('title');
    taskView.setMap(null);
    if (changedProject) {
      query.value = '';
      status.value = 'all';
      applyFilter();
    }
    tree.setHidden(null);
    if (!projectId) return;
    const valid = () => version === request && nextProject === nav.state.target?.project_id;
    try {
      const data = await api(`nav?project_id=${encodeURIComponent(projectId)}`, { signal: controller.signal });
      if (!valid()) return;
      const tasks = data.tasks || [];
      const orphans = data.orphan_runs || [];
      const runs = [...tasks.flatMap((task) => task.runs || []), ...orphans];
      summary.textContent = `${tasks.length} 任务 · ${runs.length} 运行`;
      const archived = tasks.filter((task) => task.archived).length;
      summary.title = `普通任务 ${tasks.length - archived} · 归档任务 ${archived}\n运行中 ${runs.filter((run) => run.status === 'running').length} · 失败 ${runs.filter((run) => run.status === 'failed').length} · 孤立运行 ${orphans.length}`;
      nav.setTasks(data.tasks || []);
      tree.setHidden(data.nav_hidden || []);
      taskView.setMap({ tasks: data.tasks || [], deleted_tasks: data.deleted_tasks || [], orphan_runs: data.orphan_runs || [] });
      nav.emit();
    } catch (error) {
      if (!valid()) return;
      summary.textContent = '统计加载失败';
      flash(`导航数据加载失败：${error.message}`);
    }
  }

  // 治理写入后必须重载；仅按项目变化触发的 loadNav 会因项目未变而早退。
  function reloadNav() {
    return loadNav(true);
  }

  nav.subscribe(() => {
    void loadNav();
  });

  session.subscribe?.((prefs) => {
    taskView.setSort(prefs.nav_sort || 'default');
    tree.setSort(prefs.nav_sort || 'default');
    taskView.setStyle(prefs.task_view || 'indent');
    const select = document.getElementById('task-view-select');
    if (select && select.value !== (prefs.task_view || 'indent')) select.value = prefs.task_view || 'indent';
  });

  const styleSelect = document.getElementById('task-view-select');
  if (styleSelect) {
    styleSelect.value = session.preferences.task_view || 'indent';
    taskView.setStyle(session.preferences.task_view || 'indent');
    styleSelect.onchange = () => {
      taskView.setStyle(styleSelect.value);
      session.save({ task_view: styleSelect.value }).catch((error) => flash(`任务视图保存失败：${error.message}`));
    };
  }

  return { host, addButton, loadNav, reloadNav,
    setTaskViewStyle: (value) => taskView.setStyle(value),
  };
}
