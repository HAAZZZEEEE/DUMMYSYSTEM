// 当前页面内的有界计时样本；不保存正文、查询参数或持久化用户数据。
const samples = [];
export function record(phase, operation, elapsed, status, diagnosticId) {
  samples.push({ phase, operation: operation.split(/[?#]/, 1)[0],
    elapsedMs: elapsed, status, diagnosticId });
  if (samples.length > 100) samples.shift();
}
export function snapshot() { return samples.map((sample) => ({ ...sample })); }
export function measure(operation, render) {
  const start = performance.now();
  try { return render(); }
  finally { record('render', operation, performance.now() - start); }
}
