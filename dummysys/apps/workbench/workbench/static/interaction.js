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

export function mountScrollEndFades() {
  for (const scroller of document.querySelectorAll('[data-scroll-end-fade]')) {
    function update() {
      const remaining = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop;
      scroller.classList.toggle('scroll-end-overflow', scroller.clientHeight > 0 && remaining > 1);
    }
    const resize = new ResizeObserver(() => {
      scroller.style.setProperty('--scroll-gutter-inline', `${scroller.offsetWidth - scroller.clientWidth}px`);
      scroller.style.setProperty('--scroll-gutter-block', `${scroller.offsetHeight - scroller.clientHeight}px`);
      update();
    });
    function observeContent() {
      // Navigation and preview may replace their content without resizing the scroll viewport.
      resize.disconnect();
      resize.observe(scroller, { box: 'border-box' });
      for (const child of scroller.children) resize.observe(child, { box: 'border-box' });
      update();
    }
    observeContent();
    new MutationObserver(observeContent).observe(scroller, { childList: true });
    scroller.addEventListener('scroll', update, { passive: true });
  }
}
