import { wireSettings } from './settings.js';

const DEFAULT_ACCENT = '#0066cc';
const presets = [['蓝色', '#0066cc'], ['紫色', '#7c3aed'], ['绿色', '#15803d'],
  ['橙色', '#c2410c'], ['玫红', '#be185d'], ['青色', '#0e7490']];
const themes = ['system', 'light', 'dark'];
function normalize(value) {
  const color = String(value || '').trim();
  if (/^#[0-9a-f]{6}$/i.test(color)) return color.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(color)) return '#' + [...color.slice(1)].map((part) => part + part).join('').toLowerCase();
  return null;
}
const rgb = (color) => [1, 3, 5].map((index) => parseInt(color.slice(index, index + 2), 16));
const hex = (color) => '#' + color.map((part) => Math.round(part).toString(16).padStart(2, '0')).join('');
const mix = (color, toward, amount) => color.map((part, index) => Math.round(part + (toward[index] - part) * amount));
function luminance(color) {
  return color.map((part) => {
    const value = part / 255;
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}
function contrast(a, b) {
  const first = luminance(a), second = luminance(b);
  return (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
}
// 保留原色预览；界面文字色按实际表面适配，黑白也有可读的选中与焦点。
function palette(raw, dark) {
  const canvas = rgb(dark ? '#1c1c20' : '#ffffff');
  const backgrounds = [canvas, rgb(dark ? '#242429' : '#f5f5f7'), rgb(dark ? '#2b2b32' : '#fafafc')];
  const endpoint = dark ? [255, 255, 255] : [0, 0, 0];
  const original = rgb(raw === DEFAULT_ACCENT && dark ? '#70b7ff' : raw);
  const amount = dark ? .16 : .08;
  let accent = original;
  for (let step = 0; step <= 255; step++) {
    accent = mix(original, endpoint, step / 255);
    if ([...backgrounds, mix(canvas, accent, amount)].every((background) => contrast(accent, background) >= 4.5)) break;
  }
  return {
    '--accent': hex(accent), '--accent-hover': hex(mix(accent, endpoint, .1)),
    '--accent-focus': hex(accent), '--accent-on-dark': hex(accent),
    '--accent-surface': hex(mix(canvas, accent, amount)),
    '--on-primary': contrast(accent, [255, 255, 255]) >= contrast(accent, [0, 0, 0]) ? '#ffffff' : '#000000',
    '--focus-ring': `rgba(${accent.join(',')},${dark ? '.38' : '.25'})`, '--accent-original': raw,
  };
}

export function createTheme(session, flash) {
  const $ = (id) => document.getElementById(id);
  const media = matchMedia('(prefers-color-scheme: dark)');
  const select = $('theme-select'), picker = $('accent-color'), field = $('accent-hex'), status = $('settings-status');
  const nameInput = $('workspace-name-input'), nameLabel = $('workspace-name');
  let theme = 'system', accent = DEFAULT_ACCENT, revision = 0, pending = 0;
  function apply() {
    const actual = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme;
    const root = document.documentElement;
    root.dataset.theme = actual;
    root.dataset.themePreference = theme;
    root.dataset.accentColor = accent;
    for (const [name, value] of Object.entries(palette(accent, actual === 'dark'))) root.style.setProperty(name, value);
    select.value = theme;
    picker.value = accent;
    field.value = accent;
    field.removeAttribute('aria-invalid');
    $('accent-value').textContent = accent.toUpperCase();
    for (const button of $('accent-presets').children) button.setAttribute('aria-pressed', String(button.dataset.color === accent));
  }
  async function save(patch) {
    const current = ++revision;
    pending++;
    status.textContent = '正在保存…';
    status.dataset.state = 'saving';
    try {
      await session.save(patch);
      if (current === revision) { status.textContent = '设置已保存'; status.dataset.state = 'saved'; }
    } catch (error) {
      if (current === revision) {
        status.textContent = `保存失败：${error.message}。`;
        status.dataset.state = 'error';
        flash(status.textContent);
      }
    } finally { pending--; }
  }
  function setAccent(value, persist) {
    const next = normalize(value);
    if (!next) {
      field.setAttribute('aria-invalid', 'true');
      status.textContent = '请输入 #RRGGBB 格式，例如 #0066cc。';
      status.dataset.state = 'error';
      return;
    }
    accent = next;
    apply();
    if (persist) save({ accent_color: accent });
    else { status.textContent = '颜色预览中，选择完成后自动保存'; status.dataset.state = 'preview'; }
  }
  for (const [name, color] of presets) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'accent-preset';
    button.dataset.testid = 'accent-preset'; button.dataset.color = color;
    button.style.setProperty('--swatch', color);
    button.setAttribute('aria-label', `${name} ${color}`); button.title = `${name} ${color}`;
    const dot = document.createElement('span'); dot.className = 'accent-dot'; dot.setAttribute('aria-hidden', 'true');
    button.append(dot, document.createTextNode(name));
    button.onclick = () => setAccent(color, true);
    $('accent-presets').append(button);
  }
  media.addEventListener('change', apply);
  select.addEventListener('change', () => { theme = select.value; apply(); save({ theme }); });
  picker.addEventListener('input', () => setAccent(picker.value, false));
  picker.addEventListener('change', () => setAccent(picker.value, true));
  field.addEventListener('change', () => setAccent(field.value, true));
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); setAccent(field.value, true); }
  });
  $('settings-reset').onclick = () => { theme = 'system'; accent = DEFAULT_ACCENT; apply(); save({ theme, accent_color: accent }); };
  function applyWorkspaceName(prefs) {
    const name = prefs.workspace_name || '';
    nameLabel.textContent = name || '个人工作空间';
    nameLabel.title = nameLabel.textContent;
    if (document.activeElement !== nameInput) nameInput.value = name;
  }
  nameInput.addEventListener('input', () => nameInput.removeAttribute('aria-invalid'));
  nameInput.addEventListener('change', () => {
    const name = nameInput.value.trim();
    if ([...name].length > 40 || /[\u0000-\u001f\u007f]/u.test(name)) {
      nameInput.setAttribute('aria-invalid', 'true');
      status.textContent = '请输入不超过 40 个字符的单行名称。';
      status.dataset.state = 'error';
      return;
    }
    nameInput.value = name;
    void save({ workspace_name: name });
  });
  nameInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      nameInput.blur();
    }
  });
  session.subscribe(applyWorkspaceName);
  wireSettings();
  session.subscribe?.((prefs) => {
    if (pending || $('settings-dialog').open) return;
    theme = themes.includes(prefs.theme) ? prefs.theme : 'system';
    accent = normalize(prefs.accent_color) || DEFAULT_ACCENT;
    apply();
  });
  return { init() {
    applyWorkspaceName(session.preferences);
    theme = themes.includes(session.preferences.theme) ? session.preferences.theme : 'system';
    accent = normalize(session.preferences.accent_color) || DEFAULT_ACCENT;
    apply();
  } };
}
