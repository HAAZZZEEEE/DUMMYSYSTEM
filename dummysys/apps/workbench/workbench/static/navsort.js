// 同层级导航排序；不改变分组、目标身份与手动默认顺序。
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });
export const NAV_SORTS = [['default', '默认顺序'], ['name', '名称升序'], ['name_desc', '名称降序'],
  ['newest', '时间新到旧'], ['oldest', '时间旧到新']];

export function sortNav(items, mode = 'default') {
  const result = [...items];
  if (mode === 'default') return result;
  const name = (item) => item.title || item.name || item.label || '';
  const time = (item) => {
    let value = String(item.created_at || item.created || item.date || item.modified_at || '');
    if (/^\d{8}$/.test(value)) value = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
    return Date.parse(value) || 0;
  };
  return result.sort((a, b) => {
    if (mode === 'name' || mode === 'name_desc') return collator.compare(name(a), name(b)) * (mode === 'name_desc' ? -1 : 1);
    const x = time(a), y = time(b);
    if (!x || !y) return x === y ? collator.compare(name(a), name(b)) : x ? -1 : 1;
    const direction = mode === 'newest' ? -1 : 1;
    // Task 只有日期精度；同日按稳定编号排序，避免标题改变创建先后顺序。
    const numberDelta = Number.isInteger(a.task_number) && a.task_number > 0 &&
      Number.isInteger(b.task_number) && b.task_number > 0 ? a.task_number - b.task_number : 0;
    return (x - y) * direction || numberDelta * direction || collator.compare(name(a), name(b));
  });
}

export function mountNavSort(session, flash) {
  const row = document.createElement('div');
  row.className = 'sidebar-controls';
  const label = document.createElement('label');
  label.textContent = '排序';
  label.className = 'sr-only';
  label.htmlFor = 'nav-sort';
  const select = document.createElement('select');
  select.id = 'nav-sort';
  select.dataset.testid = 'nav-sort';
  select.className = 'btn ghost';
  select.setAttribute('aria-label', '导航树排序');
  select.title = '同层级排序；项目/任务/运行按创建时间，路径按修改时间';
  for (const [value, text] of NAV_SORTS) {
    const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
  }
  row.append(label, select);
  document.querySelector('.sidebar-header').append(row);
  session.subscribe((prefs) => { select.value = prefs.nav_sort || 'default'; });
  select.onchange = () => session.save({ nav_sort: select.value }).catch((error) => flash(`导航排序保存失败：${error.message}`));
}
