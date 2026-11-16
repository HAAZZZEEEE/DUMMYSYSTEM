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
function dateLabel(date) {
  const match = String(date || '').match(/^(\d{4})(\d{2})(\d{2})$/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : '日期未记录';
}
function guidance(projectName, projectId, valid) {
  const guide = node('section', 'dh-guide');
  guide.setAttribute('aria-label', '定制首页引导');
  guide.append(node('h2', '', '让 Agent 为这个项目做一个首页'),
    node('p', 'dh-muted', '这里先帮你汇总项目概况。想看实验对比、资料索引或阶段成果？把下面这句话交给你的 Agent。'));
  const choices = node('div', 'dh-examples');
  choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', '首页提示词示例');
  const prompt = node('textarea', 'dh-prompt');
  prompt.setAttribute('aria-label', '发给 Agent 的提示词，可编辑');
  prompt.spellcheck = false;
  const status = node('small', 'dh-muted', '复制后发给你正在使用的 Agent，可按需改写。');
  status.setAttribute('role', 'status');
  function select(index) {
    [...choices.children].forEach((el, i) => el.setAttribute('aria-pressed', String(i === index)));
    prompt.value = `请为「${projectName}」制作一个 DUMMYSYS Workbench 自定义首页。先阅读项目说明与当前任务，${examples[index][1]}使用真实项目资料，保持简洁，并完成首页配置。`;
    status.textContent = '复制后发给你正在使用的 Agent，可按需改写。';
  }
  examples.forEach(([label], index) => choices.append(button('dh-chip', label, () => select(index))));
  select(0);
  const copy = button('btn primary dh-copy', '复制提示词', async () => {
    if (!valid()) return;
    const text = `${prompt.value}\n\n项目标识：${projectId}。先按工作区 AGENTS 定位所属项目、登记资源根与相关说明。将 HTML 页面包放在该项目资源目录，例如 homepage/index.html；在项目资源根 workbench.json 中合入 schema_version: 1 与 homepage: {root_id: "resources", path: "homepage/index.html"}，保留原有配置字段。不要覆盖已有页面，完成后刷新 Workbench 验证。`;
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
  const heading = node('header', 'dh-heading'), intro = node('div');
  intro.append(node('h1', '', '项目概览'), node('p', 'dh-muted', `${name}的任务、执行与资料，集中在这里。`));
  heading.append(intro, node('span', 'dh-badge', '默认首页')); page.append(heading);
  // 与导航使用同一批记录，明确区分活跃任务与包含归档的执行历史。
  const tasks = (data.tasks || []).filter(task => !task.archived);
  const runs = [...(data.tasks || []).flatMap(task => task.runs || []), ...(data.orphan_runs || [])];
  const running = runs.filter(run => (run.execution_status || run.status) === 'running').length;
  const stats = node('div', 'dh-stats');
  const metrics = [
    ['全部任务', tasks.length, '不含已归档任务'],
    ['进行中', tasks.filter(task => task.status === 'active').length, '按任务登记状态'],
    ['已完成', tasks.filter(task => task.status === 'completed').length, '不含已归档任务'],
    ['执行记录', runs.length, `含归档记录 · ${running} 次运行中`],
  ];
  for (const [label, count, detail] of metrics) {
    const metric = node('div', 'dh-stat'); metric.setAttribute('aria-label', label);
    metric.append(node('span', 'dh-muted', label), node('strong', '', count.toLocaleString('zh-CN')), node('small', 'dh-muted', detail));
    stats.append(metric);
  }
  page.append(stats);
  if ((data.roots || []).some(root => ['docs', 'resources'].includes(root.kind) && !root.available))
    page.append(node('p', 'dh-notice', '部分项目目录暂不可读，统计仅包含可读取的记录。可从下方项目入口查看原因。'));
  const columns = node('div', 'dh-columns'), recent = section('最近任务'), entries = section('项目入口');
  recent.firstChild.append(node('span', 'dh-muted', '按创建时间'));
  const latest = [...tasks].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')) || b.task_number - a.task_number).slice(0, 3);
  for (const task of latest) {
    const row = button('dh-task', '', () => { if (ctx.valid()) nav.go(task.target); });
    row.disabled = !task.target;
    const text = node('span', 'dh-task-text');
    text.append(node('span', 'dh-task-title', task.title),
      node('small', 'dh-muted', `任务 ${task.task_number} · ${dateLabel(task.date)} · ${(task.runs || []).length} 次执行`));
    const status = node('span', 'dh-status', labels[task.status] || '未记录');
    if (task.status === 'active') status.classList.add('dh-active');
    row.append(icon(task.status === 'completed' ? 'check' : 'clock'), text, status); recent.append(row);
  }
  if (!latest.length) recent.append(node('p', 'dh-empty dh-muted', '还没有任务。可以先浏览项目资料，再让 Agent 帮你安排第一项工作。'));
  for (const root of data.roots || []) {
    const entry = button('dh-entry', '', () => {
      if (ctx.valid()) nav.go({project_id:ctx.target.project_id, root_id:root.root_id, relative_path:''});
    });
    const text = node('span', 'dh-entry-text');
    const detail = !root.available ? (root.reason || '暂不可用') :
      root.kind === 'docs' ? '说明、笔记与结论' : root.kind === 'resources' ? '报告、数据与执行产物' : '浏览已关联的代码仓库';
    text.append(node('span', '', root.kind === 'docs' ? '项目文档' : root.label), node('small', 'dh-muted', detail));
    entry.append(icon(root.kind === 'docs' ? 'document' : root.kind === 'repo' ? 'code' : 'folder'), text, icon('forward'));
    entries.append(entry);
  }
  if (!(data.roots || []).length) entries.append(node('p', 'dh-empty dh-muted', '尚未登记可浏览的项目目录。'));
  columns.append(recent, entries); page.append(columns, guidance(name, ctx.target.project_id, ctx.valid),
    node('p', 'dh-footnote dh-muted', '配置自定义首页后，它会替换这张默认看板。'));
  return page;
}
