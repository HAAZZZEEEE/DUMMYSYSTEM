"""快捷入口保存的是导航引用；实际打开仍受 Catalog 边界校验。"""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from workbench.preferences import Preferences, PreferenceConflict
from workbench.catalog import InvalidTarget


class QuickAccessPreferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'preferences.json'
        self.prefs = Preferences(self.path)
        self.target = {'project_id': 'p', 'root_id': 'docs', 'relative_path': '中文/[task 1]'}

    def test_old_file_and_independent_patch_preserve_navigation_lists(self):
        self.path.write_text(json.dumps({'theme': 'dark'}), encoding='utf-8')
        self.assertEqual(self.prefs.read()['pinned_locations'], [])
        self.prefs.patch({'pinned_locations': [self.target]})
        self.prefs.patch({'recent_locations': [self.target]})
        self.prefs.patch({'pinned_project_ids': ['q']})
        loaded = Preferences(self.path).read()
        self.assertEqual(loaded['theme'], 'dark')
        self.assertEqual(loaded['pinned_locations'], [self.target])
        self.assertEqual(loaded['recent_locations'], [self.target])

    def test_homepage_pins_persist_per_project_and_preserve_other_preferences(self):
        self.prefs.patch({'theme': 'dark', 'homepage_pins': {'a': ['report1', 'report1'], 'b': ['report2']}})
        loaded = Preferences(self.path).read()
        self.assertEqual(loaded['homepage_pins'], {'a': ['report1'], 'b': ['report2']})
        self.assertEqual(loaded['theme'], 'dark')
        for invalid in ([], {'a': [None]}, {'a': ['']}, {'a': ['x' * 513]}, {'a': ['bad\nkey']}):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidTarget):
                self.prefs.patch({'homepage_pins': invalid})
        self.assertEqual(Preferences(self.path).read()['homepage_pins']['b'], ['report2'])

    def test_homepage_display_overrides_persist_normalize_and_validate(self):
        self.prefs.patch({'homepage_pins': {'a': ['batch1']}, 'theme': 'dark',
                         'homepage_overrides': {'a': {'batch1': {'name': ' 新名称 ', 'description': '介绍\n第二行'}}}})
        loaded = Preferences(self.path).read()
        self.assertEqual(loaded['homepage_overrides']['a']['batch1'], {'name': '新名称', 'description': '介绍\n第二行'})
        self.assertEqual(loaded['homepage_pins'], {'a': ['batch1']})
        self.assertEqual(loaded['theme'], 'dark')
        for invalid in ({'a': {'b': {'name': 'x' * 121}}}, {'a': {'b': {'description': 3}}},
                        {'a': {'b': {'path': 'secret'}}}, {'a': {'b': {'name': 'bad\nname'}}}):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidTarget):
                self.prefs.patch({'homepage_overrides': invalid})
        self.prefs.patch({'homepage_overrides': {'a': {'batch1': {'name': ' ', 'description': ''}}}})
        self.assertEqual(Preferences(self.path).read()['homepage_overrides'], {'a': {}})
        self.assertEqual(Preferences(self.path).read()['homepage_pins'], {'a': ['batch1']})

    def test_navigation_sort_defaults_validation_and_persistence(self):
        self.assertEqual(self.prefs.read()['nav_sort'], 'default')
        for value in ('name', 'name_desc', 'newest', 'oldest', 'default'):
            self.prefs.patch({'nav_sort': value})
            self.assertEqual(Preferences(self.path).read()['nav_sort'], value)
        with self.assertRaises(InvalidTarget):
            self.prefs.patch({'nav_sort': 'unsupported'})

    def test_actor_defaults_and_legacy_empty_identity_preserve_other_settings(self):
        self.assertEqual(self.prefs.read()['actor'], 'workbench')
        self.path.write_text(json.dumps({'actor': '', 'theme': 'dark'}), encoding='utf-8')
        self.assertEqual(self.prefs.read()['actor'], 'workbench')
        self.assertEqual(self.prefs.read()['theme'], 'dark')
        self.assertEqual(self.prefs.patch({'actor': '   '})['actor'], 'workbench')
        self.prefs.patch({'actor': '  alice  '})
        self.assertEqual(Preferences(self.path).read()['actor'], 'alice')

    def test_unsupported_saved_view_falls_back_without_losing_other_preferences(self):
        self.path.write_text(json.dumps({'task_view': 'obsolete-view', 'theme': 'dark'}), encoding='utf-8')
        loaded = self.prefs.read()
        self.assertEqual(loaded['task_view'], 'indent')
        self.assertEqual(loaded['theme'], 'dark')

    def test_deduplicates_normalized_paths_independent_of_key_order(self):
        alternate = {'relative_path': r'中文\[task 1]', 'root_id': 'docs', 'project_id': 'p'}
        self.assertEqual(self.prefs.patch({'recent_locations': [self.target, alternate]})['recent_locations'], [self.target])

    def test_rejects_invalid_or_excessive_lists_without_changing_file(self):
        self.prefs.patch({'theme': 'dark'})
        before = self.path.read_bytes()
        bad_locations = [None, {}, {**self.target, 'relative_path': '../secret'},
                         {**self.target, 'relative_path': r'C:\secret'},
                         {**self.target, 'relative_path': r'\\server\share'},
                         {**self.target, 'relative_path': '/outside'},
                         {**self.target, 'project_id': ''},
                         {**self.target, 'extra': True}]
        patches = [{'pinned_locations': [x]} for x in bad_locations]
        patches += [{'recent_locations': [self.target] * 9},
                    {'pinned_locations': [self.target] * 31}, {'recent_locations': {}}]
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(InvalidTarget):
                self.prefs.patch(patch)
            self.assertEqual(self.path.read_bytes(), before)

    def test_stale_reference_can_be_removed_without_resolving_filesystem(self):
        self.prefs.patch({'pinned_locations': [self.target]})
        self.prefs.patch({'pinned_locations': []})
        self.assertEqual(self.prefs.read()['pinned_locations'], [])

    def test_stale_revision_cannot_overwrite_other_window_and_retry_merges(self):
        revision = self.prefs.revision(self.prefs.read())
        first = self.prefs.patch({'pinned_locations': [self.target]}, revision)
        other = {**self.target, 'project_id': 'q'}
        with self.assertRaises(PreferenceConflict):
            self.prefs.patch({'pinned_locations': [other]}, revision)
        self.assertEqual(self.prefs.read(), first)
        merged = self.prefs.patch({'pinned_locations': first['pinned_locations'] + [other]},
                                 self.prefs.revision(first))
        self.assertEqual(merged['pinned_locations'], [self.target, other])

    def test_simultaneous_same_revision_has_exactly_one_writer(self):
        revision = self.prefs.revision(self.prefs.read())
        barrier = Barrier(2)
        def update(project):
            barrier.wait(timeout=5)
            try:
                self.prefs.patch({'pinned_locations': [{**self.target, 'project_id': project}]}, revision)
                return 'saved'
            except PreferenceConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(update, ['p', 'q']), ['saved', 'conflict'])
        self.assertEqual(len(self.prefs.read()['pinned_locations']), 1)


if __name__ == '__main__':
    unittest.main()
