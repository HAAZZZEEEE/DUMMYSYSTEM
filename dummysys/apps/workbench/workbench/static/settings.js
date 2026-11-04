// 设置入口、服务重启与原生 dialog 焦点管理；不改变导航或其他对话框业务。
import { api } from './api.js';

export function wireSettings() {
  const button = document.getElementById('btn-settings');
  const dialog = document.getElementById('settings-dialog');
  document.addEventListener('beforetoggle', (event) => {
    if (event.target.tagName !== 'DIALOG' || event.newState !== 'open') return;
    if ([...document.querySelectorAll('dialog[open]')].some((item) => item !== event.target)) event.preventDefault();
  }, true);
  button.onclick = () => {
    if (document.querySelector('dialog[open]')) return;
    dialog.showModal();
    wireMeta();
    button.setAttribute('aria-expanded', 'true');
    document.getElementById('theme-select').focus();
  };
  document.getElementById('settings-close').onclick = () => dialog.close();
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dialog.close(); }
  });
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); dialog.close(); });
  dialog.addEventListener('close', () => {
    button.setAttribute('aria-expanded', 'false');
    if (!document.querySelector('dialog[open]')) button.focus();
    disarm();
  });
  const disarm = wireRestart();
}

// 源码提交与位置只读展示；缺字段显示破折号，不影响其他设置。
async function wireMeta() {
  const rows = {
    version: document.querySelector('[data-testid="meta-version"]'),
    sha: document.querySelector('[data-testid="meta-sha"]'),
    source: document.querySelector('[data-testid="meta-source"]'),
  };
  function fill(meta) {
    rows.version.textContent = meta.version || '—';
    rows.sha.textContent = meta.short_sha || '—';
    rows.source.textContent = meta.install_source || '—';
    rows.source.title = meta.source_path || '';
  }
  try {
    fill(await api('meta'));
  } catch {
    fill({});
  }
}

// 重启是破坏性动作：两步确认，避免原生 confirm 与整体设计冲突。
function wireRestart() {
  const restart = document.getElementById('btn-restart-service');
  const status = document.getElementById('settings-status');
  let armed = false, timer = 0, running = false;
  function disarm() {
    armed = false;
    clearTimeout(timer);
    restart.classList.remove('danger');
    if (!running) { restart.disabled = false; restart.textContent = '重启'; }
  }
  restart.onclick = async () => {
    if (running) return;
    if (!armed) {
      armed = true;
      restart.textContent = '确认重启';
      restart.classList.add('danger');
      timer = setTimeout(disarm, 4000);
      return;
    }
    clearTimeout(timer);
    armed = false;
    running = true;
    restart.disabled = true;
    restart.textContent = '重启中…';
    status.textContent = '正在请求重启…';
    status.dataset.state = 'saving';
    try {
      await api('restart', { body: {} });
      restart.textContent = '已请求';
      status.textContent = '服务重启中，新窗口即将打开，本窗口可关闭。';
      status.dataset.state = 'saved';
    } catch (error) {
      running = false;
      restart.textContent = '重启';
      restart.classList.remove('danger');
      restart.disabled = false;
      status.textContent = `重启失败：${error.message}`;
      status.dataset.state = 'error';
    }
  };
  return disarm;
}
