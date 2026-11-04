"""工作区总览：复用导航记录，只聚合，不产生另一份状态。"""
from collections import Counter
from datetime import datetime, timezone

from .catalog import CatalogError
from .dmy import DmyError


def _time(value):
    if not value:
        return 0
    try:
        text = str(value)
        date = (datetime.strptime(text, '%Y%m%d-%H%M%S') if len(text) == 15
                else datetime.fromisoformat(text.replace('Z', '+00:00')))
        return date.replace(tzinfo=timezone.utc).timestamp() if date.tzinfo is None else date.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0


def build_overview(catalog, read_stats):
    listing = catalog.list_projects()
    projects, recent, attention = [], [], []
    diagnostics = list(listing.get('diagnostics', []))
    totals = Counter(projects=0, tasks=0, completed=0, open_tasks=0, running=0, runs=0)
    for project in listing['projects']:
        try:
            nav = catalog.list_project_nav(project['project_id'])
        except (CatalogError, OSError, ValueError) as error:
            diagnostics.append(dict(project=project['title'], message=str(error)))
            projects.append(dict(project_id=project['project_id'], title=project['title'],
                                 status=project['status'], unavailable=True))
            continue
        tasks = nav['tasks']
        runs = [run for task in tasks for run in task.get('runs', [])] + nav['orphan_runs']
        counts = Counter(tasks=len(tasks), runs=len(runs))
        for task in tasks:
            status = task.get('status')
            counts['completed'] += status == 'completed'
            counts['open_tasks'] += not task.get('archived') and status not in ('completed', 'cancelled')
            if not task.get('archived') and status in ('blocked', 'awaiting_acceptance'):
                attention.append(dict(title=task['title'], status=status, target=task['target'],
                                      project_title=project['title'], number=task['task_number']))
        for run in runs:
            status = run.get('execution_status') or run.get('status') or 'unknown'
            counts['running'] += status == 'running'
            recent.append(dict(title=run['title'], status=status, created_at=run.get('created_at'),
                               target=run['target'], project_title=project['title']))
        for key, value in counts.items():
            totals[key] += value
        projects.append(dict(project_id=project['project_id'], title=project['title'],
                             status=project['status'], counts=dict(counts),
                             task_states=dict(Counter(t.get('status') or 'unknown' for t in tasks)),
                             run_states=[r.get('execution_status') or r.get('status') or 'unknown'
                                         for r in sorted(runs, key=lambda r: _time(r.get('created_at')), reverse=True)[:16]]))
    totals['projects'] = len(projects)
    recent.sort(key=lambda r: _time(r['created_at']), reverse=True)
    projects.sort(key=lambda p: (-p.get('counts', {}).get('running', 0),
                                 -p.get('counts', {}).get('open_tasks', 0), p['title']))
    try:
        stats = read_stats()
        usage = dict(available=True, total_calls=stats['total_calls'], started_at=stats.get('started_at'),
                     top=stats.get('commands', [])[:5])
    except (DmyError, ValueError, KeyError, TypeError, OSError, RuntimeError):
        usage = dict(available=False, message='命令统计暂不可用，请检查 CLI 是否支持 stats。')
    return dict(updated_at=datetime.now(timezone.utc).isoformat(), totals=dict(totals),
                projects=projects, recent_runs=recent[:8], attention=attention[:8],
                attention_total=len(attention), usage=usage, diagnostics=diagnostics)
