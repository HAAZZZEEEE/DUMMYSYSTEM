import { api } from './api.js';

function element(tag, className, text) {
  const el = document.createElement(tag); el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function capacity(bytes) {
  const unit = bytes >= 1024 ** 3 ? 3 : bytes >= 1024 ** 2 ? 2 : bytes >= 1024 ? 1 : 0;
  return `${(bytes / 1024 ** unit).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} ${['B', 'KiB', 'MiB', 'GiB'][unit]}`;
}

export function createStorage(nav) {
  let data, controller, timer, generation = 0, pending = false, message = '';
  function render() {
    const host = document.getElementById('overview-storage');
    if (!host || nav.state.target) return;
    host.replaceChildren();
    const header = element('header', 'ov-panel-heading');
    const title = element('div', '');
    title.append(element('span', 'ov-kicker', '存储空间'), element('h2', '', 'DUMMYSYS 总占用'));
    const refresh = element('button', 'btn ghost', pending ? '正在采集…' : '刷新容量');
    refresh.type = 'button'; refresh.disabled = pending; refresh.onclick = start;
    header.append(title, refresh); host.append(header);
    const ranking = data?.ranking;
    const total = ranking?.workspace_bytes;
    if (Number.isFinite(total)) {
      const summary = element('div', 'ov-storage-summary');
      summary.append(element('strong', '', capacity(total)));
      host.append(summary);
    } else host.append(element('p', 'ov-empty', pending ? '正在统计 DUMMYSYS 空间…' : '暂无空间数据。'));
    const layout = element('div', 'ov-storage-layout');
    const projects = element('section', 'ov-storage-projects');
    projects.setAttribute('aria-label', '项目空间 TOP 5');
    const subheading = element('div', 'ov-storage-summary');
    subheading.append(element('h3', '', '项目空间 TOP 5'),
      element('span', 'ov-muted', data?.projects_refreshing ? '正在更新…' : '资源目录'));
    projects.append(subheading);
    if (ranking?.top?.length) {
      const top = [...ranking.top].sort((a, b) => b.bytes - a.bytes);
      const list = element('ol', 'ov-storage-ranking');
      for (const [index, item] of top.entries()) {
        const row = element('li', '');
        row.style.setProperty('--segment-color', `var(--storage-${index + 1})`);
        const line = element('div', 'ov-storage-rank-line');
        const button = element('button', '', item.title);
        button.type = 'button'; button.title = item.title;
        button.onclick = () => nav.go({ project_id: item.project_id, root_id: 'resources', relative_path: '' });
        line.append(button, element('span', '', `${capacity(item.bytes)}${item.partial ? '（部分）' : ''}`));
        const bar = element('div', 'ov-storage-bar');
        const share = total > 0 ? Math.min(100, Math.max(0, item.bytes / total * 100)) : 0;
        bar.title = `占 DUMMYSYS 总量 ${share.toFixed(1)}%`;
        const fill = element('span', ''); fill.style.width = `${share}%`; bar.append(fill);
        row.append(line, bar); list.append(row);
      }
      projects.append(list);
      const slices = top.map((item, index) => ({ title: item.title, bytes: item.bytes, color: `var(--storage-${index + 1})` }));
      const otherProjects = Math.max(0, (ranking.projects_bytes || 0) - top.reduce((sum, item) => sum + item.bytes, 0));
      const shared = Math.max(0, (total || 0) - (ranking.projects_bytes || 0));
      if (otherProjects) slices.push({ title: '其他项目', bytes: otherProjects, color: 'var(--storage-6)' });
      if (shared) slices.push({ title: '公共资源', bytes: shared, color: 'var(--storage-7)' });
      if (total > 0) {
        const figure = element('figure', 'ov-storage-distribution');
        figure.append(element('figcaption', '', '空间分布'));
        const pie = element('div', 'ov-storage-pie');
        pie.setAttribute('role', 'img');
        pie.setAttribute('aria-label', slices.map(item => `${item.title} ${(item.bytes / total * 100).toFixed(1)}%`).join('，'));
        let offset = 0;
        const stops = slices.map(item => {
          const start = offset; offset += item.bytes / total * 100;
          return `${item.color} ${start}% ${offset}%`;
        });
        pie.style.background = `conic-gradient(${stops.join(',')})`;
        figure.append(pie);
        const legend = element('ul', 'ov-storage-legend');
        for (const item of slices) {
          const row = element('li', '');
          row.style.setProperty('--segment-color', item.color);
          row.append(element('i', ''), element('span', '', item.title), element('strong', '', `${(item.bytes / total * 100).toFixed(1)}%`));
          legend.append(row);
        }
        figure.append(legend); layout.append(projects, figure);
      } else layout.append(projects);
    } else {
      projects.append(element('p', 'ov-empty', data?.projects_refreshing ? '正在统计项目空间…' : '暂无项目统计。'));
      layout.append(projects);
    }
    host.append(layout);
    if (ranking) host.append(element('p', 'ov-footnote',
      `${ranking.project_count} 个项目（含归档） · ${new Date(ranking.updated_at).toLocaleString('zh-CN')}${ranking.incomplete ? ' · 部分目录无法读取，统计不完整' : ''}`));
    if (data?.projects_error) host.append(element('p', 'ov-footnote', data.projects_error));
    const statusText = message || data?.error;
    if (statusText) {
      const status = element('p', 'ov-footnote', statusText);
      status.setAttribute('role', 'status'); host.append(status);
    }
  }
  function stop() {
    generation++; controller?.abort(); clearTimeout(timer); pending = false;
  }
  async function start() {
    stop();
    if (nav.state.target || document.hidden) return;
    const current = generation, ctx = nav.context();
    controller = new AbortController();
    const signal = controller.signal;
    const valid = () => current === generation && ctx.valid() && !nav.state.target && !document.hidden;
    pending = true; message = ''; render();
    try {
      const cached = await api('storage', { signal });
      if (!valid()) return;
      data = cached;
      render(); // 先呈现缓存，再请求后台采集。
      const refreshed = await api('storage/refresh', { method: 'POST', signal });
      if (!valid()) return;
      data = refreshed;
      const started = performance.now();
      async function poll() {
        if (!valid()) return;
        render();
        if (!data.refreshing && !data.projects_refreshing) { pending = false; render(); return; }
        if (performance.now() - started >= 15000 && !data.projects_refreshing) {
          pending = false; message = '采集仍在后台进行，可稍后刷新查看。'; render(); return;
        }
        timer = setTimeout(async () => {
          try {
            const result = await api('storage', { signal });
            if (!valid()) return;
            data = result; void poll();
          } catch (error) { failed(error); }
        }, Math.min(5000, 250 + (performance.now() - started) / 2));
      }
      void poll();
    } catch (error) { failed(error); }
    function failed(error) {
      if (!valid() || error.name === 'AbortError') return;
      pending = false; message = `容量更新失败：${error.message}`; render();
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop(); else if (!nav.state.target) void start();
  });
  return { render, start, stop };
}
