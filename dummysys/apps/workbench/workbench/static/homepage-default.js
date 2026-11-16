// 默认项目看板复用导航投影；自定义页面仍由 homepage.js 隔离承载。
import { icon } from './icons.js';

const labels = { active:'进行中', completed:'已完成', blocked:'受阻',
  awaiting_acceptance:'待验收', cancelled:'已取消', archived:'已归档' };
const examples = [
  ['项目总览', '展示项目目标、任务进展、最近成果和常用入口。'],
  ['实验与数据', '展示关键指标、实验对比、最新结论和报告入口；先核对实际数据，不编造结果。'],
  ['资料与成果', '把重要文档、阶段结论、报告和常用资源整理成清晰的索引。'],
];
function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}
function button(className, text, action) {
  const el = node('button', className, text);
  el.type = 'button'; el.onclick = action;
  return el;
}
function section(title) {
  const el = node('section', 'dh-panel');
  el.setAttribute('aria-label', title);
  const header = node('div', 'dh-section-head');
  header.append(node('h2', '', title)); el.append(header);
  return el;
}
// 装饰性的待扩展画布，不参与导航、读屏或统计，也不模拟加载状态。
function draftSpace() {
  const space = node('div', 'dh-draft-space'); space.setAttribute('aria-hidden', 'true');
  const grid = node('div', 'dh-draft-grid');
  for (const [title, style, count] of [['项目目标', 'lines', 3], ['指标与图表', 'bars', 7], ['资料与成果', 'links', 3]]) {
    const slot = node('div', 'dh-draft-slot'), heading = node('div', 'dh-draft-title');
    heading.append(node('span', '', '＋'), node('span', '', title));
    const shapes = node('div', `dh-draft-${style}`);
    for (let i = 0; i < count; i++) shapes.append(node('i'));
    slot.append(heading, shapes); grid.append(slot);
  }
  for (let i = 0; i < 3; i++) grid.append(node('div', 'dh-draft-slot dh-draft-more'));
  space.append(grid); return space;
}
function guidance(projectName, projectId, valid) {
  const guide = node('section', 'dh-guide');
  guide.setAttribute('aria-label', '定制首页引导');
  guide.append(node('h2', '', '这只是首页的起点'),
    node('p', 'dh-muted', '项目目标、实验图表、常用资料……这里还可以放下更多。'),
    node('p', 'dh-muted', '选一个方向，把下面的话交给 Agent，让它为你补上专属首页。'));
  const choices = node('div', 'dh-examples');
  choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', '首页提示词示例');
  const prompt = node('textarea', 'dh-prompt');
  prompt.setAttribute('aria-label', '发给 Agent 的提示词，可编辑');
  prompt.spellcheck = false;
  const status = node('small', 'dh-muted', '发给你正在使用的 Agent，让它帮你把首页补完整。');
  status.setAttribute('role', 'status');
  function select(index) {
    [...choices.children].forEach((el, i) => el.setAttribute('aria-pressed', String(i === index)));
    prompt.value = `请为「${projectName}」制作一个 DUMMYSYS Workbench 自定义首页。先阅读项目说明与当前任务，${examples[index][1]}使用真实项目资料，保持简洁，并完成首页配置。`;
    status.textContent = '发给你正在使用的 Agent，让它帮你把首页补完整。';
  }
  examples.forEach(([label], index) => choices.append(button('dh-chip', label, () => select(index))));
  select(0);
  const setup = `项目标识：${projectId}。先按工作区 AGENTS 定位所属项目、登记资源根与相关说明。将 HTML 页面包放在该项目资源目录，例如 homepage/index.html；在项目资源根 workbench.json 中合入 schema_version: 1 与 homepage: {root_id: "resources", path: "homepage/index.html"}，保留原有配置字段。不要覆盖已有页面，完成后刷新 Workbench 验证。`;
  const copy = button('btn primary dh-copy', '复制提示词', async () => {
    if (!valid()) return;
    const text = prompt.value.endsWith(setup) ? prompt.value : `${prompt.value}\n\n${setup}`;
    copy.disabled = true;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(text);
      if (valid()) status.textContent = '已复制，发给你的 Agent 即可。';
    } catch {
      if (!valid()) return;
      prompt.value = text; prompt.focus(); prompt.select();
      status.textContent = '无法自动复制，请复制已选中的完整提示词。';
    } finally { copy.disabled = false; }
  });
  const footer = node('div', 'dh-guide-bottom'); footer.append(status, copy);
  guide.append(choices, prompt, footer);
  return guide;
}

export function defaultHomepage(data, project, nav, ctx) {
  const name = project?.title || '当前项目';
  const page = node('div', 'default-homepage'); page.dataset.testid = 'default-homepage';
  const content = node('div', 'dh-content'); page.append(content);
  const heading = node('header', 'dh-heading'), intro = node('div');
  intro.append(node('h1', '', '项目首页'), node('p', 'dh-muted', `${name}的概况先放在这里，更多内容留给你来定义。`));
  heading.append(intro, node('span', 'dh-badge', '首页草稿')); content.append(heading);
  const tasks = (data.tasks || []).filter(task => !task.archived);
  const runs = [...(data.tasks || []).flatMap(task => task.runs || []), ...(data.orphan_runs || [])];
  const running = runs.filter(run => (run.execution_status || run.status) === 'running').length;
  const completed = tasks.filter(task => task.status === 'completed').length;
  const pending = tasks.filter(task => !['completed', 'cancelled'].includes(task.status)).length;
  function metric(label, count, suffix) {
    const value = node('span'); value.setAttribute('aria-label', label);
    value.append(node('strong', '', count.toLocaleString('zh-CN')), document.createTextNode(suffix));
    return value;
  }
  const summary = node('div', 'dh-summary');
  summary.title = '任务不含归档记录；待推进包括进行中、受阻、待验收和未记录状态的任务。';
  const totals = node('p');
  totals.append(metric('全部任务', tasks.length, ' 项任务，已经完成 '), metric('已完成', completed, ' 项。'));
  summary.append(totals);
  if (pending) {
    const next = node('p', 'dh-active');
    next.append(document.createTextNode('还有 '), metric('待推进', pending, ' 项工作待推进。')); summary.append(next);
  } else summary.append(node('p', 'dh-active', tasks.length ? '当前任务均已结束。' : '从第一项工作开始，慢慢补全这一页。'));
  content.append(summary);
  const stats = node('div', 'dh-inline-stats'); stats.title = '执行记录含归档历史。';
  stats.append(metric('执行记录', runs.length, ' 次执行记录'), metric('运行中', running, ' 次正在运行'),
    metric('关联仓库', (data.roots || []).filter(root => root.kind === 'repo').length, ' 个关联仓库'));
  content.append(stats);
  if ((data.roots || []).some(root => ['docs', 'resources'].includes(root.kind) && !root.available))
    content.append(node('p', 'dh-notice', '部分项目目录暂不可读，统计仅包含可读取的记录。可从下方项目入口查看原因。'));
  const recent = section('最近任务'); recent.firstChild.append(node('span', 'dh-muted', '按创建时间'));
  const latest = [...tasks].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')) || b.task_number - a.task_number).slice(0, 3);
  for (const task of latest) {
    const row = button('dh-task', '', () => { if (ctx.valid()) nav.go(task.target); });
    row.disabled = !task.target;
    const status = node('span', 'dh-status', labels[task.status] || '未记录');
    if (task.status === 'active') status.classList.add('dh-active');
    row.append(icon(task.status === 'completed' ? 'check' : 'clock'), node('span', 'dh-task-title', task.title), status);
    recent.append(row);
  }
  if (!latest.length) recent.append(node('p', 'dh-empty dh-muted', '还没有任务。可以先浏览项目资料，再让 Agent 帮你安排第一项工作。'));
  content.append(recent);
  const entries = node('nav', 'dh-entries'); entries.setAttribute('aria-label', '项目入口');
  for (const root of data.roots || []) {
    const entry = button('dh-entry', root.kind === 'docs' ? '项目文档' : root.label, () => {
      if (ctx.valid()) nav.go({project_id:ctx.target.project_id, root_id:root.root_id, relative_path:''});
    });
    entry.title = !root.available ? (root.reason || '暂不可用') : `浏览${root.label}`;
    entry.append(icon('forward')); entries.append(entry);
  }
  if (!(data.roots || []).length) entries.append(node('p', 'dh-empty dh-muted', '尚未登记可浏览的项目目录。'));
  content.append(entries, draftSpace(), guidance(name, ctx.target.project_id, ctx.valid),
    node('p', 'dh-footnote dh-muted', '准备好后，自定义首页会接替这份草稿。'));
  return page;
}
