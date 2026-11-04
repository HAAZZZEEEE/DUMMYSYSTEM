// 主区右栏预览：文本用 /read 取内容；md 走 marked + DOMPurify，其余高亮代码块。
import { api, mark, target } from './api.js';
import { metadata } from './actions.js';
import { Marked } from './vendor/marked.js';
import createDOMPurify from './vendor/purify.js';
import hljs from './vendor/highlight.js';

// DOMPurify 默认导出在有 DOM 时即为实例，无 DOM（构建/测试）时是工厂。
const DOMPurify = typeof createDOMPurify.sanitize === 'function'
  ? createDOMPurify : createDOMPurify(window);

const MARKDOWN = /\.(md|markdown|mdown)$/i;
const TEXTUAL = /\.(txt|log|rst|csv|tsv|json|jsonc|yaml|yml|toml|ini|cfg|conf|env|xml|lock|js|mjs|cjs|ts|tsx|jsx|css|scss|html|htm|py|pyw|sh|ps1|bat|cmd|c|h|cc|cpp|hpp|rs|go|java|sql|mdx)$/i;
const escapeHtml = (value) => String(value).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const md = new Marked({ gfm: true, breaks: false });
md.use({
  renderer: {
    code(token) {
      const lang = String(token.lang || '').trim().split(/\s+/)[0];
      let body;
      if (lang && hljs.getLanguage(lang)) {
        body = hljs.highlight(token.text, { language: lang, ignoreIllegals: true }).value;
      } else if (!lang) {
        try { body = hljs.highlightAuto(token.text).value; }
        catch { body = escapeHtml(token.text); }
      } else {
        body = escapeHtml(token.text);
      }
      const cls = lang ? ` class="hljs language-${escapeHtml(lang)}"` : ' class="hljs"';
      return `<pre><code${cls}>${body}</code></pre>`;
    },
  },
});

export function isMarkdown(info) {
  return MARKDOWN.test(String(info?.name || info?.relative_path || ''));
}
export function isTextual(info) {
  const name = String(info?.name || info?.relative_path || '');
  return MARKDOWN.test(name) || TEXTUAL.test(name);
}

export function createPreview(nav, session, actions, flash) {
  const pane = document.getElementById('preview-pane');
  const title = document.getElementById('preview-title');
  const body = document.getElementById('preview-body');
  const toggle = document.getElementById('btn-preview-toggle');
  let visible = true;
  let saving = false;
  function applyVisibility(prefs) {
    visible = prefs.preview_visible !== false;
    document.body.classList.toggle('preview-hidden', !visible);
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.title = visible ? '关闭预览栏' : '开启预览栏';
  }
  session.subscribe(prefs => { if (!saving) applyVisibility(prefs); });
  applyVisibility(session.preferences);
  toggle.onclick = async () => {
    const next = !visible;
    saving = true;
    toggle.disabled = true;
    toggle.setAttribute('aria-busy', 'true');
    applyVisibility({ preview_visible: next });
    try { await session.save({ preview_visible: next }); }
    catch (error) { flash(`预览开关未保存：${error.message}`); }
    finally {
      saving = false;
      applyVisibility(session.preferences);
      toggle.disabled = false;
      toggle.setAttribute('aria-busy', 'false');
    }
  };
  let current = null;
  let version = 0;

  function clear() {
    current = null;
    title.textContent = '预览';
    body.replaceChildren();
    pane.dataset.state = 'empty';
    const empty = document.createElement('p');
    empty.className = 'preview-empty';
    empty.textContent = '选择文本文件以在此预览';
    body.append(empty);
  }

  function showNotice(text) {
    const note = document.createElement('p');
    note.className = 'preview-notice';
    note.textContent = text;
    body.prepend(note);
  }

  function renderText(text, info) {
    body.replaceChildren();
    if (isMarkdown(info)) {
      const html = DOMPurify.sanitize(md.parse(text), { USE_PROFILES: { html: true } });
      const article = document.createElement('article');
      article.className = 'markdown-body';
      article.innerHTML = html;
      body.append(article);
    } else {
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.className = 'hljs';
      code.textContent = text;
      try { hljs.highlightElement(code); } catch { /* 未覆盖语言时保留纯文本 */ }
      pre.append(code);
      body.append(pre);
    }
  }

  async function open(value, info = {}) {
    const snapshot = target(value);
    current = snapshot;
    const at = ++version;
    const ctx = nav.context();
    pane.dataset.state = 'loading';
    title.textContent = info.name || snapshot.relative_path || '预览';
    body.replaceChildren();
    const busy = document.createElement('p');
    busy.className = 'preview-empty';
    busy.textContent = '加载中…';
    body.append(busy);
    try {
      const result = await api('read', { body: { target: snapshot }, signal: ctx.signal });
      if (!ctx.valid() || at !== version) return;
      renderText(result.text, { ...metadata(info), ...metadata(result.target), name: info.name });
      if (result.truncated) showNotice('文件过大，仅显示前 2MB。');
      pane.dataset.state = 'ready';
    } catch (error) {
      if (!ctx.valid() || at !== version) return;
      pane.dataset.state = 'error';
      body.replaceChildren();
      const message = document.createElement('p');
      message.className = 'preview-error';
      message.textContent = error.message;
      body.append(message);
      const fallback = document.createElement('button');
      fallback.className = 'btn ghost';
      fallback.textContent = '改用外部应用打开';
      fallback.onclick = () => actions.open(snapshot, null, info);
      body.append(fallback);
    }
  }

  clear();
  return {
    canPreview: (info) => isTextual(info),
    open,
    clear,
    get current() { return current; },
  };
}
