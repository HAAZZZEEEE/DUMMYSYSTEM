// 首页只负责隔离页面承载；内容与内部导航由项目页面自己组织。
import { api } from './api.js';

export function createHomepage(nav, session, flash) {
  const host = document.getElementById('project-homepage');
  let active;
  // 仅当前首页可请求 Explorer 动作；项目身份来自上下文，不接受页面自报。
  window.addEventListener('message', async event => {
    const current = active;
    const request = event.data;
    if (!current || !current.ctx.valid() || event.source !== current.frame.contentWindow
        || !current.frame.isConnected || request?.type !== 'dmy:homepage-explorer'
        || typeof request.requestId !== 'string' || !request.requestId.length || request.requestId.length > 64) return;
    const { ctx, frame, projectId } = current;
    const valid = () => active === current && ctx.valid() && frame.isConnected;
    const reply = result => {
      if (valid()) frame.contentWindow.postMessage({type:'dmy:homepage-explorer-result', requestId:request.requestId, ...result}, '*');
    };
    try {
      const value = request.target;
      if (!value || Object.keys(value).some(key => !['root_id', 'relative_path'].includes(key))
          || typeof value.root_id !== 'string' || !value.root_id || value.root_id.length > 4096
          || typeof value.relative_path !== 'string' || value.relative_path.length > 4096)
        throw new Error('请提供登记根 root_id 和相对路径 relative_path。');
      const target = { project_id: projectId, root_id:value.root_id, relative_path:value.relative_path };
      const fingerprint = JSON.stringify(target);
      const previous = current.opens.get(request.requestId);
      if (previous) {
        if (previous.fingerprint !== fingerprint) throw new Error('同一请求标识不能用于不同路径。');
        reply(await previous.promise);
        return;
      }
      if (current.opening) throw new Error('正在处理上一次打开请求，请稍后重试。');
      // 请求缓存有界且不淘汰已处理ID，防止同一标识重复派发。
      if (current.opens.size >= 128) throw new Error('打开请求次数已达本页上限，请刷新首页。');
      current.opening = true;
      const promise = (async () => {
        try {
          const info = await api('actions', { body:{target}, signal:ctx.signal });
          if (!valid()) return {};
          const action = info.target?.kind === 'dir' ? 'explorer_open' : 'explorer_reveal';
          if (!info.target?.available || info.target.navigation_only
              || !(info.available_actions || []).some(item => (typeof item === 'string' ? item : item.action || item.id) === action))
            throw new Error(info.target?.reason || '该路径不存在或不能在资源管理器打开。');
          if (!valid()) return {};
          await api('open', { body:{target, action, request_id:crypto.randomUUID()}, signal:ctx.signal });
          return {status:'dispatched', action};
        } catch (error) { return {error:error.message}; }
        finally { current.opening = false; }
      })();
      current.opens.set(request.requestId, {fingerprint, promise});
      reply(await promise);
    } catch (error) { reply({error:error.message}); }
  });
  // 隔离页只可读写自身项目的收藏键，不能取得会话或其他偏好。
  window.addEventListener('message', async event => {
    const current = active;
    const request = event.data;
    if (!current || !current.ctx.valid() || event.source !== current.frame.contentWindow
        || !current.frame.isConnected || !request || request.type !== 'dmy:homepage-pins'
        || typeof request.requestId !== 'string' || request.requestId.length > 64
        || !['read', 'set', 'edit'].includes(request.action)) return;
    const { frame, ctx, projectId } = current;
    const reply = result => {
      if (active === current && ctx.valid() && frame.isConnected)
        frame.contentWindow.postMessage({type:'dmy:homepage-pins-result', requestId:request.requestId, ...result}, '*');
    };
    try {
      if (request.action === 'set') {
        const key = request.key;
        const pinned = request.pinned;
        if (typeof key !== 'string' || !key.length || key.length > 512
            || /[\x00-\x1f]/.test(key) || typeof pinned !== 'boolean') return;
        await session.save(prefs => {
          const all = prefs.homepage_pins || {};
          const keys = new Set(all[projectId] || []);
          if (typeof request.legacyKey === 'string' && request.legacyKey !== key) keys.delete(request.legacyKey);
          if (pinned) keys.add(key); else keys.delete(key);
          return {homepage_pins:{...all, [projectId]:[...keys]}};
        }, () => active === current && ctx.valid() && frame.isConnected);
      }
      if (request.action === 'edit') {
        const {key, fields} = request;
        if (typeof key !== 'string' || !key.length || key.length > 512 || /[\x00-\x1f]/.test(key)
            || (fields !== null && (typeof fields !== 'object' || Array.isArray(fields)
            || Object.keys(fields).some(k=>!['name','description'].includes(k))
            || Object.entries(fields).some(([k,v])=>typeof v!=='string' || v.length>(k==='name'?120:2000))))) return;
        await session.save(prefs => {
          const all = prefs.homepage_overrides || {};
          const entries = {...(all[projectId] || {})};
          if (fields === null) delete entries[key]; else entries[key] = fields;
          return {homepage_overrides:{...all, [projectId]:entries}};
        }, () => active === current && ctx.valid() && frame.isConnected);
      }
      reply({pins:session.preferences.homepage_pins?.[projectId] || [],
             overrides:session.preferences.homepage_overrides?.[projectId] || {}});
    } catch (error) {
      reply({error:request.action==='edit'?'显示内容保存失败，请重试。':'收藏保存失败，请重试。'});
    }
  });
  nav.subscribe(state => {
    const selected = state.target?.root_id === 'homepage';
    host.classList.toggle('hidden', !selected);
    if (!selected || state.loading || state.error) { active = undefined; host.replaceChildren(); }
  });
  async function load(ctx) {
    const data = await api(`homepage?project_id=${encodeURIComponent(ctx.target.project_id)}`, { signal: ctx.signal });
    if (!ctx.valid()) return;
    const frame = document.createElement('iframe');
    frame.title = '项目首页';
    frame.dataset.testid = 'homepage-frame';
    frame.setAttribute('sandbox', 'allow-scripts');
    frame.referrerPolicy = 'no-referrer';
    frame.src = data.url;
    frame.onerror = () => {
      if (!ctx.valid()) return;
      nav.state.error = new Error('项目首页加载失败，请刷新重试。');
      nav.emit();
    };
    nav.state.loading = false;
    nav.emit();
    host.replaceChildren(frame);
    active = {frame, ctx, projectId:ctx.target.project_id, opens:new Map(), opening:false};
    session.save({ last_location: ctx.target }, ctx.valid).catch(error => {
      if (ctx.valid()) flash(`位置保存失败：${error.message}`);
    });
  }
  return { load };
}
