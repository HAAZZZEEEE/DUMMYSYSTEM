// p/t/r 治理表单：新建/编辑/交接/结束运行。写操作一律 POST /api/v1/ptr/*，
// 后端转 dmy 子进程；本模块不碰记录文件。
// request_id 在弹窗生命周期内固定，重试复用同一个 id → dmy Operation 幂等去重。
import { api, mark } from './api.js';

const LIST_HINT = '每行一条';
const DEFAULT_ARCHIVE_REASON = '用户手动归档';
const CLOSED_TASK = new Set(['completed', 'cancelled']);
const TASK_STATUS = { active: '进行中', blocked: '阻塞', awaiting_acceptance: '待验收', completed: '已完成', cancelled: '已取消' };

function field(spec) {
  const row = document.createElement('div');
  row.className = `form-row${spec.advanced ? ' form-advanced' : ''}`;
  const label = document.createElement('label');
  label.className = 'form-label';
  label.textContent = spec.label;
  row.append(label);
  if (spec.type === 'readonly') {
    const value = document.createElement('div');
    value.className = 'form-readonly';
    value.textContent = spec.value || '—';
    value.title = spec.value || '';
    row.append(label, value);
    if (spec.hint) row.append(hint(spec.hint));
    return row;
  }
  let input;
  if (spec.type === 'textarea' || spec.type === 'lines') {
    input = document.createElement('textarea');
    input.rows = spec.rows || 3;
    input.value = spec.type === 'lines' ? (spec.value || []).join('\n') : (spec.value || '');
  } else if (spec.type === 'select') {
    input = document.createElement('select');
    for (const option of spec.options) {
      const element = document.createElement('option');
      element.value = option.value;
      element.textContent = option.label;
      input.append(element);
    }
    input.value = spec.value ?? spec.options[0]?.value ?? '';
  } else if (spec.type === 'checkbox') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!spec.value;
  } else {
    input = document.createElement('input');
    input.type = 'text';
    input.value = spec.value || '';
  }
  input.name = spec.name;
  input.id = `ptr-field-${spec.name}`;
  label.htmlFor = input.id;
  input.dataset.ptrField = spec.name;
  input.dataset.ptrKind = spec.type || 'text';
  if (spec.placeholder) input.placeholder = spec.placeholder;
  if (spec.required) input.required = true;
  if (spec.readonly) input.disabled = true;
  row.append(input);
  if (spec.hint) row.append(hint(spec.hint));
  return row;
}

function hint(text) {
  const element = document.createElement('p');
  element.className = 'form-hint';
  element.textContent = text;
  return element;
}

export function createPtrForms({ nav, session, flash, reloadNav, taskList = () => [] }) {
  const dialog = document.getElementById('ptr-dialog');
  const form = document.getElementById('ptr-form');
  const titleEl = document.getElementById('ptr-title');
  const descriptionEl = document.getElementById('ptr-description');
  const statusEl = document.getElementById('ptr-status');
  const cancelBtn = document.getElementById('ptr-cancel');
  const submitBtn = document.getElementById('ptr-submit');
  let surface = null;
  let active = null;
  let armed = false;
  let armTimer = 0;
  let projectMenu = null;
  let projectMenuAnchor = null;
  const missing = (entity, op) => {
    const entry = surface?.[entity]?.[op];
    if (!entry || entry.status === 'missing') return entry?.reason || 'dmy 未提供该命令';
    return '';
  };

  cancelBtn.onclick = () => dialog.close();
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); dialog.close(); });
  dialog.addEventListener('close', disarm);

  function disarm() {
    resetConfirmation();
    active = null;
  }

  function resetConfirmation() {
    armed = false;
    clearTimeout(armTimer);
    submitBtn.classList.remove('danger');
    if (active) submitBtn.textContent = active.submitLabel;
  }

  async function loadSurface() {
    if (!surface) surface = await api('ptr/surface');
    return surface;
  }

  function actor() {
    return (session.preferences?.actor || '').trim();
  }

  function requireActor() {
    const value = actor();
    if (!value) { flash('请先在设置里填写当前负责人'); return null; }
    return value;
  }

  function collect() {
    const values = {};
    for (const element of form.querySelectorAll('[data-ptr-field]')) {
      const name = element.dataset.ptrField;
      const kind = element.dataset.ptrKind;
      if (element.disabled && kind === 'text' && element.readOnly) continue;
      if (kind === 'checkbox') values[name] = element.checked;
      else if (kind === 'lines') {
        values[name] = element.value.split('\n').map((line) => line.trim()).filter(Boolean);
      } else if (!element.disabled) values[name] = element.value.trim();
    }
    return values;
  }

  // spec: {title, description, fields, submitLabel, armLabel?, armWhen?(values)}
  // onSubmit(values, {requestId}) → Promise；成功后本模块负责重载导航。
  function open(spec) {
    if (document.querySelector('dialog[open]')) return;
    const requestId = crypto.randomUUID();
    titleEl.textContent = spec.title;
    descriptionEl.textContent = spec.description || '';
    descriptionEl.hidden = !spec.description;
    statusEl.textContent = '';
    statusEl.dataset.state = '';
    submitBtn.textContent = spec.submitLabel;
    submitBtn.classList.remove('danger');
    form.replaceChildren(...spec.fields.map(field));
    armed = false;
    clearTimeout(armTimer);
    active = {
      requestId,
      armWhen: spec.armWhen,
      armLabel: spec.armLabel || `确认${spec.submitLabel}`,
      submitLabel: spec.submitLabel,
      onSubmit: spec.onSubmit,
    };
    submitBtn.onclick = () => void submit();
    dialog.showModal();
    form.querySelector('input,select,textarea')?.focus();
  }

  async function submit() {
    if (!active) return;
    const values = collect();
    if (form.querySelector(':invalid')) {
      statusEl.textContent = '请补全必填项';
      statusEl.dataset.state = 'error';
      return;
    }
    // 两步计划确认：onSubmit 返回 {needsPlan:true, plan, planToken} 后等待再次提交。
    if (active._planToken) {
      // 已经拿到 plan_token，直接带 token 提交
      const requestId = active.requestId;
      const onSubmit = active.onSubmit;
      const planToken = active._planToken;
      active._planToken = null;
      submitBtn.disabled = true;
      statusEl.textContent = '提交中…';
      statusEl.dataset.state = 'saving';
      try {
        await onSubmit(values, { requestId, ifPlan: planToken });
        statusEl.textContent = '已保存';
        statusEl.dataset.state = 'saved';
        flash('已保存', 'success');
        dialog.close();
        reloadNav();
      } catch (error) {
        submitBtn.disabled = false;
        submitBtn.textContent = active?.submitLabel || submitBtn.textContent;
        submitBtn.classList.remove('danger');
        statusEl.textContent = error.message;
        statusEl.dataset.state = 'error';
        flash(error.message);
        if (error.code === 'VERSION_CONFLICT') {
          statusEl.textContent = `${error.message}；请重新打开编辑`;
          reloadNav();
        }
      }
      return;
    }
    // 难撤销动作两步确认，沿用重启按钮的模式，不用原生 confirm。
    if (active.armWhen?.(values)) {
      if (!armed) {
        armed = true;
        submitBtn.textContent = active.armLabel;
        submitBtn.classList.add('danger');
        armTimer = setTimeout(resetConfirmation, 4000);
        return;
      }
      clearTimeout(armTimer);
      armed = false;
    }
    const requestId = active.requestId;
    const onSubmit = active.onSubmit;
    submitBtn.disabled = true;
    statusEl.textContent = '提交中…';
    statusEl.dataset.state = 'saving';
    try {
      const result = await onSubmit(values, { requestId });
      // 两步计划：onSubmit 返回 {needsPlan, plan, planToken}
      if (result && result.needsPlan) {
        active._planToken = result.planToken;
        submitBtn.disabled = false;
        submitBtn.textContent = '确认执行';
        submitBtn.classList.add('danger');
        const detail = result.plan || {};
        const lines = Object.entries(detail)
          .filter(([, v]) => typeof v === 'string' && v)
          .map(([k, v]) => `${k}: ${v}`);
        statusEl.textContent = `计划就绪：${lines.join('；') || '确认执行？'}`;
        statusEl.dataset.state = 'plan';
        return;
      }
      statusEl.textContent = '已保存';
      statusEl.dataset.state = 'saved';
      flash('已保存', 'success');
      dialog.close();
      reloadNav();
    } catch (error) {
      submitBtn.disabled = false;
      submitBtn.textContent = active?.submitLabel || submitBtn.textContent;
      submitBtn.classList.remove('danger');
      if (error.code === 'RESULT_UNKNOWN') {
        statusEl.textContent = '结果确认中：超时，操作可能已生效';
        statusEl.dataset.state = 'warning';
        flash('超时：结果确认中', 'warning');
        // 提供确认按钮
        submitBtn.textContent = '确认结果';
        submitBtn.onclick = () => void checkOperation(requestId);
        return;
      }
      statusEl.textContent = error.message;
      statusEl.dataset.state = 'error';
      flash(error.message);
      if (error.code === 'VERSION_CONFLICT') {
        statusEl.textContent = `${error.message}；请重新打开编辑`;
        reloadNav();
      }
    }
  }

  // ---- 各表单 ----
  async function createTask() {
    if (!requireActor()) return;
    const project = nav.state.target?.project_id;
    if (!project) { flash('请先选择一个项目'); return; }
    const info = await loadSurface().catch(() => null);
    const origins = info?.origins || ['user', 'agent'];
    open({
      title: '新建任务',
      description: '标题会成为目录名的一部分，创建后不可改。',
      submitLabel: '创建任务',
      fields: [
        { name: 'title', label: '标题', type: 'text', required: true, hint: '单层目录名，不含 : / \\ 等字符' },
        { name: 'origin', label: '来源', type: 'select', options: origins.map((value) => ({ value, label: value === 'user' ? '用户发起' : 'Agent 生成' })) },
        { name: 'goal', label: '目标与完成条件', type: 'textarea', required: true, rows: 4 },
        { name: 'owner', label: '负责人', type: 'text', value: actor(), hint: '留空则记为当前负责人' },
        { name: 'requires_acceptance', label: '需要验收', type: 'checkbox', advanced: true },
        { name: 'read_paths', label: '只读路径', type: 'lines', advanced: true, hint: `${LIST_HINT}；绝对路径` },
        { name: 'write_paths', label: '可写路径', type: 'lines', advanced: true, hint: `${LIST_HINT}；绝对路径` },
      ],
      onSubmit: (values, { requestId }) => api('ptr/task/create', {
        body: { project, request_id: requestId, ...values },
      }),
    });
  }

  async function editTask(task) {
    if (!requireActor()) return;
    let current;
    try {
      current = await api(`ptr/task?task=${encodeURIComponent(task.task_id)}`);
    } catch (error) { flash(`读取任务失败：${error.message}`); return; }
    const scope = current.binding?.scope || {};
    const owner = current.owner || '';
    const editable = owner === actor();
    const info = await loadSurface().catch(() => null);
    open({
      title: `编辑任务：${current.title || task.title}`,
      description: editable ? '标题与来源创建后不可改。' : `仅当前负责者可维护（${owner || '未指定'}）`,
      submitLabel: '保存',
      fields: [
        { name: 'title', label: '标题', type: 'readonly', value: current.title || task.title },
        { name: 'status', label: '状态', type: 'select', value: current.status || 'active', readonly: !editable,
          options: (info?.task_statuses || ['active', 'blocked', 'awaiting_acceptance', 'completed', 'cancelled']).map((value) => ({ value, label: value })) },
        { name: 'owner', label: '负责人', type: 'text', value: owner, readonly: !editable, hint: '改负责人请用「交接」' },
        { name: 'note', label: '变更说明', type: 'textarea', required: true, rows: 3, hint: '状态变化须记录原因与结果' },
        { name: 'accepted', label: '标记为已验收', type: 'checkbox', readonly: !editable, advanced: true },
        { name: 'read_paths', label: '只读路径', type: 'lines', value: scope.read_paths || [], readonly: !editable, advanced: true, hint: `${LIST_HINT}；留空则不改` },
        { name: 'write_paths', label: '可写路径', type: 'lines', value: scope.write_paths || [], readonly: !editable, advanced: true, hint: `${LIST_HINT}；留空则不改` },
        { name: 'remote_resources', label: '远端资源', type: 'lines', value: scope.remote_resources || [], readonly: !editable, advanced: true, hint: `${LIST_HINT}；勿包含凭据` },
        { name: 'clear_read_paths', label: '清空只读路径', type: 'checkbox', readonly: !editable, advanced: true },
        { name: 'clear_write_paths', label: '清空可写路径', type: 'checkbox', readonly: !editable, advanced: true },
      ],
      onSubmit: (values, { requestId }) => {
        const body = { task: task.task_id, request_id: requestId, if_version: current.version, note: values.note };
        if (values.status) body.status = values.status;
        if (values.owner && values.owner !== owner) body.owner = values.owner;
        if (values.accepted) body.accepted = true;
        if (values.read_paths.length) body.read_paths = values.read_paths;
        if (values.write_paths.length) body.write_paths = values.write_paths;
        if (values.remote_resources.length) body.remote_resources = values.remote_resources;
        if (values.clear_read_paths) body.clear_read_paths = true;
        if (values.clear_write_paths) body.clear_write_paths = true;
        return api('ptr/task/update', { body });
      },
    });
  }

  async function handoffTask(task) {
    if (!requireActor()) return;
    let current;
    try {
      current = await api(`ptr/task?task=${encodeURIComponent(task.task_id)}`);
    } catch (error) { flash(`读取任务失败：${error.message}`); return; }
    const owner = current.owner || '';
    const needsAuthorization = owner !== actor();
    open({
      title: `交接任务：${current.title || task.title}`,
      description: needsAuthorization
        ? `当前负责者是 ${owner || '未指定'}，接手须记录用户授权来源。`
        : '你是当前负责者，交接须记录原因。',
      submitLabel: '交接',
      armLabel: '确认交接',
      armWhen: () => true,
      fields: [
        { name: 'owner', label: '新负责人', type: 'text', required: true, value: '' },
        { name: 'note', label: '交接说明', type: 'textarea', required: true, rows: 3 },
        ...(needsAuthorization
          ? [{ name: 'authorization', label: '用户授权来源', type: 'text', required: true, hint: '例如：会议记录、消息确认' }]
          : []),
      ],
      onSubmit: (values, { requestId }) => api('ptr/task/handoff', {
        body: {
          task: task.task_id, request_id: requestId, if_version: current.version,
          owner: values.owner, note: values.note, authorization: values.authorization || '',
        },
      }),
    });
  }

  // task 为空时从 tasks 里选一个（导航组头的「新建运行」入口）。
  async function createRun(task, tasks = []) {
    if (!requireActor()) return;
    const pool = task ? [task] : tasks;
    if (!pool.length) { flash('当前项目暂无任务，请先新建任务'); return; }
    const pick = !task && pool.length > 1;
    const info = await loadSurface().catch(() => null);
    open({
      title: task ? `新建运行：${task.title || task.name}` : '新建运行',
      description: '标题会成为运行目录名的一部分，创建后不可改。',
      submitLabel: '创建运行',
      fields: [
        ...(pick ? [{
          name: 'task_id', label: '所属任务', type: 'select', required: true,
          options: pool.map((item) => ({ value: item.task_id, label: item.title || item.name })),
        }] : []),
        { name: 'title', label: '标题', type: 'text', required: true },
        { name: 'command', label: '执行命令', type: 'textarea', required: true, rows: 3 },
        { name: 'host', label: '主机', type: 'text', value: info?.hostname || '', advanced: true, required: true },
        { name: 'source', label: '来源', type: 'text', value: 'unknown', advanced: true, required: true, hint: '无则填 unknown' },
        { name: 'inputs', label: '输入', type: 'text', value: 'unknown', advanced: true, required: true, hint: '无则填 unknown' },
        { name: 'retry_of', label: '重试自', type: 'text', advanced: true, hint: '被重试运行的 run_id，可留空' },
      ],
      onSubmit: (values, { requestId }) => api('ptr/run/create', {
        body: {
          task: values.task_id || task.task_id, request_id: requestId,
          title: values.title, command: values.command, host: values.host,
          source: values.source, inputs: values.inputs, retry_of: values.retry_of || '',
        },
      }),
    });
  }

  async function startRun(task, run) {
    if (!requireActor()) return;
    let current;
    try {
      current = await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`);
    } catch (error) { flash(`读取运行失败：${error.message}`); return; }
    try {
      await api('ptr/run/start', {
        body: { task: task.task_id, run: run.run_id, request_id: crypto.randomUUID(), if_version: current.version },
      });
      flash('已开始运行', 'success');
      reloadNav();
    } catch (error) { flash(error.message); }
  }

  async function finishRun(task, run) {
    if (!requireActor()) return;
    let current;
    try {
      current = await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`);
    } catch (error) { flash(`读取运行失败：${error.message}`); return; }
    const info = await loadSurface().catch(() => null);
    open({
      title: `结束运行：${current.title || run.title}`,
      description: '已结束的运行不可重开；重试请新建运行并填「重试自」。',
      submitLabel: '结束运行',
      armLabel: '确认结束',
      armWhen: (values) => values.status !== 'completed',
      fields: [
        { name: 'status', label: '结束状态', type: 'select',
          options: (info?.run_finish_statuses || ['completed', 'failed', 'cancelled']).map((value) => ({ value, label: value })),
          value: 'completed' },
        { name: 'result', label: '结果', type: 'textarea', required: true, rows: 3 },
        { name: 'exit_code', label: '退出码', type: 'text', value: '0', hint: '标记 completed 时必须为 0' },
        { name: 'evidence', label: '证据', type: 'lines', rows: 3, hint: `${LIST_HINT}；标记 completed 时至少一条` },
      ],
      onSubmit: (values, { requestId }) => {
        const body = {
          task: task.task_id, run: run.run_id, request_id: requestId,
          if_version: current.version, status: values.status, result: values.result,
        };
        if (values.exit_code !== '') body.exit_code = Number.parseInt(values.exit_code, 10);
        if (values.evidence.length) body.evidence = values.evidence;
        return api('ptr/run/finish', { body });
      },
    });
  }

  // 设置弹窗里的「当前负责人」：dmy --actor 的来源。
  function wireActor() {
    const input = document.getElementById('actor-input');
    if (!input) return;
    input.value = session.preferences?.actor || '';
    session.subscribe?.((prefs) => {
      if (document.activeElement !== input && input.value !== (prefs.actor || '')) {
        input.value = prefs.actor || '';
      }
    });
    input.onchange = () => {
      session.save({ actor: input.value.trim() })
        .catch((error) => flash(`负责人保存失败：${error.message}`));
    };
  }
  wireActor();

  // ---- 项目工具栏（上下文工具栏）：主操作 + 项目级缺口溢出菜单 ----
  function closeProjectMenu(focus = false) {
    projectMenu?.remove();
    projectMenu = null;
    projectMenuAnchor?.setAttribute('aria-expanded', 'false');
    if (focus && projectMenuAnchor?.isConnected) projectMenuAnchor.focus();
    projectMenuAnchor = null;
  }

  function openProjectMenu(anchor) {
    if (projectMenuAnchor === anchor) { closeProjectMenu(true); return; }
    closeProjectMenu();
    projectMenuAnchor = anchor;
    const menu = document.createElement('div');
    menu.className = 'menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', '项目操作');
    // 项目级操作：不可用项置灰并写明原因。
    const entries = [
      ['新建项目', 'create', () => void createProject()],
      ['改名项目…', 'rename', () => void renameProject()],
      ['暂停项目…', 'pause', () => void pauseProject()],
      ['恢复项目…', 'resume', () => void resumeProject()],
      ['归档项目…', 'archive', () => void archiveProject()],
      ['取消归档…', 'unarchive', () => void unarchiveProject()],
      ['删除项目…', 'delete', () => void deleteProject()],
      ['取消删除…', 'undelete', () => void undeleteProject()],
    ];
    for (const [label, op, fn] of entries) {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'menu-item';
      item.textContent = label;
      const missingReason = missing('project', op);
      item.disabled = !!missingReason;
      item.title = missingReason || '';
      item.setAttribute('role', 'menuitem');
      item.onclick = (event) => { event.stopPropagation(); closeProjectMenu(true); fn(); };
      menu.append(item);
    }
    const box = anchor.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(box.right - 230, innerWidth - 246))}px`;
    menu.style.top = `${Math.max(8, Math.min(box.bottom + 4, innerHeight - 160))}px`;
    document.body.append(menu);
    anchor.setAttribute('aria-expanded', 'true');
    projectMenu = menu;
  }

  document.addEventListener('click', (event) => {
    if (projectMenu && !projectMenu.contains(event.target) && !projectMenuAnchor?.contains(event.target)) {
      closeProjectMenu();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && projectMenu) { event.preventDefault(); closeProjectMenu(true); }
  });

  function mountToolbar() {
    const bar = document.getElementById('project-toolbar');
    if (!bar) return;
    bar.replaceChildren();
    const primary = document.createElement('button');
    primary.type = 'button';
    primary.className = 'btn primary';
    primary.dataset.testid = 'project-new-task';
    primary.textContent = '＋ 新建任务';
    primary.title = '在当前项目下新建任务';
    primary.onclick = () => void createTask();
    const secondary = document.createElement('button');
    secondary.type = 'button';
    secondary.className = 'btn ghost';
    secondary.dataset.testid = 'project-new-run';
    secondary.textContent = '＋ 新建运行';
    secondary.title = '在当前项目的任务下新建运行';
    secondary.onclick = () => void createRun(null, taskList());
    const overflow = document.createElement('button');
    overflow.type = 'button';
    overflow.className = 'more-btn';
    overflow.dataset.testid = 'project-menu';
    overflow.textContent = '⋯';
    overflow.title = '项目操作';
    overflow.setAttribute('aria-label', '项目操作');
    overflow.setAttribute('aria-haspopup', 'menu');
    overflow.setAttribute('aria-expanded', 'false');
    overflow.addEventListener('keydown', (event) => event.stopPropagation());
    overflow.onclick = (event) => { event.stopPropagation(); openProjectMenu(overflow); };
    bar.append(primary, secondary, overflow);
  }

  // ---- 两步计划：dry-run → 确认 → 提交 ----
  async function planAndSubmit(action, values, { requestId, ifVersion, buildArgs }) {
    // 第一步：dry-run 拿 plan_token
    const planBody = { action, ...buildArgs(values) };
    const planResult = await api('ptr/plan', { body: planBody });
    const planToken = planResult.plan_token;
    const planDetail = planResult.plan || {};
    // 展示计划摘要并请求确认
    const lines = Object.entries(planDetail)
      .filter(([, v]) => typeof v === 'string' && v)
      .map(([k, v]) => `${k}: ${v}`);
    statusEl.textContent = `计划：${lines.join('；') || '确认执行？'}`;
    statusEl.dataset.state = 'plan';
    submitBtn.textContent = '确认执行';
    submitBtn.classList.add('danger');
    return new Promise((resolve) => {
      submitBtn.onclick = () => {
        const body = { ...buildArgs(values), request_id: requestId, if_plan: planToken };
        if (ifVersion) body.if_version = ifVersion;
        api(action.replace('.', '/').replace('ptr/', 'ptr/'), { body })
          .then(resolve)
          .catch(resolve);
      };
    });
  }

  // ---- P/T/R 简单表单 ----
  async function renameTask(task) {
    if (!requireActor()) return;
    let current;
    try { current = await api(`ptr/task?task=${encodeURIComponent(task.task_id)}`); }
    catch (error) { flash(`读取任务失败：${error.message}`); return; }
    open({
      title: `改名任务：${current.title || task.title}`,
      description: '目录名会改变，旧路径映射自动登记。',
      submitLabel: '改名',
      armLabel: '确认改名',
      armWhen: () => true,
      fields: [
        { name: 'title', label: '新标题', type: 'text', required: true, value: current.title || task.title },
        { name: 'reason', label: '改名原因', type: 'textarea', required: true, rows: 2 },
      ],
      onSubmit: async (values, { requestId, ifPlan }) => {
        const body = { task: task.task_id, title: values.title, reason: values.reason,
                       request_id: requestId, if_version: current.version };
        if (ifPlan) {
          body.if_plan = ifPlan;
          return api('ptr/task/rename', { body });
        }
        const planResult = await api('ptr/plan', { body: { action: 'task.rename', ...body } });
        return { needsPlan: true, plan: planResult.plan, planToken: planResult.plan_token };
      },
    });
  }

  async function moveTask(task) {
    if (!requireActor()) return;
    let current;
    try { current = await api(`ptr/task?task=${encodeURIComponent(task.task_id)}`); }
    catch (error) { flash(`读取任务失败：${error.message}`); return; }
    const info = await loadSurface().catch(() => null);
    const projects = info?.projects || [];
    open({
      title: `移动任务：${current.title || task.title}`,
      description: '移动到另一个项目，旧路径映射自动登记。',
      submitLabel: '移动',
      armLabel: '确认移动',
      armWhen: () => true,
      fields: [
        { name: 'to_project', label: '目标项目', type: 'select', required: true,
          options: projects.map((p) => ({ value: p.project_id || p.name, label: p.title || p.name })) },
        { name: 'reason', label: '移动原因', type: 'textarea', required: true, rows: 2 },
        { name: 'authorization', label: '用户授权来源', type: 'text', hint: '跨项目移动须记录授权' },
      ],
      onSubmit: async (values, { requestId, ifPlan }) => {
        const body = { task: task.task_id, to_project: values.to_project,
                       reason: values.reason, authorization: values.authorization || '',
                       request_id: requestId, if_version: current.version };
        if (ifPlan) {
          body.if_plan = ifPlan;
          return api('ptr/task/move', { body });
        }
        const planResult = await api('ptr/plan', { body: { action: 'task.move', ...body } });
        return { needsPlan: true, plan: planResult.plan, planToken: planResult.plan_token };
      },
    });
  }

  function lifecycleDialog(entity, task, run, action, label, armLabel) {
    // 通用归档/取消归档/删除/取消删除表单
    const isRun = !!run;
    const id = isRun ? run.run_id : task.task_id;
    const show = async () => {
      if (!requireActor()) return;
      let current;
      try {
        current = isRun
          ? await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`)
          : await api(`ptr/task?task=${encodeURIComponent(task.task_id)}`);
      } catch (error) { flash(`读取失败：${error.message}`); return; }
      const title = current.management?.display_title || current.title || (isRun ? run.title : task.title);
      const needsPlan = ['archive', 'unarchive'].includes(action) && !isRun;
      const unfinished = needsPlan && action === 'archive' && !CLOSED_TASK.has(current.status);
      open({
        title: `${label}：${title}`,
        description: unfinished
          ? `任务尚未完成，当前状态为${TASK_STATUS[current.status] || current.status || '未知'}。归档后状态保持不变，是否确实归档？`
          : needsPlan ? '归档或取消归档保留任务原状态，请确认执行计划。' : '此操作需要记录原因。',
        submitLabel: label,
        armLabel: unfinished ? '仍然归档（保留原状态）' : armLabel || `确认${label}`,
        armWhen: () => needsPlan ? unfinished : true,
        fields: [
          { name: 'reason', label: action === 'archive' ? '归档说明（可选）' : '原因', type: 'textarea', required: action !== 'archive', rows: 2,
            hint: action === 'archive' ? `留空记录为“${DEFAULT_ARCHIVE_REASON}”` : '' },
        ],
        onSubmit: async (values, { requestId, ifPlan }) => {
          const reason = values.reason || (action === 'archive' ? DEFAULT_ARCHIVE_REASON : '');
          const base = isRun
            ? { task: task.task_id, run: run.run_id, reason }
            : { task: task.task_id, reason };
          const body = { ...base, request_id: requestId, if_version: current.version };
          if (unfinished) body.allow_unfinished = true;
          const route = `ptr/${entity}/${action}`;
          if (needsPlan && !ifPlan) {
            const planResult = await api('ptr/plan', { body: { action: `${entity}.${action}`, ...body } });
            return { needsPlan: true, plan: planResult.plan, planToken: planResult.plan_token };
          }
          if (ifPlan) body.if_plan = ifPlan;
          return api(route, { body });
        },
      });
    };
    return show;
  }

  async function deleteTask(task) { return lifecycleDialog('task', task, null, 'delete', '删除任务')(); }
  async function undeleteTask(task) { return lifecycleDialog('task', task, null, 'undelete', '取消删除')(); }
  async function archiveTask(task) { return lifecycleDialog('task', task, null, 'archive', '归档任务')(); }
  async function unarchiveTask(task) { return lifecycleDialog('task', task, null, 'unarchive', '取消归档')(); }
  async function archiveRun(task, run) { return lifecycleDialog('run', task, run, 'archive', '归档运行')(); }
  async function unarchiveRun(task, run) { return lifecycleDialog('run', task, run, 'unarchive', '取消归档')(); }
  async function deleteRun(task, run) { return lifecycleDialog('run', task, run, 'delete', '删除运行')(); }
  async function undeleteRun(task, run) { return lifecycleDialog('run', task, run, 'undelete', '取消删除')(); }

  async function renameRun(task, run) {
    if (!requireActor()) return;
    let current;
    try { current = await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`); }
    catch (error) { flash(`读取运行失败：${error.message}`); return; }
    open({
      title: `改名运行：${current.title || run.title}`,
      description: '运行标题可改，目录名不变。',
      submitLabel: '改名',
      fields: [
        { name: 'title', label: '新标题', type: 'text', required: true, value: current.management?.display_title || current.title || run.title },
      ],
      onSubmit: (values, { requestId }) => api('ptr/run/rename', {
        body: { task: task.task_id, run: run.run_id, title: values.title,
                request_id: requestId, if_version: current.version },
      }),
    });
  }

  async function updateRun(task, run) {
    if (!requireActor()) return;
    let current;
    try { current = await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`); }
    catch (error) { flash(`读取运行失败：${error.message}`); return; }
    const info = await loadSurface().catch(() => null);
    const planned = current.status === 'planned';
    const terminal = ['completed', 'failed', 'cancelled'].includes(current.status);
    open({
      title: `补写运行：${current.title || run.title}`,
      description: '补写遗漏的字段；已结束的运行只允许补写证据。',
      submitLabel: '保存',
      fields: [
        { name: 'status', label: '状态', type: 'select', value: current.status || 'planned', readonly: terminal,
          options: (info?.run_statuses || ['planned', 'running', 'completed', 'failed', 'cancelled']).map((v) => ({ value: v, label: v })) },
        { name: 'host', label: '主机', type: 'text', value: current.host || '', advanced: true, readonly: !planned },
        { name: 'source', label: '来源', type: 'text', value: current.source || '', advanced: true, readonly: !planned },
        { name: 'inputs', label: '输入', type: 'text', value: current.inputs || '', advanced: true, readonly: !planned },
        { name: 'command', label: '命令', type: 'textarea', value: current.command || '', rows: 2, advanced: true, readonly: !planned },
        { name: 'result', label: '结果', type: 'textarea', value: current.result || '', rows: 2, readonly: terminal },
        { name: 'exit_code', label: '退出码', type: 'text', value: current.exit_code != null ? String(current.exit_code) : '', advanced: true, readonly: terminal },
        { name: 'add_evidence', label: '补写证据', type: 'lines', rows: 2, hint: '每行一条；绝对路径' },
      ],
      onSubmit: (values, { requestId }) => {
        const body = { task: task.task_id, run: run.run_id,
                       request_id: requestId, if_version: current.version };
        if (values.status) body.status = values.status;
        if (values.host) body.host = values.host;
        if (values.source) body.source = values.source;
        if (values.inputs) body.inputs = values.inputs;
        if (values.command) body.command = values.command;
        if (values.result) body.result = values.result;
        if (values.exit_code !== undefined && values.exit_code !== '') body.exit_code = Number.parseInt(values.exit_code, 10);
        if (values.add_evidence.length) body.add_evidence = values.add_evidence;
        return api('ptr/run/update', { body });
      },
    });
  }

  // ---- 项目级表单 ----
  async function createProject() {
    if (!requireActor()) return;
    open({
      title: '新建项目',
      description: '标题会成为目录名的一部分，创建后不可改。',
      submitLabel: '创建项目',
      fields: [
        { name: 'title', label: '标题', type: 'text', required: true },
        { name: 'created', label: '创建日期', type: 'text', placeholder: 'YYYY-MM-DD', hint: '留空则今天' },
      ],
      onSubmit: (values, { requestId }) => api('ptr/project/create', {
        body: { title: values.title, created: values.created || '', request_id: requestId },
      }),
    });
  }

  async function renameProject() {
    if (!requireActor()) return;
    const projectId = nav.state.target?.project_id;
    if (!projectId) { flash('请先选择一个项目'); return; }
    let current;
    try { current = await api(`ptr/project?project=${encodeURIComponent(projectId)}`); }
    catch (error) { flash(`读取项目失败：${error.message}`); return; }
    open({
      title: `改名项目：${current.title || projectId}`,
      description: '目录名会改变，旧路径映射自动登记。',
      submitLabel: '改名',
      armLabel: '确认改名',
      armWhen: () => true,
      fields: [
        { name: 'title', label: '新标题', type: 'text', required: true, value: current.title || '' },
        { name: 'reason', label: '改名原因', type: 'textarea', required: true, rows: 2 },
      ],
      onSubmit: async (values, { requestId, ifPlan }) => {
        const body = { project: projectId, title: values.title, reason: values.reason,
                       request_id: requestId, if_version: current.version };
        if (ifPlan) {
          body.if_plan = ifPlan;
          return api('ptr/project/rename', { body });
        }
        const planResult = await api('ptr/plan', { body: { action: 'project.rename', ...body } });
        return { needsPlan: true, plan: planResult.plan, planToken: planResult.plan_token };
      },
    });
  }

  async function projectLifecycle(action, label, explicitProject = null) {
    if (!requireActor()) return;
    const projectId = explicitProject || nav.state.target?.project_id;
    if (!projectId) { flash('请先选择一个项目'); return; }
    let current;
    try { current = await api(`ptr/project?project=${encodeURIComponent(projectId)}`); }
    catch (error) { flash(`读取项目失败：${error.message}`); return; }
    const needsPlan = ['archive', 'unarchive'].includes(action);
    let unfinished = [];
    if (action === 'archive') {
      try {
        const data = await api(`nav?project_id=${encodeURIComponent(projectId)}`);
        unfinished = [...(data.tasks || []), ...(data.deleted_tasks || [])].filter((task) => !CLOSED_TASK.has(task.status));
      } catch (error) { flash(`读取任务状态失败：${error.message}`); return; }
    }
    open({
      title: `${label}：${current.title || projectId}`,
      description: unfinished.length
        ? `还有 ${unfinished.length} 个未完成 Task：${unfinished.map((task) => `${task.title}（${TASK_STATUS[task.status] || task.status || '未知'}）`).join('、')}。归档后这些 Task 的状态保持不变，是否确实归档？`
        : needsPlan ? '请确认归档计划，Task 状态保持不变。' : '此操作需要记录原因。',
      submitLabel: label,
      armLabel: unfinished.length ? '仍然归档（保留Task状态）' : `确认${label}`,
      armWhen: () => needsPlan ? unfinished.length > 0 : true,
      fields: [
        { name: 'reason', label: action === 'archive' ? '归档说明（可选）' : '原因', type: 'textarea', required: action !== 'archive', rows: 2,
          hint: action === 'archive' ? `留空记录为“${DEFAULT_ARCHIVE_REASON}”` : '' },
      ],
      onSubmit: async (values, { requestId, ifPlan }) => {
        const body = { project: projectId, reason: values.reason || (action === 'archive' ? DEFAULT_ARCHIVE_REASON : ''),
                       request_id: requestId, if_version: current.version };
        if (unfinished.length) body.allow_unfinished = true;
        if (needsPlan && !ifPlan) {
          const planResult = await api('ptr/plan', { body: { action: `project.${action}`, ...body } });
          return { needsPlan: true, plan: planResult.plan, planToken: planResult.plan_token };
        }
        if (ifPlan) body.if_plan = ifPlan;
        return api(`ptr/project/${action}`, { body });
      },
    });
  }

  async function archiveProject() { return projectLifecycle('archive', '归档项目'); }
  async function unarchiveProject() { return projectLifecycle('unarchive', '取消归档'); }
  async function deleteProject() { return projectLifecycle('delete', '删除项目'); }
  async function undeleteProject(projectId = null) { return projectLifecycle('undelete', '取消删除', projectId); }
  async function pauseProject() { return projectLifecycle('pause', '暂停项目'); }
  async function resumeProject() { return projectLifecycle('resume', '恢复项目'); }

  // 状态快捷切换：图标按钮 / 下拉触发，直接调 run.update。
  async function quickStatus(task, run, toStatus) {
    if (!requireActor()) return;
    let current;
    try { current = await api(`ptr/run?task=${encodeURIComponent(task.task_id)}&run=${encodeURIComponent(run.run_id)}`); }
    catch (error) { flash(`读取运行失败：${error.message}`); return; }
    try {
      await api('ptr/run/update', {
        body: { task: task.task_id, run: run.run_id,
                request_id: crypto.randomUUID(), if_version: current.version,
                status: toStatus },
      });
      flash(`状态已切换为 ${toStatus}`, 'success');
      reloadNav();
    } catch (error) { flash(error.message); }
  }

  // 超时后确认 Operation 结果。
  async function checkOperation(requestId) {
    try {
      const result = await api(`ptr/operation?request_id=${encodeURIComponent(requestId)}`);
      if (result.found === false) {
        statusEl.textContent = result.note || '尚未产生回执';
        statusEl.dataset.state = 'warning';
      } else {
        statusEl.textContent = `结果：${result.status || '已完成'}`;
        statusEl.dataset.state = result.status === 'completed' ? 'saved' : 'warning';
        flash(`操作状态：${result.status || '已完成'}`, result.status === 'completed' ? 'success' : 'warning');
        if (result.status === 'completed') { dialog.close(); reloadNav(); }
      }
    } catch (error) {
      statusEl.textContent = `确认失败：${error.message}`;
      statusEl.dataset.state = 'error';
    }
  }

  return {
    // task
    createTask, editTask, handoffTask, renameTask, moveTask,
    archiveTask, unarchiveTask, deleteTask, undeleteTask,
    // run
    createRun, startRun, finishRun, updateRun, renameRun,
    archiveRun, unarchiveRun, deleteRun, undeleteRun,
    // project
    createProject, renameProject,
    archiveProject, unarchiveProject, deleteProject, undeleteProject,
    pauseProject, resumeProject,
    quickStatus, checkOperation,
    mountToolbar,
    missing,
    surface: () => surface,
    loadSurface,
  };
}
