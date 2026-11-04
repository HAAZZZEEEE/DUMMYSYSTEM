"""本机命令计数；只保存命令名和聚合结果，不保存调用参数。"""
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import sqlite3

BOUNDS_MS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 90000)


def classify(code, error_code=None):
    if code == 0: return 'success'
    if code == 1: return 'issues_found'
    if error_code == 'RESULT_UNKNOWN': return 'unknown'
    if error_code == 'LOCK_BUSY': return 'contention'
    if error_code and ('CONFLICT' in error_code or error_code == 'INSTALLATION_CHANGED'): return 'conflict'
    if error_code and (error_code.startswith(('INVALID_', 'CONFIG_', 'ACTOR_', 'VERSION_', 'REQUEST_')) or error_code == 'NOT_FOUND'): return 'invalid_input'
    return 'error'


def database(root):
    return Path(root) / 'runtime/state/cli/usage.sqlite3'


def record(root, command, code, *, duration_ms=None, error_code=None, source='cli'):
    """短事务累加，统计不可用时由入口降级，不能影响业务结果。"""
    path = database(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    with closing(sqlite3.connect(path, timeout=0.25)) as connection, connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL, command TEXT NOT NULL,
            calls INTEGER NOT NULL, successes INTEGER NOT NULL,
            failures INTEGER NOT NULL, first_called TEXT NOT NULL,
            last_called TEXT NOT NULL, PRIMARY KEY(day, command))''')
        connection.execute('''INSERT INTO usage VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(day, command) DO UPDATE SET
            calls=calls+1, successes=successes+excluded.successes,
            failures=failures+excluded.failures,
            first_called=MIN(first_called, excluded.first_called),
            last_called=MAX(last_called, excluded.last_called)''',
            (now[:10], command, int(code == 0), int(code != 0), now, now))
        if duration_ms is not None:
            bucket=next((bound for bound in BOUNDS_MS if duration_ms <= bound), -1)
            connection.execute('''CREATE TABLE IF NOT EXISTS metrics (
                day TEXT, command TEXT, outcome TEXT, error_code TEXT, source TEXT,
                bucket INTEGER, calls INTEGER, total_ms REAL,
                PRIMARY KEY(day, command, outcome, error_code, source, bucket))''')
            connection.execute('''INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(day, command, outcome, error_code, source, bucket)
                DO UPDATE SET calls=calls+1, total_ms=total_ms+excluded.total_ms''',
                (now[:10], command, classify(code,error_code), error_code or '', source, bucket, duration_ms))


def summary(root, days=None):
    path = database(root)
    rows = []
    since = None
    started = None
    metrics = []
    if days is not None:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    if path.exists():
        # 查询既不创建数据库，也不修改计数。
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.25)) as connection:
            started = connection.execute('SELECT MIN(first_called) FROM usage').fetchone()[0]
            rows = connection.execute('''SELECT command, SUM(calls), SUM(successes),
                SUM(failures), MAX(last_called) FROM usage
                WHERE (? IS NULL OR day >= ?) GROUP BY command
                ORDER BY SUM(calls) DESC, command''', (since, since)).fetchall()
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metrics'").fetchone():
                metrics=connection.execute('''SELECT command, outcome, error_code, source, bucket, SUM(calls), SUM(total_ms)
                    FROM metrics WHERE (? IS NULL OR day >= ?) GROUP BY command, outcome, error_code, source, bucket''', (since,since)).fetchall()
    commands = [dict(command=r[0], calls=r[1], successes=r[2], failures=r[3], last_called=r[4]) for r in rows]
    for item in commands:
        relevant=[r for r in metrics if r[0] == item['command']]
        measured=sum(r[5] for r in relevant)
        hist={bound:sum(r[5] for r in relevant if r[4] == bound) for bound in (*BOUNDS_MS, -1)}
        def quantile(q):
            count=0
            for bound,n in hist.items():
                count+=n
                if measured and count >= measured*q: return bound if bound >= 0 else None
            return None
        item.update(measured_calls=measured, unknown_calls=item['calls']-measured,
                    outcomes={k:sum(r[5] for r in relevant if r[1]==k) for k in sorted({r[1] for r in relevant})},
                    error_codes={k:sum(r[5] for r in relevant if r[2]==k) for k in sorted({r[2] for r in relevant if r[2]})},
                    sources={k:sum(r[5] for r in relevant if r[3]==k) for k in sorted({r[3] for r in relevant})},
                    latency=dict(mean_ms=sum(r[6] for r in relevant)/measured if measured else None,
                                 p50_upper_ms=quantile(.5), p95_upper_ms=quantile(.95),
                                 buckets=[dict(upper_ms=b if b>=0 else None,calls=n) for b,n in hist.items() if n]))
    return dict(path=str(path), timezone='UTC', days=days, since=since,
                started_at=started, total_calls=sum(r[1] for r in rows),
                successes=sum(r[2] for r in rows), failures=sum(r[3] for r in rows),
                commands=commands)
