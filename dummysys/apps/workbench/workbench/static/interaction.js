// 通用键盘边界与列表内滚动；不滚动搜索框外的工作区。
export const isEditing = (element) => !!element?.closest('input,textarea,select,[contenteditable="true"],[role="textbox"]');

// 重建导航子树时，临时缩小的内容高度会令浏览器将 scrollTop 钳制到顶部。
// 同步恢复到原位置；折叠后超出最终范围时由浏览器自然钳制。
export function preserveNavScroll(host, update) {
  const scroller = host.closest('#sidebar-scroll, #project-navigation');
  const top = scroller?.scrollTop;
  const left = scroller?.scrollLeft;
  try { return update(); }
  finally {
    if (scroller) { scroller.scrollTop = top; scroller.scrollLeft = left; }
  }
}

export function revealOption(host, option) {
  if (!option) return;
  const list = host.getBoundingClientRect();
  const row = option.getBoundingClientRect();
  if (row.top < list.top) host.scrollTop -= list.top - row.top;
  else if (row.bottom > list.bottom) host.scrollTop += row.bottom - list.bottom;
}
