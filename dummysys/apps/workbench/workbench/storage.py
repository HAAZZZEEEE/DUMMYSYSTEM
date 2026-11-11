"""卷容量与项目大小后台统计，各自缓存和请求去重。"""
from __future__ import annotations

from dummysys_core import locations as loc
from .file_io import write_json

import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class StorageMonitor:
    MIN_INTERVAL = 30.0
    PROJECT_INTERVAL = 600.0

    def __init__(self, workspace: Path, *, probe=None, clock=time.monotonic, projects=None):
        self.workspace = Path(workspace)
        self.path = loc.runtime(self.workspace) / 'state/workbench/storage.json'
        self._probe = probe or shutil.disk_usage
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._last_attempt = None
        self._sample = None
        self._error = None
        self._projects = projects
        self._ranking = None
        self._projects_running = False
        self._projects_attempt = None
        self._projects_error = None
        try:
            cached = json.loads(self.path.read_text(encoding='utf-8'))
            sample = cached['sample']
            if (cached.get('schema_version') == 1 and cached.get('workspace') == str(self.workspace)
                    and isinstance(sample['updated_at'], str)
                    and all(type(sample[k]) is int and sample[k] >= 0 for k in ('total', 'used', 'free'))
                    and sample['total'] > 0 and sample['used'] + sample['free'] == sample['total']):
                self._sample = sample
                ranking = cached.get('ranking')
                if (cached.get('scan_version') == 4 and cached.get('locations') == loc.load(self.workspace).as_dict()
                        and isinstance(ranking, dict) and isinstance(ranking.get('top'), list)
                        and isinstance(ranking.get('updated_at'), str)):
                    self._ranking = ranking
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def snapshot(self, refresh=False):
        with self._lock:
            if refresh and not self._running and (self._last_attempt is None
                    or self._clock() - self._last_attempt >= self.MIN_INTERVAL):
                self._running = True
                self._last_attempt = self._clock()
                threading.Thread(target=self._collect, daemon=True, name='storage-capacity').start()
            if refresh and self._projects and not self._projects_running and self._projects_due():
                self._projects_running = True
                self._projects_attempt = self._clock()
                threading.Thread(target=self._collect_projects, daemon=True, name='storage-projects').start()
            return {'sample': dict(self._sample) if self._sample else None,
                    'refreshing': self._running, 'error': self._error,
                    'ranking': self._ranking, 'projects_refreshing': self._projects_running,
                    'projects_error': self._projects_error,
                    'minimum_interval_seconds': self.MIN_INTERVAL}

    def _projects_due(self):
        if self._projects_attempt is not None:
            return self._clock() - self._projects_attempt >= self.PROJECT_INTERVAL
        try:
            updated = datetime.fromisoformat(self._ranking['updated_at'])
            age = (datetime.now(timezone.utc) - updated).total_seconds()
            return age < 0 or age >= self.PROJECT_INTERVAL
        except (KeyError, TypeError, ValueError):
            return True

    def _save_locked(self):
        write_json(self.path, {'schema_version': 1, 'workspace': str(self.workspace),
                              'sample': self._sample, 'ranking': self._ranking,
                              'scan_version': 4, 'locations': loc.load(self.workspace).as_dict()})

    def _collect_projects(self):
        try:
            rows = []
            assignments = {}
            listing = self._projects()
            incomplete = bool(listing.get('diagnostics'))
            locations = loc.load(self.workspace)
            bases = [self.workspace.resolve(), locations.vault, locations.runtime]
            scan_roots = [base for base in bases if not any(base != other and base.is_relative_to(other) for other in bases)]
            for project in listing['projects']:
                root = Path(project['resource_root'])
                if not any(root.resolve().is_relative_to(base) for base in scan_roots):
                    incomplete = True
                    continue
                row = {'project_id': project['project_id'], 'title': project['title'],
                       'bytes': 0, 'files': 0, 'partial': not root.is_dir()}
                rows.append(row)
                assignments[os.path.normcase(str(self._native_path(root)))] = row
            total = files = skipped = 0
            for base in scan_roots:
                size, count, errors = self._directory_size(base, assignments)
                total += size
                files += count
                skipped += errors
            incomplete = incomplete or bool(skipped) or any(row['partial'] for row in rows)
            rows.sort(key=lambda row: (-row['bytes'], row['title']))
            ranking = {'top': rows[:5], 'project_count': len(rows), 'incomplete': incomplete,
                       'workspace_bytes': total, 'workspace_files': files,
                       'projects_bytes': sum(row['bytes'] for row in rows),
                       'updated_at': datetime.now(timezone.utc).isoformat()}
            with self._lock:
                self._ranking = ranking
                self._projects_error = None
                try:
                    self._save_locked()
                except OSError:
                    self._projects_error = '排行已更新，但缓存保存失败。'
        except Exception:
            with self._lock:
                self._projects_error = '项目统计失败，保留上次排行。'
        finally:
            with self._lock:
                self._projects_running = False

    @staticmethod
    def _native_path(root):
        if os.name == 'nt' and not str(root).startswith('\\\\?\\'):
            absolute = str(Path(root).absolute())
            return Path('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute)
        return root

    @staticmethod
    def _directory_size(root, assignments=None):
        # 一次遍历同时汇总工作区与项目；每个文件只计入一个项目及总量。
        assignments = assignments or {}
        stack = [(StorageMonitor._native_path(root), None)]
        size = files = skipped = 0

        while stack:
            path, owner = stack.pop()
            owner = assignments.get(os.path.normcase(str(path)), owner)
            try:
                stat = path.lstat()
                if path.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                    continue
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            stat = entry.stat(follow_symlinks=False)
                            if entry.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append((Path(entry.path), owner))
                            elif entry.is_file(follow_symlinks=False):
                                size += stat.st_size
                                files += 1
                                if owner is not None:
                                    owner['bytes'] += stat.st_size
                                    owner['files'] += 1
                        except OSError:
                            skipped += 1
                            if owner is not None:
                                owner['partial'] = True
            except OSError:
                skipped += 1
                if owner is not None:
                    owner['partial'] = True
        return size, files, skipped

    def _collect(self):
        try:
            started = time.perf_counter()
            usage = self._probe(self.workspace)
            sample = {'total': usage.total, 'used': usage.used, 'free': usage.free,
                      'volume': self.workspace.anchor,
                      'updated_at': datetime.now(timezone.utc).isoformat(),
                      'duration_ms': round((time.perf_counter() - started) * 1000, 2)}
            with self._lock:
                self._sample = sample
                self._error = None
                try:
                    self._save_locked()
                except OSError:
                    self._error = '容量已更新，但缓存保存失败。'
        except Exception:
            with self._lock:
                self._error = '采集失败，保留上次容量；请稍后重试。'
        finally:
            with self._lock:
                self._running = False
