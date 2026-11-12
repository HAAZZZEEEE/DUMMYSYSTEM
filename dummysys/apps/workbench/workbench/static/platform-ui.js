// UI conventions only; all operating-system actions are selected by Python adapters.
export const isMac = /Mac/i.test(navigator.platform);
export const primaryKey = isMac ? '⌘' : 'Ctrl';
export const fileManager = isMac ? 'Finder' : '资源管理器';
export const commandPressed = event => isMac ? event.metaKey : event.ctrlKey;
const button = document.getElementById('btn-open-explorer');
if (button) {
  button.textContent = fileManager;
  button.title = button.ariaLabel = `在 ${fileManager} 中打开当前目录`;
}
for (const element of document.querySelectorAll('[data-primary-key]')) element.textContent = primaryKey;
const quick = document.getElementById('btn-quick-switch');
if (quick) quick.title = `快速跳转 (${primaryKey}+K)`;
