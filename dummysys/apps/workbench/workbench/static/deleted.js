// 全局已删除栏：来源项目 → Task → Run；祖先只提供上下文，恢复绑定原身份。
import { api, mark } from './api.js';
import { preserveNavScroll } from './interaction.js';
import { sortNav } from './navsort.js';

export function createDeleted(nav, ptr, flash, session) {
  const host = mark(document.createElement('details'), 'deleted-items');
  host.className = 'tv-archive';
  const caption = document.createElement('summary');
  caption.textContent = '已删除';
  const body = document.createElement('div');
  host.append(caption, body);
  document.getElementById('sidebar-scroll').append(host);
  const open = new Map();
  let request = 0;
  let sort = 'default';
  let latest = null;
  session.subscribe((prefs) => {
    sort = prefs.nav_sort || 'default';
    if (latest) render(latest);
  });

  function restoreButton(id, label, callback, disabled = false, reason = '') {
    const button = mark(document.createElement('button'), id);
    button.type = 'button';
    button.className = 'btn ghost';
    button.textContent = label;
    button.disabled = disabled;
    button.title = reason || label;
    button.onclick = (event) => { event.preventDefault(); event.stopPropagation(); void callback(); };
    return button;
  }

  function label(text, target, deleted) {
    const link = document.createElement('button');
    link.type = 'button';
    link.className = 'btn ghost';
    link.textContent = text + (deleted ? '（已删除）' : '');
    link.onclick = (event) => { event.preventDefault(); event.stopPropagation(); if (target) nav.go(target); };
    return link;
  }

  function group(id, key, text) {
    const box = mark(document.createElement('details'), id);
    box.dataset.deletedKey = key;
    box.open = open.get(key) || false;
    box.style.margin = '6px 10px';
    const summary = document.createElement('summary');
    summary.textContent = text;
    box.append(summary);
    return { box, summary };
  }

  function runRow(run, task, blocked) {
    const row = mark(document.createElement('div'), 'deleted-run-node', run.target);
    row.style.margin = '4px 12px';
    row.append(label(`运行：${run.title}`, run.target, run.deleted));
    if (run.deleted) row.append(restoreButton('trash-restore-run', '恢复运行', () => ptr.undeleteRun(task, run),
      blocked || !task?.task_id || !run.run_id, blocked ? '请先恢复来源项目或任务' : '缺少Task/Run身份时不能恢复'));
    return row;
  }

  function render(data) {
    latest = data;
    preserveNavScroll(host, () => {
      for (const box of body.querySelectorAll('details[data-deleted-key]')) open.set(box.dataset.deletedKey, box.open);
      body.replaceChildren();
      caption.textContent = `已删除（${data.count}）`;
      for (const project of sortNav(data.projects || [], sort)) {
        const { box, summary } = group('deleted-project-group', project.project_id,
          `来源项目：${project.title}${project.deleted ? '（项目已删除）' : ''}`);
        summary.dataset.projectId = project.project_id;
        summary.append(label('查看来源项目', { project_id: project.project_id, root_id: '', relative_path: '' }, false));
        if (project.deleted) summary.append(restoreButton('trash-restore-project', '恢复项目',
          () => ptr.undeleteProject(project.project_id)));
        for (const task of sortNav(project.tasks, sort)) {
          const child = group('deleted-task-group', `${project.project_id}:${task.task_id || task.name}`,
            `任务：${task.title}${task.deleted ? '（已删除）' : ''}`);
          child.summary.append(label('查看任务', task.target, false));
          if (task.deleted) child.summary.append(restoreButton('trash-restore-task', '恢复任务',
            () => ptr.undeleteTask(task), project.deleted || !task.task_id,
            project.deleted ? '请先恢复来源项目' : '缺少Task身份时不能恢复'));
          for (const run of sortNav(task.runs, sort)) child.box.append(runRow(run, task, project.deleted || task.deleted));
          box.append(child.box);
        }
        for (const run of sortNav(project.orphan_runs || [], sort)) box.append(runRow(run, null, project.deleted));
        body.append(box);
      }
      if (!data.count) body.textContent = '暂无已删除内容';
      if (data.diagnostics?.length) {
        const warning = document.createElement('p');
        warning.textContent = '部分项目无法读取，请刷新重试。';
        body.append(warning);
      }
    });
  }

  async function reload() {
    const version = ++request;
    host.setAttribute('aria-busy', 'true');
    try {
      const data = await api('deleted');
      if (version === request) render(data);
    } catch (error) {
      if (version !== request) return;
      caption.textContent = '已删除（加载失败）';
      body.replaceChildren(restoreButton('deleted-retry', '重试', reload));
      flash(`已删除内容加载失败：${error.message}`);
    } finally {
      if (version === request) host.setAttribute('aria-busy', 'false');
    }
  }
  return { host, reload };
}
