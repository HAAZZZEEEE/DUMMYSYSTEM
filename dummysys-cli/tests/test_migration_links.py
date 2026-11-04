"""迁移的链接语义：4 条硬性要求 + 「链接仍指向原对象」的身份核验。

用户明确要求写进实现测试的一条：**「链接能解析」不等于「链接仍指向原对象」**。
同名文件、短链接、别名、路径重用都要验证仍指向原来的 Project/Task，而不是碰巧
指向另一个同名对象。仅比对「有无新增断链」不足以发现这种漂移。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dummysys_core._migration import (
    GovernanceError, obsidian_move, resolve_legacy_path, rewrite_external_links,
    verify_links,
)


class LinkIdentityTests(unittest.TestCase):
    """迁移后链接必须仍指向原对象（按 project_id/task_id 判定，不看路径字符串）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vault = self.root / 'dmy_vault'
        self.old = self.vault / 'A' / '任务'
        self.new = self.vault / 'A2' / '任务'
        self.twin = self.vault / 'B' / '任务'      # 同名的另一个对象
        for p in (self.old, self.twin):
            p.mkdir(parents=True)
            (p / 'README.md').write_text('---\ntask_id: %s\n---\n'
                                         % ('uuid-1' if p == self.old else 'uuid-2'), encoding='utf-8')
        self.old = self.old.resolve()
        self.twin = self.twin.resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def _move(self):
        self.new.parent.mkdir(parents=True, exist_ok=True)
        self.old.rename(self.new)
        self.new = self.new.resolve()

    def _identity(self, *dirs):
        out = {}
        for d in dirs:
            readme = d / 'README.md'
            if readme.is_file():
                for line in readme.read_text(encoding='utf-8').splitlines():
                    if line.startswith('task_id:'):
                        out[d.as_posix()] = line.split(':', 1)[1].strip()
        return out

    def test_same_named_object_link_follows_move(self):
        """同名文件：链接跟着原对象走；指向另一个同名对象即失败。"""
        before = {'unresolved': set(),
                  'resolved': {('note.md', '[[任务]]', self.old.as_posix())},
                  'identity': self._identity(self.old, self.twin)}
        self._move()
        good = {'unresolved': set(),
                'resolved': {('note.md', '[[任务]]', self.new.as_posix())},
                'identity': self._identity(self.new, self.twin)}
        self.assertEqual(verify_links(before, good, self.old, self.new)['checked_identity'], 1)

        # 碰巧解析到同名的另一个对象（uuid-2）——路径与身份都对不上，必须拒绝报成功。
        twin_named = self.new / '..' / '..' / 'B' / '任务'
        bad = {'unresolved': set(),
               'resolved': {('note.md', '[[任务]]', twin_named.resolve().as_posix())},
               'identity': self._identity(self.new, self.twin)}
        with self.assertRaises(GovernanceError) as caught:
            verify_links(before, bad, self.old, self.new)
        problems = '\n'.join(caught.exception.details.get('problems', []))
        self.assertIn('同名', problems)

    def test_identity_drift_at_same_relative_path_is_rejected(self):
        """相对位置对但对象身份变了（路径重用）：也必须拒绝。"""
        before = {'unresolved': set(),
                  'resolved': {('note.md', '[[任务]]', self.old.as_posix())},
                  'identity': {self.old.as_posix(): 'uuid-1'}}
        self._move()
        # 目标位置被塞进了另一个对象（uuid-9），路径看着一样，身份不对。
        (self.new / 'README.md').write_text('---\ntask_id: uuid-9\n---\n', encoding='utf-8')
        after = {'unresolved': set(),
                 'resolved': {('note.md', '[[任务]]', self.new.as_posix())},
                 'identity': {self.new.as_posix(): 'uuid-9'}}
        with self.assertRaises(GovernanceError):
            verify_links(before, after, self.old, self.new)

    def test_short_link_and_alias_are_subject_to_identity_check(self):
        """短链接与别名：Obsidian 都可能解析成功，但身份漂移照样要拦。"""
        for link in ('[[任务]]', '[[A/任务|别名]]'):
            with self.subTest(link=link):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    old = root / 'A' / '任务'
                    twin = root / 'B' / '任务'
                    new = root / 'A2' / '任务'
                    for p, uid in ((old, 'uuid-1'), (twin, 'uuid-2')):
                        p.mkdir(parents=True)
                        (p / 'README.md').write_text(f'---\ntask_id: {uid}\n---\n', encoding='utf-8')
                    before = {'unresolved': set(),
                              'resolved': {('note.md', link, old.resolve().as_posix())},
                              'identity': self._identity(old.resolve(), twin.resolve())}
                    new.parent.mkdir(parents=True)
                    old.rename(new)
                    good = {'unresolved': set(),
                            'resolved': {('note.md', link, new.resolve().as_posix())},
                            'identity': self._identity(new.resolve(), twin.resolve())}
                    self.assertEqual(verify_links(before, good, old, new)['checked_identity'], 1)
                    # 同名另一个对象被解析到了：短链接/别名都不该逃过身份核验。
                    bad = {'unresolved': set(),
                           'resolved': {('note.md', link, twin.resolve().as_posix())},
                           'identity': self._identity(new.resolve(), twin.resolve())}
                    with self.assertRaises(GovernanceError):
                        verify_links(before, bad, old, new)

    def test_new_unresolved_link_blocks_success(self):
        """要求 4：迁移后新增断链就不能报成功。"""
        before = {'unresolved': {('old.md', '[[早就断的]]')},
                  'resolved': set(), 'identity': {}}
        self._move()
        after = {'unresolved': {('old.md', '[[早就断的]]'), ('note.md', '[[被弄断的]]')},
                 'resolved': set(), 'identity': {}}
        with self.assertRaises(GovernanceError) as caught:
            verify_links(before, after, self.old, self.new)
        self.assertIn('新增断链', '\n'.join(caught.exception.details.get('problems', [])))

    def test_preexisting_broken_links_are_tolerated(self):
        """迁移前就断的链接不算新增，不应阻断成功。"""
        before = {'unresolved': {('a.md', '[[早就断的]]')},
                  'resolved': set(), 'identity': {}}
        self._move()
        after = {'unresolved': {('a.md', '[[早就断的]]')},
                 'resolved': set(), 'identity': {}}
        verify_links(before, after, self.old, self.new)


class LegacyPathResolutionTests(unittest.TestCase):
    """要求 3：历史事实不改写，靠旧路径映射解析到当前位置。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / 'runtime/state/workspace').mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _register(self, entries):
        path = self.root / 'runtime/state/workspace/retired-paths.json'
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')

    def test_maps_old_path_to_current(self):
        self._register([{'source': '/w/A', 'target': '/w/A2', 'identity': 'uuid-1', 'generation': 0}])
        (self.root / 'moved').mkdir()
        result = resolve_legacy_path(self.root, '/w/A', identity='uuid-1')
        self.assertTrue(result['via_mapping'])

    def test_reports_ambiguity_when_path_reused_by_other_object(self):
        """路径重用：老位置被另一个身份占用时，不能报「解析成功」指向那个对象。"""
        reused = self.root / 'reused'
        reused.mkdir()
        (reused / 'README.md').write_text('---\ntask_id: uuid-9\n---\n', encoding='utf-8')
        result = resolve_legacy_path(self.root, str(reused), identity='uuid-1')
        self.assertIsNone(result['resolved'], '路径还在、链接能解析，但已是另一个对象')
        self.assertIn('歧义', result.get('ambiguous', ''))

    def test_resolves_to_current_position_after_mapping(self):
        moved = self.root / 'moved'
        moved.mkdir()
        (moved / 'README.md').write_text('---\ntask_id: uuid-1\n---\n', encoding='utf-8')
        old = self.root / 'old'
        self._register([{'source': str(old), 'target': str(moved), 'identity': 'uuid-1', 'generation': 0}])
        result = resolve_legacy_path(self.root, str(old), identity='uuid-1')
        self.assertEqual(result['resolved'], str(moved))
        self.assertTrue(result['via_mapping'])

    def test_detects_mapping_cycle(self):
        self._register([{'source': '/w/A', 'target': '/w/B', 'identity': 'uuid-1', 'generation': 0},
                        {'source': '/w/B', 'target': '/w/A', 'identity': 'uuid-1', 'generation': 1}])
        result = resolve_legacy_path(self.root, '/w/A', identity='uuid-1')
        self.assertIsNone(result['resolved'])
        self.assertIn('成环', result.get('ambiguous', ''))


class ExternalReferenceTests(unittest.TestCase):
    """要求 2：Obsidian 不保证更新的引用要补——Base/Canvas/Vault 外/JSON 绑定。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vault = self.root / 'dmy_vault'
        (self.vault / '30-项目').mkdir(parents=True)
        res = self.root / 'runtime/project_src/项目'
        res.mkdir(parents=True)
        self.old = self.vault / '30-项目/项目/旧名'
        self.new = self.vault / '30-项目/项目/新名'
        self.old.mkdir(parents=True)
        (self.old / 'README.md').write_text('x', encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def test_rewrites_json_binding_canvas_and_base(self):
        res = self.root / 'runtime/project_src/项目'
        task_json = res / '旧名' / 'task.json'
        task_json.parent.mkdir(parents=True, exist_ok=True)
        task_json.write_text(json.dumps({'docs_root': str(self.old), 'resource_root': str(res / '旧名')}),
                             encoding='utf-8')
        (self.vault / 'q.base').write_text('path: %s' % self.old.relative_to(self.vault).as_posix(), encoding='utf-8')
        (self.vault / 'c.canvas').write_text(json.dumps({'nodes': [{'file': self.old.relative_to(self.vault).as_posix()}]}),
                                             encoding='utf-8')
        (self.vault / 'note.md').write_text('外链 %s\n' % self.old.as_posix(), encoding='utf-8')
        rewrite_external_links(self.root, [(self.old, self.new), (res / '旧名', res / '新名')])
        self.assertNotIn('旧名', task_json.read_text(encoding='utf-8'))
        self.assertNotIn('旧名', (self.vault / 'q.base').read_text(encoding='utf-8'))
        self.assertNotIn('旧名', (self.vault / 'c.canvas').read_text(encoding='utf-8'))
        self.assertNotIn('旧名', (self.vault / 'note.md').read_text(encoding='utf-8'))

    def test_registry_is_not_rewritten(self):
        registry = self.root / 'runtime/state/workspace/retired-paths.json'
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps([{'source': str(self.old), 'target': str(self.new)}]), encoding='utf-8')
        before = registry.read_text(encoding='utf-8')
        rewrite_external_links(self.root, [(self.old, self.new)])
        self.assertEqual(before, registry.read_text(encoding='utf-8'))


class ObsidianGuardTests(unittest.TestCase):
    """要求 1：Obsidian 条件不满足就报错，绝不降级成普通文件移动。"""

    def test_missing_obsidian_is_capability_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / 'dmy_vault'
            source = vault / 'A'
            target = vault / 'A2'
            source.mkdir(parents=True)
            (source / 'README.md').write_text('x', encoding='utf-8')
            with self.assertRaises(GovernanceError) as caught:
                obsidian_move(root, source, target, executable=str(root / 'nope'))
        self.assertEqual(caught.exception.code, 'CAPABILITY_UNAVAILABLE')

    def test_plain_move_never_masquerades_as_link_update(self):
        """Obsidian 不可用时目录不得被静默挪走——否则链接就留在旧位置。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / 'dmy_vault'
            source = vault / 'A'
            target = vault / 'A2'
            source.mkdir(parents=True)
            (source / 'README.md').write_text('x', encoding='utf-8')
            with self.assertRaises(GovernanceError):
                obsidian_move(root, source, target, executable=str(root / 'nope'))
            self.assertTrue(source.is_dir(), '源目录不得被普通移动')
            self.assertFalse(target.exists(), '目标不得出现')


if __name__ == '__main__':
    unittest.main()
