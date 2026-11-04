"""配置加载与校验。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workbench.config import ConfigError, load_config, write_example_config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def _valid(self, **overrides) -> dict:
        base = {
            "schema_version": 1,
            "workspace_root": str(self.workspace),
            "task_root": str(self.root / "task"),
            "port": 0,
            "apps": {"vscode_exe": None, "edge_exe": None, "obsidian_vault_path": None},
        }
        base.update(overrides)
        return base

    def test_load_valid(self):
        path = self._config("valid.json", self._valid())
        config = load_config(path)
        self.assertEqual(config["schema_version"], 1)
        self.assertEqual(config["workspace_root"], self.workspace)
        self.assertEqual(config["port"], 0)
        self.assertIn("config_path", config)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(self.root / "nope.json")

    def test_invalid_json(self):
        path = self.root / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_unknown_key(self):
        path = self._config("unknown.json", {**self._valid(), "surprise": 1})
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_bad_schema_version(self):
        path = self._config("schema.json", {**self._valid(), "schema_version": 2})
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_missing_required(self):
        path = self._config("missing.json", {**self._valid(), "workspace_root": ""})
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_workspace_root_not_dir(self):
        path = self._config("nodir.json", self._valid(workspace_root=str(self.root / "absent")))
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_apps_not_dict(self):
        path = self._config("apps.json", {**self._valid(), "apps": []})
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_port_range(self):
        for bad in (-1, 65536, "8080", True):
            path = self._config(f"port{type(bad).__name__}.json", self._valid(port=bad))
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_relative_roots_resolved_against_config_dir(self):
        # workspace_root 相对配置所在目录解析
        sub = self.root / "cfg"
        sub.mkdir()
        path = sub / "rel.json"
        path.write_text(json.dumps({**self._valid(), "workspace_root": "../workspace"}, ensure_ascii=False),
                        encoding="utf-8")
        config = load_config(path)
        self.assertEqual(config["workspace_root"].resolve(), self.workspace.resolve())

    def test_write_example_config(self):
        out = self.root / "example.json"
        write_example_config(out)
        self.assertTrue(out.is_file())
        # 示例配置本身可被加载（workspace_root 指向真实目录）
        loaded = load_config(out)
        self.assertEqual(loaded["schema_version"], 1)
        self.assertIsNone(loaded["apps"]["vscode_exe"])


if __name__ == "__main__":
    unittest.main()
