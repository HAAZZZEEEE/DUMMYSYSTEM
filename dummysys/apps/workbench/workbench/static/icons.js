// 离线 SVG 图标；只根据显示名称选择表现，不参与目标解析或动作路由。
const ns = 'http://www.w3.org/2000/svg';
const shapes = {
  folder: ['M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z', 'M3 9h18'],
  document: ['M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z', 'M14 3v6h6', 'M8 13h8M8 17h5'],
  code: ['M8 7 3 12l5 5M16 7l5 5-5 5M14 4l-4 16'],
  config: ['M5 5h14M5 12h14M5 19h14', 'M9 3v4M15 10v4M10 17v4'],
  image: ['M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z', 'm3 17 6-6 4 4 3-3 5 5', 'M16 7h.01'],
  table: ['M4 3h16v18H4Z', 'M4 9h16M4 15h16M10 9v12'],
  archive: ['M4 3h16v18H4Z', 'M10 3h4v3h-4v3h4v3h-4v3h4v3h-4'],
  video: ['M3 5h18v14H3Z', 'm10 9 5 3-5 3Z'],
  audio: ['M9 18V5l11-2v13', 'M3 18a3 3 0 1 0 6 0 3 3 0 1 0-6 0M14 16a3 3 0 1 0 6 0 3 3 0 1 0-6 0'],
  slide: ['M3 4h18v13H3Z', 'M12 17v4M8 21h8M7 8h10M7 12h6'],
  file: ['M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z', 'M14 3v6h6'],
  chevron: ['m9 5 7 7-7 7'],
  chevronsDown: ['m6 5 6 6 6-6', 'm6 12 6 6 6-6'],
  expandAll: ['M8 3h13v13', 'M3 8h13v13H3Z', 'M6 14.5h7M9.5 11v7'],
  collapseAll: ['M8 3h13v13', 'M3 8h13v13H3Z', 'M6 14.5h7'],
  pin: ['M9 3h6l-1 5 3 3v2H7v-2l3-3-1-5Z', 'M12 13v8'],
  play: ['M8 5v14l11-7Z'],
  check: ['m5 13 4 4L19 7'],
  xmark: ['M6 6l12 12M18 6 6 18'],
  ban: ['M4 12a8 8 0 1 0 8-8', 'M4 4l16 16'],
};
export function fileType(entry) {
  if (entry.kind === 'dir') return 'folder';
  const name = String(entry.name || '').toLowerCase();
  const ext = name.includes('.') ? name.split('.').at(-1) : '';
  if (['md', 'markdown', 'txt', 'rst', 'pdf', 'doc', 'docx'].includes(ext)) return 'document';
  if (['py', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'html', 'css', 'scss', 'c', 'cc', 'cpp', 'h', 'hpp', 'rs', 'go', 'java', 'sh', 'ps1', 'bat', 'cmd'].includes(ext)) return 'code';
  if (['json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env', 'xml', 'lock'].includes(ext) || name.startsWith('.git')) return 'config';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'tif', 'tiff', 'ico'].includes(ext)) return 'image';
  if (['csv', 'tsv', 'xls', 'xlsx', 'parquet', 'db', 'sqlite'].includes(ext)) return 'table';
  if (['zip', '7z', 'tar', 'gz', 'bz2', 'xz', 'rar', 'whl'].includes(ext)) return 'archive';
  if (['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) return 'video';
  if (['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a'].includes(ext)) return 'audio';
  if (['ppt', 'pptx', 'odp'].includes(ext)) return 'slide';
  return 'file';
}
export function icon(name, filled = false) {
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '20');
  svg.setAttribute('height', '20');
  svg.setAttribute('fill', name === 'pin' && filled ? 'currentColor' : 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.55');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', `type-icon type-icon-${name}`);
  for (const [index, shape] of (shapes[name] || shapes.file).entries()) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', shape);
    if (name === 'pin' && index === 1) path.setAttribute('fill', 'none');
    svg.append(path);
  }
  return svg;
}
export const fileIcon = (entry) => icon(fileType(entry));
