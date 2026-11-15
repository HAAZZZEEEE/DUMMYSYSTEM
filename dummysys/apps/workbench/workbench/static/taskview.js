// 上组 Task/Run 关系视图：两种样式共用同一份 /nav 数据，不展开 task/run 子文件夹。
import { mark, target } from './api.js';
import { metadata } from './actions.js';
import { icon } from './icons.js';
import { preserveNavScroll } from './interaction.js';
import { sortNav } from './navsort.js';
import { recordDate, recordDirectoryLabel, recordTime } from './record-label.js';

// Run 状态迁移图：当前状态 → [{to, label, icon, danger}]
const RUN_TRANSITIONS = {
  planned: [
    { to: 'running', label: '开始', icon: 'play' },
    { to: 'cancelled', label: '取消', icon: 'ban', danger: true },
  ],
  running: [
    { to: 'completed', label: '完成', icon: 'check' },
    { to: 'failed', label: '失败', icon: 'xmark', danger: true },
    { to: 'cancelled', label: '取消', icon: 'ban', danger: true },
  ],
  completed: [],
  failed: [],
  cancelled: [],
};

const STYLES = new Set(['indent', 'cards']);
const TASK_LIMIT = 5;
const STATUS_ICONS = { completed: 'check', running: 'play', failed: 'xmark', cancelled: 'ban', planned: 'clock', archived: 'archive', deleted: 'xmark' };
const TASK_STATUS = { active: '进行中', blocked: '受阻', awaiting_acceptance: '待验收', completed: '已完成', cancelled: '已取消' };
const STATUS_TEXT = { completed: '完成', running: '运行中', failed: '失败', cancelled: '取消', planned: '计划', archived: '已归档', deleted: '已删除', unknown: '未知' };
const STATUS_ORDER = ['completed', 'running', 'failed', 'cancelled', 'planned', 'archived', 'unknown'];
// 闭环（completed）与取消（cancelled）之外的状态（failed/running/planned/缺失）保留展开，便于关注未收口的运行。
const SETTLED = new Set(['completed', 'cancelled', 'archived']);
const shortDate = (value) => {
  const digits = String(value || '').slice(0, 10).replace(/-/g, '');
  return /^\d{8}$/.test(digits) ? `${digits.slice(4, 6)}-${digits.slice(6, 8)}` : '';
};

export function createTaskView(nav, actions, flash, ptr) {
  const host = mark(document.createElement('div'), 'task-view');
  host.className = 'task-view';
  host.dataset.taskView = 'indent';
  host.setAttribute('role', 'group');
  host.setAttribute('aria-label', '任务与运行');
  let payload = null;
  let style = 'indent';
  let sort = 'default';
  let query = '';
  let range = 'all';
  // task.name -> true 折叠 / false 展开；未手动切换过时按 Run 状态取默认。
  const folds = new Map();
  const completedOpen = new Map();
  const archiveOpen = new Map();
  const projectKey = () => nav.state.target?.project_id || '';
  const taskListOpen = new Map();
  let lastScope = null;
  let runGroupId = 0;

  const foldKey = (task) => JSON.stringify([projectKey(), task.task_id || task.name]);
  function contains(value, scope = nav.scopeTarget()) {
    return value && scope && value.project_id === scope.project_id && value.root_id === scope.root_id &&
      (scope.relative_path === value.relative_path || scope.relative_path.startsWith(`${value.relative_path}/`));
  }
  function selectedTask(task, scope) {
    return [task.docs, task.resource].some((value) => contains(value, scope));
  }
  function runTitle(run) {
    return run.title === run.name ? recordDirectoryLabel(run.name)?.title || run.title : run.title;
  }
  function matchesTask(task) {
    return !query || [task.title, task.name, `#${task.task_number}`, TASK_STATUS[task.status],
      ...task.runs.map((run) => [run.title, run.name, STATUS_TEXT[run.status]].join(' '))]
      .join(' ').toLocaleLowerCase().includes(query);
  }

  function statusMark(status) {
    const span = document.createElement('span');
    span.className = `tv-status tv-status-${status || 'unknown'}`;
    span.setAttribute('aria-hidden', 'true');
    span.append(icon(STATUS_ICONS[status] || 'clock'));
    span.title = STATUS_TEXT[status || 'unknown'] || status;
    return span;
  }

  function defaultFolded(task) {
    return task.runs.length > 0 && task.runs.every((run) => SETTLED.has(run.status));
  }

  function foldedOf(task) {
    return folds.get(foldKey(task)) ?? defaultFolded(task);
  }

  function setFolded(task, folded) {
    folds.set(foldKey(task), folded);
    render();
  }

  function runSummary(task) {
    // 折叠后代替 Run 列表的一行摘要：状态计数 + 运行日期跨度。
    const line = document.createElement('div');
    line.className = 'tv-run-summary';
    mark(line, 'run-summary');
    if (!task.runs.length) {
      line.textContent = '暂无运行';
      return line;
    }
    const counts = new Map();
    for (const run of task.runs) {
      const status = run.status || 'unknown';
      counts.set(status, (counts.get(status) || 0) + 1);
    }
    const parts = [];
    for (const status of STATUS_ORDER) {
      if (!counts.has(status)) continue;
      const part = document.createElement('span');
      part.className = `tv-status-${status}`;
      part.textContent = `${counts.get(status)} ${STATUS_TEXT[status]}`;
      parts.push(part);
    }
    const dates = task.runs.map((run) => shortDate(run.created_at)).filter(Boolean).sort();
    if (dates.length) {
      const span = dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]}→${dates[dates.length - 1]}`;
      const part = document.createElement('span');
      part.textContent = span;
      parts.push(part);
    }
    parts.forEach((part, index) => {
      if (index) line.append(' · ');
      line.append(part);
    });
    line.title = task.runs.map((run) => `${STATUS_TEXT[run.status || 'unknown']}｜${run.title}`).join('\n');
    return line;
  }

  function go(value, info) {
    if (!value) return;
    if (nav.state.loading) return;
    if (info && info.available === false) { flash(info.reason || '此目标不可用'); return; }
    nav.go(target(value));
  }

  function row(spec) {
    // spec: {id, testid, target, title, meta, info, onActivate, depth, classes}
    const line = document.createElement('div');
    line.className = `tv-row ${spec.classes || ''}`.trim();
    line.setAttribute('role', 'treeitem');
    line.tabIndex = -1;
    line.style.setProperty('--tv-depth', spec.depth || 0);
    if (spec.testid) mark(line, spec.testid, spec.target);
    if (spec.target) line.dataset.targetKey = JSON.stringify(target(spec.target));
    const selected = contains(spec.target);
    line.setAttribute('aria-selected', String(!!selected));
    const label = document.createElement('span');
    label.className = 'tv-label';
    label.textContent = spec.title;
    label.title = spec.title;
    const meta = document.createElement('span');
    meta.className = 'tv-meta';
    meta.textContent = spec.meta || '';
    if (spec.meta) meta.title = spec.meta;
    const text = document.createElement('div');
    text.className = 'tv-run-text';
    text.append(label, meta);
    line.append(text);
    line.title = spec.info?.reason || spec.info?.native_path || spec.title;
    line.onclick = (event) => { event.stopPropagation(); spec.onActivate(); };
    line.onkeydown = (event) => {
      if (event.target !== line) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); spec.onActivate(); }
    };
    return line;
  }

  function taskCard(task) {
    const open = !!query || !foldedOf(task);
    const card = document.createElement('div');
    card.className = 'tv-task';
    card.dataset.taskName = task.name;

    const head = document.createElement('div');
    head.className = 'tv-task-head';
    head.setAttribute('role', 'treeitem');
    head.tabIndex = -1;
    const snap = task.target ? target(task.target) : null;
    if (snap) mark(head, 'task-node', snap);
    const selected = selectedTask(task);
    card.classList.toggle('tv-current', selected);
    head.setAttribute('aria-selected', String(!!selected));
    head.setAttribute('aria-expanded', String(open));

    const arrow = document.createElement('button');
    arrow.type = 'button';
    arrow.className = 'tv-toggle';
    arrow.tabIndex = -1;
    arrow.append(icon('chevron'));
    arrow.setAttribute('aria-label', `${open ? '折叠' : '展开'}任务：${task.title}`);
    arrow.onclick = (event) => {
      event.stopPropagation();
      setFolded(task, open);
      [...host.querySelectorAll('.tv-task')].find((item) => item.dataset.taskName === task.name)
        ?.querySelector('.tv-toggle')?.focus({ preventScroll: true });
    };
    arrow.onkeydown = (event) => event.stopPropagation();

    const label = document.createElement('span');
    label.className = 'tv-label';
    label.textContent = task.title;
    label.title = task.name;
    const number = document.createElement('span');
    number.className = 'tv-task-number';
    if (task.task_number != null) {
      const value = mark(document.createElement('span'), 'task-number');
      value.textContent = `#${task.task_number}`;
      number.append('任务 ', value);
    }
    number.title = `任务序号：${task.task_number ?? '未提供'}`;
    const meta = document.createElement('span');
    meta.className = 'tv-meta';
    meta.textContent = [recordDate(task.date) || task.date, TASK_STATUS[task.status] || task.status,
      task.deleted ? '已删除' : task.archived ? '已归档' : '', task.docs_missing ? '仅资源' : '']
      .filter(Boolean).join(' · ');
    const minor = document.createElement('div');
    minor.className = 'tv-task-meta';
    minor.append(number, meta);
    const heading = document.createElement('div');
    heading.className = 'tv-task-text';
    heading.append(minor, label);

    // 治理动作；不可用项置灰并保留原因。分组横线按相近功能分开。
    const sep = { separator: true };
    const menu = task.target
      ? actions.menuButton(task.target, metadata(task), task.title, [
          // 日常操作
          { id: 'edit-task', label: '编辑任务…', onClick: () => ptr.editTask(task) },
          { id: 'new-run', label: '新建运行…', onClick: () => ptr.createRun(task) },
          sep,
          // 变更
          { id: 'handoff-task', label: '交接负责人…', onClick: () => ptr.handoffTask(task) },
          { id: 'rename-task', label: '改名…', onClick: () => ptr.renameTask(task) },
          { id: 'move-task', label: '移动到…', onClick: () => ptr.moveTask(task) },
          sep,
          // 归档与删除
          { id: 'archive-task', label: '归档…', onClick: () => ptr.archiveTask(task) },
          { id: 'unarchive-task', label: '取消归档…', onClick: () => ptr.unarchiveTask(task) },
          { id: 'delete-task', label: '删除…', onClick: () => ptr.deleteTask(task) },
          { id: 'undelete-task', label: '取消删除…', onClick: () => ptr.undeleteTask(task) },
        ].filter((item) => {
          if (task.deleted) return item.id === 'undelete-task';
          if (item.id === 'archive-task') return !task.archived;
          if (item.id === 'unarchive-task') return !!task.archived;
          if (item.id === 'undelete-task') return false;
          if (item.id === 'move-task') return !task.archived;
          return true;
        }))
      : document.createElement('span');
    menu.disabled = nav.state.loading;

    head.append(arrow, heading, menu);
    if (task.target) actions.bindContextMenu(head, menu);
    const activate = () => {
      if (nav.state.loading) return;
      // 与高亮状态一致：浏览其 Run、子目录或资源时，标题仍切换折叠。
      if (selected) { setFolded(task, open); return; }
      go(task.target);
    };
    head.onclick = (event) => {
      event.stopPropagation();
      activate();
    };
    head.onkeydown = (event) => {
      if (event.target !== head) return;
      if (event.key === 'Enter') { event.preventDefault(); activate(); }
      if (event.key === ' ' || (event.key === 'ArrowLeft' && open) || (event.key === 'ArrowRight' && !open)) {
        event.preventDefault();
        setFolded(task, open);
      }
    };
    card.append(head);

    if (open) {
      const list = document.createElement('div');
      list.className = 'tv-runs';
      list.setAttribute('role', 'group');
      list.id = `task-runs-${++runGroupId}`;
      head.setAttribute('aria-owns', list.id);
      if (task.runs.length) {
        const caption = document.createElement('div');
        caption.className = 'tv-runs-caption';
        caption.textContent = `运行记录 · ${task.runs.length}`;
        list.append(caption);
      }
      if (!task.runs.length) {
        const empty = document.createElement('div');
        empty.className = 'tv-empty';
        empty.textContent = '暂无运行';
        list.append(empty);
      }
      for (const run of sortNav(task.runs, sort)) {
        const line = row({
          testid: 'run-node', target: run.target, depth: 1,
          title: runTitle(run),
          meta: [STATUS_TEXT[run.status] || run.status || '状态未知', recordTime(run.created_at, run.name)].filter(Boolean).join(' · '),
          info: run, classes: `tv-run tv-status-line-${run.status || 'unknown'}`,
          onActivate: () => go(run.target, run),
        });
        line.prepend(statusMark(run.status));
        const tools = document.createElement('div');
        tools.className = 'tv-run-tools';
        // 仍从各自的 Run 触发原有状态迁移与操作。
        for (const t of RUN_TRANSITIONS[run.status] || []) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `tv-status-btn${t.danger ? ' danger' : ''}`;
          btn.append(icon(t.icon));
          btn.title = t.label;
          btn.setAttribute('aria-label', t.label);
          btn.onclick = (event) => { event.stopPropagation(); ptr.quickStatus(task, run, t.to); };
          tools.append(btn);
        }
        const runMenu = actions.menuButton(run.target, metadata(run), run.title, [
          // 日常操作
          { id: 'finish-run', label: '结束运行…', onClick: () => ptr.finishRun(task, run) },
          { id: 'update-run', label: '补写…', onClick: () => ptr.updateRun(task, run) },
          { id: 'rename-run', label: '改名…', onClick: () => ptr.renameRun(task, run) },
          { separator: true },
          // 归档与删除
          { id: 'archive-run', label: '归档…', onClick: () => ptr.archiveRun(task, run) },
          { id: 'unarchive-run', label: '取消归档…', onClick: () => ptr.unarchiveRun(task, run) },
          { id: 'delete-run', label: '删除…', onClick: () => ptr.deleteRun(task, run) },
          { id: 'undelete-run', label: '取消删除…', onClick: () => ptr.undeleteRun(task, run) },
        ]);
        runMenu.disabled = nav.state.loading;
        tools.append(runMenu);
        line.append(tools);
        actions.bindContextMenu(line, runMenu);
        list.append(line);
      }
      card.append(list);
    } else {
      card.append(runSummary(task));
    }
    return card;
  }

  function orphanCard(run) {
    const line = row({
      testid: 'orphan-run-node', target: run.target, depth: 0,
      title: runTitle(run), meta: run.location_hint || run.parent_name || '',
      info: run, classes: `tv-run tv-orphan tv-status-line-${run.status || 'unknown'}`,
      onActivate: () => go(run.target, run),
    });
    line.prepend(statusMark(run.status));
    // 孤立 Run 无 Task 身份，只能浏览。
    const runMenu = actions.menuButton(run.target, metadata(run), run.title, [
      { id: 'archive-run', label: '归档', disabled: true, reason: '孤立运行缺 task_id，无法治理' },
      { id: 'delete-run', label: '删除', disabled: true, reason: '孤立运行缺 task_id，无法治理' },
    ]);
    runMenu.disabled = nav.state.loading;
    line.append(runMenu);
    actions.bindContextMenu(line, runMenu);
    return line;
  }

  function renderTasks(tasks, container, label) {
    container.setAttribute('role', 'tree');
    container.setAttribute('aria-label', label);
    for (const task of sortNav(tasks, sort)) {
      const card = taskCard(task);
      if (style === 'cards') card.classList.add('tv-card');
      container.append(card);
    }
  }

  function renderTaskList(tasks, revealScope) {
    if (!tasks.length) return;
    const ordered = sortNav(tasks, sort);
    const key = projectKey();
    if (revealScope && ordered.slice(TASK_LIMIT).some((task) => selectedTask(task))) taskListOpen.set(key, true);
    const expanded = !!query || taskListOpen.get(key) || false;
    const list = document.createElement('div');
    list.id = 'visible-task-list';
    renderTasks(expanded ? ordered : ordered.slice(0, TASK_LIMIT), list, '当前任务');
    host.append(list);
    if (query || ordered.length <= TASK_LIMIT) return;
    const button = mark(document.createElement('button'), 'task-list-toggle');
    button.type = 'button';
    button.className = 'tv-more';
    button.setAttribute('aria-expanded', String(expanded));
    button.setAttribute('aria-controls', list.id);
    const label = expanded ? `收起到 ${TASK_LIMIT} 个任务` : `展开其余 ${ordered.length - TASK_LIMIT} 个任务`;
    button.setAttribute('aria-label', label);
    button.title = label;
    button.append(icon('chevronsDown'), label);
    button.onclick = () => {
      taskListOpen.set(key, !expanded);
      render();
      host.querySelector('[data-testid="task-list-toggle"]')?.focus({ preventScroll: true });
    };
    host.append(button);
  }

  function renderHistory(tasks, testid, label, opened, forceOpen, revealScope, defaultOpen = false) {
    if (!tasks.length) return;
    const key = projectKey();
    const box = mark(document.createElement('details'), testid);
    box.className = 'tv-archive';
    if (revealScope && tasks.some((task) => selectedTask(task))) opened.set(key, true);
    box.open = forceOpen || (opened.get(key) ?? defaultOpen);
    const summary = document.createElement('summary');
    summary.textContent = `${label}（${tasks.length}）`;
    box.append(summary);
    const list = document.createElement('div');
    renderTasks(tasks, list, label);
    box.append(list);
    box.ontoggle = () => {
      if (!box.isConnected) return;
      if (!forceOpen) opened.set(key, box.open);
      host.dispatchEvent(new CustomEvent('nav-expand-state', { bubbles: true }));
    };
    host.append(box);
  }

  function renderOrphans(runs) {
    if (!runs.length) return;
    const block = document.createElement('div');
    block.className = 'tv-orphans';
    const title = document.createElement('div');
    title.className = 'tv-group-title';
    title.textContent = '孤立运行';
    block.append(title);
    const list = document.createElement('div');
    list.setAttribute('role', 'tree');
    list.setAttribute('aria-label', '孤立运行');
    for (const run of sortNav(runs, sort)) list.append(orphanCard(run));
    block.append(list);
    host.append(block);
  }

  function focusItem(item, preventScroll = false) {
    if (!item) return;
    item.closest('[role="tree"]').querySelector('[role="treeitem"][tabindex="0"]')?.setAttribute('tabindex', '-1');
    item.tabIndex = 0;
    item.focus({ preventScroll });
  }

  host.addEventListener('keydown', (event) => {
    const item = event.target;
    if (event.defaultPrevented || !item.matches('[role="treeitem"]')) return;
    const items = [...item.closest('[role="tree"]').querySelectorAll('[role="treeitem"]')];
    const index = items.indexOf(item);
    const card = item.closest('.tv-task');
    const destination = {
      ArrowUp: () => items[index - 1],
      ArrowDown: () => items[index + 1],
      Home: () => items[0],
      End: () => items.at(-1),
      ArrowLeft: () => item.matches('.tv-run') ? card?.querySelector('.tv-task-head') : null,
      ArrowRight: () => item.matches('.tv-task-head') ? card?.querySelector('.tv-run') : null,
    }[event.key];
    if (destination) {
      event.preventDefault();
      focusItem(destination());
    }
  });

  function render() {
    const active = document.activeElement;
    const inside = host.contains(active);
    const focusedKey = inside && active.matches('[role="treeitem"]') ? active.dataset.target : null;
    preserveNavScroll(host, renderContent);
    if (inside && active.dataset.testid === 'task-list-toggle') {
      host.querySelector('[data-testid="task-list-toggle"]')?.focus({ preventScroll: true });
    } else if (focusedKey) {
      const item = [...host.querySelectorAll('[role="treeitem"][data-target]')]
        .find((row) => row.dataset.target === focusedKey && !row.closest('details:not([open])'));
      focusItem(item, true);
    }
  }

  function renderContent() {
    host.replaceChildren();
    runGroupId = 0;
    host.dataset.taskView = style;
    if (!payload) return;
    const scope = nav.scopeTarget();
    const scopeKey = JSON.stringify(scope || null);
    const revealScope = scopeKey !== lastScope;
    lastScope = scopeKey;
    const tasks = payload.tasks.filter(matchesTask).filter((task) => {
      if (range === 'active') return !task.archived && task.status === 'active';
      if (range === 'completed') return !task.archived && task.status === 'completed';
      return true;
    });
    const orphans = range === 'all' ? payload.orphan_runs.filter((run) =>
      !query || [run.title, run.name, run.location_hint].join(' ').toLocaleLowerCase().includes(query)) : [];
    if (!tasks.length && !orphans.length) {
      const empty = document.createElement('div');
      empty.className = 'tv-empty';
      empty.textContent = query || range !== 'all' ? '没有匹配的任务或运行' : '暂无任务';
      host.append(empty);
    } else {
      if (revealScope && scope) {
        for (const task of tasks) if (task.runs.some((run) => contains(run.target))) folds.set(foldKey(task), false);
      }
      const ordinary = tasks.filter((task) => !task.archived && task.status !== 'completed');
      renderTaskList(ordinary, revealScope);
      renderHistory(tasks.filter((task) => !task.archived && task.status === 'completed'),
        'completed-tasks', '已完成任务', completedOpen, !!query || range === 'completed', revealScope, !ordinary.length);
      renderHistory(tasks.filter((task) => task.archived), 'archived-tasks', '归档任务', archiveOpen, !!query, revealScope);
      renderOrphans(orphans);
    }
    actions.syncMenu();
    for (const tree of host.querySelectorAll('[role="tree"]')) {
      tree.querySelector('[role="treeitem"]')?.setAttribute('tabindex', '0');
    }
    // 供工具栏单按钮同步展开/折叠态；stopPropagation 的行内折叠不冒泡 click，故用自定义事件。
    host.dispatchEvent(new CustomEvent('nav-expand-state', { bubbles: true }));
  }

  function setAllExpanded(expanded) {
    const key = projectKey();
    for (const group of [taskListOpen, completedOpen, archiveOpen]) group.set(key, expanded);
    for (const task of payload?.tasks || []) folds.set(foldKey(task), !expanded);
    render();
  }

  nav.subscribe(render);
  return {
    host,
    setMap(data) { payload = data; render(); },
    setFilter(text, status) { query = text.trim().toLocaleLowerCase(); range = status; render(); },
    get tasks() { return payload?.tasks || []; },
    setStyle(next) { if (!STYLES.has(next) || next === style) return; style = next; render(); },
    get style() { return style; },
    setSort(next) { if (sort === next) return; sort = next; lastScope = null; render(); },
    expandAll() { setAllExpanded(true); },
    collapseAll() { setAllExpanded(false); },
    hasExpanded() {
      return !!taskListOpen.get(projectKey()) ||
        !!host.querySelector('details[open], .tv-task-head[aria-expanded="true"]');
    },
  };
}
