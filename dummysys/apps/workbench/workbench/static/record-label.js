// Only format the display label. Callers keep the original name and target.
const TASK_DIRECTORY = /^\[task ([1-9]\d*)\]\[(\d{8})\](.+)$/u;
const RUN_DIRECTORY = /^\[(\d{8})-(\d{6})\](.+)$/u;

export function recordDate(value) {
  const match = /^(\d{4})(-?)(\d{2})\2(\d{2})$/u.exec(value || '');
  if (!match) return '';
  const date = `${match[1]}-${match[3]}-${match[4]}`;
  const parsed = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(date) ? date : '';
}

export function recordDirectoryLabel(name) {
  const task = TASK_DIRECTORY.exec(name);
  if (task && task[0] === name) {
    const date = recordDate(task[2]), title = task[3].trim();
    if (date && title) return { title, taskNumber: task[1], metadata: `任务 #${task[1]} · ${date}` };
  }
  const run = RUN_DIRECTORY.exec(name);
  if (run && run[0] === name) {
    const date = recordDate(run[1]), title = run[3].trim();
    const [hours, minutes, seconds] = run[2].match(/../g);
    if (date && title && Number(hours) < 24 && Number(minutes) < 60 && Number(seconds) < 60) {
      return { title, metadata: `${date} · ${hours}:${minutes}` };
    }
  }
  return null;
}

export function recordTime(value, name) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/u.exec(value || '');
  return match ? `${match[1]} · ${match[2]}` : recordDirectoryLabel(name)?.metadata || '';
}
