import { measure } from './diagnostics.js';
import { api } from './api.js';
import { createStorage } from './storage.js';

const labels = { active: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消',
  blocked: '受阻', awaiting_acceptance: '待验收', running: '运行中', planned: '待执行',
  failed: '失败', archived: '已归档', unknown: '未记录' };
const number = (value) => Number(value || 0).toLocaleString('zh-CN');
function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}
function state(value) {
  const known = Object.hasOwn(labels, value) ? value : 'unknown';
  return node('span', `ov-state ov-${known}`, labels[known]);
}
function heading(kicker, title, caption) {
  const header = node('header', 'ov-panel-heading');
  const group = node('div');
  group.append(node('span', 'ov-kicker', kicker), node('h2', '', title));
  header.append(group);
  if (caption) header.append(node('span', 'ov-caption', caption));
  return header;
}
function dateLabel(value) {
  if (!value) return '时间未记录';
  const compact = String(value).match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);
  if (compact) return `${compact[1]}-${compact[2]}-${compact[3]} ${compact[4]}:${compact[5]}`;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未记录' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function createOverview(nav) {
  const storage = createStorage(nav);
  const host = document.getElementById('overview');
  let version = 0, controller, lastGeneration = -1;
  let filter = 'all', data, showUnavailableServers = false;
  function projectCard(project, index) {
    const card = node('button', 'ov-project');
    card.type = 'button';
    card.dataset.projectId = project.project_id;
    card.setAttribute('aria-label', `打开项目：${project.title}`);
    card.onclick = () => nav.go({ project_id: project.project_id, root_id: '', relative_path: '' });
    const top = node('div', 'ov-project-top');
    top.append(node('span', 'ov-coordinate', String(index + 1).padStart(2, '0')), state(project.status));
    card.append(top, node('h3', '', project.title));
    if (project.unavailable) {
      card.append(node('p', 'ov-muted', '项目记录暂不可读，点击查看'));
      return card;
    }
    const c = project.counts;
    const ratio = c.tasks ? Math.round((c.completed || 0) / c.tasks * 100) : 0;
    const metrics = node('div', 'ov-project-metrics');
    const open = node('div'); open.append(node('strong', '', number(c.open_tasks)), node('span', '', '待推进任务'));
    const runs = node('div'); runs.append(node('strong', '', number(c.running)), node('span', '', '运行中记录'));
    metrics.append(open, runs);
    const progress = node('div', 'ov-progress');
    progress.setAttribute('aria-label', `任务已完成 ${c.completed || 0} / ${c.tasks}`);
    const fill = node('span'); fill.style.width = `${ratio}%`; progress.append(fill);
    const foot = node('div', 'ov-project-foot');
    foot.append(node('span', '', `${number(c.completed)} / ${number(c.tasks)} 任务已完成`), node('span', '', `${ratio}%`));
    const trail = node('div', 'ov-run-trail');
    trail.setAttribute('aria-label', '最近执行状态');
    for (const status of project.run_states) {
      const dot = node('span', `ov-run-cell ov-${Object.hasOwn(labels, status) ? status : 'unknown'}`);
      dot.title = labels[status] || '未记录'; trail.append(dot);
    }
    if (!project.run_states.length) trail.append(node('span', 'ov-muted', '尚无执行记录'));
    const tail = node('div', 'ov-tile-tail');
    tail.append(trail, node('span', 'ov-enter', '进入项目 ↗'));
    card.append(metrics, progress, foot, tail);
    return card;
  }
  function render() { return measure('overview', renderContent); }
  function renderContent() {
    host.replaceChildren();
    const hero = node('header', 'ov-hero');
    const intro = node('div');
    intro.append(node('span', 'ov-kicker', 'DUMMYSYS · 工作空间'), node('h2', '', '把每一步，放回全景。'),
      node('p', 'ov-muted', '项目是版图，任务是方向，执行留下足迹。'));
    const refresh = node('button', 'btn ghost ov-refresh', '↻ 刷新沙盘');
    refresh.type = 'button'; refresh.onclick = load;
    hero.append(intro, refresh); host.append(hero);

    const metrics = node('div', 'ov-metrics');
    for (const [key, title, detail] of [['projects', '项目版图', '未归档、未删除项目'],
      ['open_tasks', '待推进任务', '未归档且尚未结束'], ['running', '运行中记录', '按 Run 登记状态'],
      ['runs', '执行足迹', '含项目内归档记录']]) {
      const metric = node('div', 'ov-metric');
      metric.append(node('span', 'ov-metric-label', title), node('strong', '', number(data.totals[key])), node('small', 'ov-muted', detail));
      metrics.append(metric);
    }
    host.append(metrics);
    const inventory = data.server_inventory;
    const servers = node('section', 'ov-panel ov-servers');
    servers.setAttribute('aria-label', '服务器档案');
    servers.append(heading('服务器', '服务器档案', `${inventory?.servers?.length || 0} 条登记`));
    if (!inventory?.available) servers.append(node('p', 'ov-notice', inventory?.message || '服务器档案暂不可用'));
    else if (!inventory.servers.length) servers.append(node('p', 'ov-empty', '尚未登记服务器。'));
    else {
      const toggle = node('button', 'btn ghost', '显示无法连接的服务器');
      toggle.type = 'button'; toggle.setAttribute('aria-pressed', String(showUnavailableServers));
      const count = node('span', 'ov-caption');
      servers.append(toggle, count);
      const scroll = node('div', 'ov-server-scroll');
      scroll.tabIndex = 0; scroll.setAttribute('aria-label', '服务器列表，可横向滚动');
      const table = node('table', 'ov-server-table');
      const head = node('thead'), titles = node('tr');
      for (const title of ['代际', '产品', '芯片', '名字', 'IP / 端口', '账号', '密码获取']) {
        const th = node('th', '', title); th.scope = 'col'; titles.append(th);
      }
      head.append(titles); const body = node('tbody');
      function renderServers() {
        body.replaceChildren();
        const visible = inventory.servers.filter(server => showUnavailableServers || server.reachable);
        count.textContent = `显示 ${visible.length} / ${inventory.servers.length} 条 · 按最近核查结果`;
        for (const server of visible) {
          const row = node('tr');
          const values = [server.generation, server.product, server.chip, server.name, `${server.ip}:${server.port}`, server.account, server.password_access];
          values.forEach((value, index) => {
            const text = value || '未登记';
            const cell = node('td', '', index < 3 ? String(text).replace(/（[^）]*）/g, '') : text);
            if (index < 3) cell.title = text;
            row.append(cell);
          });
          body.append(row);
        }
        if (!visible.length) {
          const cell = node('td', 'ov-empty', '暂无可连接记录，可打开上方开关查看全部。');
          cell.colSpan = 7; const row = node('tr'); row.append(cell); body.append(row);
        }
      }
      toggle.onclick = () => { showUnavailableServers = !showUnavailableServers;
        toggle.setAttribute('aria-pressed', String(showUnavailableServers)); renderServers(); };
      renderServers();
      table.append(head, body); scroll.append(table); servers.append(scroll);
    }
    host.append(servers);
    const storagePanel = node('section', 'ov-panel ov-storage');
    storagePanel.id = 'overview-storage'; storagePanel.setAttribute('aria-label', '存储空间看板');
    host.append(storagePanel); storage.render();
    const layout = node('div', 'ov-layout');
    const board = node('section', 'ov-board');
    board.append(heading('01 / 项目沙盘', '正在展开的版图', `${data.projects.length} 个项目`));
    const filters = node('div', 'ov-filters'); filters.setAttribute('role', 'group'); filters.setAttribute('aria-label', '沙盘筛选');
    for (const [key, label] of [['all', '全部'], ['open', '有待推进'], ['running', '有运行中记录']]) {
      const button = node('button', 'ov-filter', label); button.type = 'button';
      button.setAttribute('aria-pressed', String(filter === key));
      button.onclick = () => {
        filter = key;
        for (const item of filters.children) item.setAttribute('aria-pressed', String(item === button));
        renderProjects();
      };
      filters.append(button);
    }
    const tiles = node('div', 'ov-projects'); tiles.dataset.testid = 'overview-projects';
    function renderProjects() {
      const projects = data.projects.filter(p => filter === 'all' || (filter === 'open' ? p.counts?.open_tasks : p.counts?.running));
      tiles.replaceChildren(...projects.map(projectCard));
      if (!projects.length) tiles.append(node('p', 'ov-empty', data.projects.length ? '这个区域暂时没有项目。' : '还没有项目，从左侧项目入口开始建立你的版图。'));
    }
    renderProjects(); board.append(filters, tiles);
    const legend = node('div', 'ov-legend');
    legend.append(node('span', '', '小格表示最近执行：'), state('completed'), state('running'), state('failed'), state('planned'));
    board.append(legend);
    const rail = node('aside', 'ov-rail');
    const usage = node('section', 'ov-panel ov-usage'); usage.dataset.testid = 'overview-usage';
    usage.append(heading('02 / 命令热度', '调用 TOP 5', '累计'));
    if (data.usage.available) {
      const calls = node('div', 'ov-calls'); calls.append(node('strong', '', number(data.usage.total_calls)), node('span', 'ov-muted', '次 CLI 调用'));
      usage.append(calls);
      const ranking = node('ol', 'ov-ranking');
      const max = Math.max(1, ...data.usage.top.map(item => item.calls));
      for (const [index, item] of data.usage.top.entries()) {
        const row = node('li'); const line = node('div', 'ov-rank-line');
        line.append(node('span', 'ov-rank', String(index + 1).padStart(2, '0')), node('code', '', item.command), node('strong', '', number(item.calls)));
        const bar = node('div', 'ov-rank-bar'); const fill = node('span'); fill.style.width = `${item.calls / max * 100}%`; bar.append(fill);
        row.append(line, bar); ranking.append(row);
      }
      usage.append(ranking);
      usage.append(node('p', 'ov-footnote', data.usage.total_calls ? `从 ${dateLabel(data.usage.started_at)} 启用后累计；查询统计不计数。` : '统计已就绪，执行命令后这里会出现排行。'));
    } else usage.append(node('p', 'ov-empty', data.usage.message));
    const attention = node('section', 'ov-panel');
    attention.append(heading('03 / 留意一下', '等待下一步', `${data.attention_total} 项`));
    for (const item of data.attention) {
      const button = node('button', 'ov-attention'); button.type = 'button';
      button.append(state(item.status), node('strong', '', item.title), node('small', 'ov-muted', `${item.project_title} · #${item.number}`));
      button.onclick = () => nav.go(item.target); attention.append(button);
    }
    if (!data.attention.length) attention.append(node('p', 'ov-empty', '目前没有登记为受阻或待验收的任务。'));
    rail.append(usage, attention); layout.append(board, rail); host.append(layout);

    const recent = node('section', 'ov-panel ov-recent');
    recent.append(heading('04 / 执行足迹', '最近发生', '按创建时间'));
    const list = node('div', 'ov-activity');
    for (const run of data.recent_runs) {
      const button = node('button', 'ov-activity-row'); button.type = 'button';
      button.append(state(run.status)); const text = node('div');
      text.append(node('strong', '', run.title), node('small', 'ov-muted', run.project_title));
      button.append(text, node('time', 'ov-muted', dateLabel(run.created_at)));
      button.onclick = () => nav.go(run.target); list.append(button);
    }
    if (!data.recent_runs.length) list.append(node('p', 'ov-empty', '第一条执行记录会成为这里的起点。'));
    recent.append(list); host.append(recent);
    const footer = node('footer', 'ov-footer');
    footer.append(node('span', '', '来自当前治理记录 · 运行中不代表进程实时存活'), node('span', '', `快照更新 ${dateLabel(data.updated_at)}`));
    host.append(footer);
    if (data.diagnostics.length) host.append(node('p', 'ov-notice', `有 ${data.diagnostics.length} 项记录未能完整读取，当前统计可能不完整。`));
  }
  async function load() {
    if (nav.state.target) return;
    void storage.start();
    const current = ++version;
    controller?.abort(); controller = new AbortController();
    const ctx = nav.context();
    if (!data) host.replaceChildren(node('p', 'ov-empty', '正在读取工作区全景…'));
    host.setAttribute('aria-busy', 'true');
    const refresh = host.querySelector('.ov-refresh');
    if (refresh) { refresh.disabled = true; refresh.textContent = '正在更新…'; }
    try {
      const result = await api('overview', { signal: controller.signal });
      if (current !== version || !ctx.valid() || nav.state.target) return;
      data = result; render();
    } catch (error) {
      if (current !== version || !ctx.valid() || nav.state.target) return;
      const message = node('div', 'ov-notice', `沙盘加载失败：${error.message}`);
      const retry = node('button', 'btn ghost', '重新读取'); retry.onclick = load; message.append(retry);
      host.replaceChildren(message); data = null;
    } finally {
      if (current === version) host.setAttribute('aria-busy', 'false');
    }
  }
  nav.subscribe(s => {
    if (s.target) { controller?.abort(); storage.stop(); version++; return; }
    if (lastGeneration !== s.generation) { lastGeneration = s.generation; void load(); }
  });
  return { catalog() { if (!nav.state.target) void load(); } };
}
