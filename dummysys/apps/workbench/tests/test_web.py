"""HTTP 契约：统一响应、会话、CSRF、Origin/Host 校验与打开动作。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workbench.web import create_app
from tests.helpers import build_application, build_workspace

PID_A = "11111111-1111-4111-8111-111111111111"


class WebTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        vault = self.ws / "d" / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        (vault / "笔记.md").write_text("# 笔记\n", encoding="utf-8")
        (vault / "a.py").write_text("x = 1\n", encoding="utf-8")
        (vault / "sub").mkdir()
        (vault / "sub" / "inner.txt").write_text("i", encoding="utf-8")
        self.task_root = self.ws / "task"
        self.application, self.opener = build_application(self.ws, self.task_root,
                                                          obsidian_vault_path=str(vault))
        self.static = self.root / "static"
        self.static.mkdir()
        (self.static / "index.html").write_text("<html>工作台</html>", encoding="utf-8")
        (self.static / "app.js").write_text("console.log(1)", encoding="utf-8")
        self.instance = {"app_id": "dummysys.workbench", "schema_version": 1, "instance_id": "inst-1"}
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.doCleanups()
        self._tmp.cleanup()

    # ---- 辅助 ----
    def _issue(self) -> str:
        """模拟启动器经控制管道请求一次性令牌。"""
        return self.app.extensions["bootstrap_issuer"]()

    def _session(self) -> str:
        """建立会话，返回 csrf token。"""
        response = self.client.post("/api/v1/session",
                                    json={"bootstrap_token": self._issue()})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["data"]["csrf"]

    def _target(self, rel: str = "") -> dict:
        return {"project_id": PID_A, "root_id": "docs", "relative_path": rel}

    def _post(self, path: str, body: dict | None = None, csrf: str | None = "csrf",
             headers: dict | None = None):
        return self.client.post(path, json=body, headers={**(headers or {}),
                                                          "X-CSRF-Token": csrf or ""})


class HealthAndStaticTest(WebTestBase):
    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["app_id"], "dummysys.workbench")
        self.assertTrue(data["ready"])

    def test_index(self):
        response = self.client.get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn("工作台", response.get_data(as_text=True))

    def test_static_file(self):
        response = self.client.get("/app.js")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)

    def test_missing_static_file(self):
        response = self.client.get("/nope.css")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "NOT_FOUND")

    def test_static_path_traversal_blocked(self):
        response = self.client.get("/..%2Fworkbench%2Fconfig.py")
        self.assertEqual(response.status_code, 403)


class SessionTest(WebTestBase):
    def test_unauthenticated_projects_401(self):
        response = self.client.get("/api/v1/projects")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "UNAUTHORIZED")

    def test_session_invalid_token(self):
        response = self.client.post("/api/v1/session", json={"bootstrap_token": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_session_success_returns_csrf(self):
        response = self.client.post("/api/v1/session",
                                    json={"bootstrap_token": self._issue()})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["instance_id"], "inst-1")
        self.assertIsInstance(data["csrf"], str)
        self.assertTrue(data["csrf"])

    def test_session_token_single_use(self):
        token = self._issue()
        self.client.post("/api/v1/session", json={"bootstrap_token": token})
        response = self.client.post("/api/v1/session", json={"bootstrap_token": token})
        self.assertEqual(response.status_code, 401)

    def test_second_bootstrap_preserves_existing_window_csrf(self):
        csrf = self._session()
        self.assertEqual(self._session(), csrf)
        self.assertEqual(self._post('/api/v1/list', {'target': self._target()}, csrf=csrf).status_code, 200)

    def test_session_survives_idle_until_service_restart(self):
        csrf = self._session()
        with mock.patch('workbench.web.time.monotonic', return_value=10**12):
            self.assertEqual(self._post('/api/v1/list', {'target': self._target()}, csrf=csrf).status_code, 200)
        restarted = create_app(self.application, self.instance).test_client()
        restarted.set_cookie('workbench_session', self.client.get_cookie('workbench_session').value)
        self.assertEqual(restarted.get('/api/v1/session').status_code, 401)

    def test_session_restore_requires_cookie_and_exact_origin(self):
        self.assertEqual(self.client.get('/api/v1/session').status_code, 401)
        csrf = self._session()
        self.assertEqual(self.client.get('/api/v1/session').get_json()['data']['csrf'], csrf)
        self.assertEqual(self.client.get('/api/v1/session', headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_session_token_expired(self):
        token = self._issue()
        with mock.patch("workbench.web.BOOTSTRAP_TTL", -1):
            response = self.client.post("/api/v1/session", json={"bootstrap_token": token})
        self.assertEqual(response.status_code, 401)

    def test_wrong_origin_rejected(self):
        response = self.client.post("/api/v1/session",
                                    json={"bootstrap_token": self._issue()},
                                    headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_wrong_host_rejected(self):
        response = self.client.post("/api/v1/session",
                                    json={"bootstrap_token": self._issue()},
                                    headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_authenticated_then_projects_ok(self):
        self._session()
        response = self.client.get("/api/v1/projects")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual([p["project_id"] for p in data["projects"]], [PID_A])
        self.assertEqual(data["diagnostics"], [])


class CsrfTest(WebTestBase):
    def test_post_without_csrf_403(self):
        self._session()
        response = self._post("/api/v1/list", {"target": self._target()}, csrf="")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "FORBIDDEN")

    def test_post_wrong_csrf_403(self):
        self._session()
        response = self._post("/api/v1/list", {"target": self._target()}, csrf="nope")
        self.assertEqual(response.status_code, 403)

    def test_post_with_csrf_ok(self):
        csrf = self._session()
        response = self._post("/api/v1/list", {"target": self._target()}, csrf=csrf)
        self.assertEqual(response.status_code, 200)

    def test_get_does_not_require_csrf(self):
        self._session()
        response = self.client.get("/api/v1/roots?project_id=" + PID_A)
        self.assertEqual(response.status_code, 200)


class EndpointTest(WebTestBase):
    def test_roots(self):
        csrf = self._session()
        response = self.client.get("/api/v1/roots?project_id=" + PID_A)
        self.assertEqual(response.status_code, 200)
        roots = response.get_json()["data"]["roots"]
        self.assertEqual([r["root_id"] for r in roots], ["docs", "resources"])

    def test_roots_missing_project_id(self):
        csrf = self._session()
        response = self.client.get("/api/v1/roots")
        self.assertEqual(response.status_code, 400)

    def test_nav_returns_groups_and_hidden(self):
        self._session()
        (self.ws / "r" / "proj").mkdir(parents=True, exist_ok=True)
        task = "[task 1][20260921]示例任务"
        (self.ws / "d" / "vault" / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (self.ws / "d" / "vault" / task).mkdir()
        response = self.client.get("/api/v1/nav?project_id=" + PID_A)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["project_id"], PID_A)
        self.assertEqual([t["name"] for t in data["tasks"]], [task])
        hidden = {(h["root_id"], h["relative_path"]) for h in data["nav_hidden"]}
        self.assertIn(("docs", "README.md"), hidden)
        self.assertIn(("docs", "AGENTS.md"), hidden)
        self.assertIn(("docs", task), hidden)
        self.assertIn("roots", data)

    def test_nav_missing_project_id(self):
        self._session()
        self.assertEqual(self.client.get("/api/v1/nav").status_code, 400)

    def test_read_text_file(self):
        csrf = self._session()
        response = self._post("/api/v1/read", {"target": self._target("笔记.md")}, csrf=csrf)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertIn("# 笔记", data["text"])
        self.assertFalse(data["truncated"])

    def test_read_rejects_directory(self):
        csrf = self._session()
        response = self._post("/api/v1/read", {"target": self._target("sub")}, csrf=csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")

    def test_task_view_preference(self):
        csrf = self._session()
        response = self.client.patch("/api/v1/preferences", json={"task_view": "cards"},
                                     headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["task_view"], "cards")
        self.assertEqual(response.get_json()["data"]["preview_width"], None)
        bad = self.client.patch("/api/v1/preferences", json={"task_view": "nope"},
                                headers={"X-CSRF-Token": csrf})
        self.assertEqual(bad.status_code, 400)

    def test_list_directory(self):
        csrf = self._session()
        response = self._post("/api/v1/list", {"target": self._target()}, csrf=csrf)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        names = [e["name"] for e in data["entries"]]
        self.assertIn("笔记.md", names)
        self.assertIn("sub", names)

    def test_list_filter(self):
        csrf = self._session()
        response = self._post("/api/v1/list", {"target": self._target(), "filter": "a.py"},
                              csrf=csrf)
        data = response.get_json()["data"]
        self.assertEqual([e["name"] for e in data["entries"]], ["a.py"])

    def test_actions(self):
        csrf = self._session()
        response = self._post("/api/v1/actions", {"target": self._target("笔记.md")}, csrf=csrf)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["default_action"], "obsidian_open")

    def test_open_dispatches(self):
        csrf = self._session()
        response = self._post("/api/v1/open",
                              {"target": self._target("a.py"), "action": "vscode_open",
                               "request_id": "req-1"}, csrf=csrf)
        self.assertEqual(response.status_code, 202)
        data = response.get_json()["data"]
        self.assertEqual(data["status"], "dispatched")
        self.assertEqual(len(self.opener.events()), 1)

    def test_open_duplicate_request_id(self):
        csrf = self._session()
        body = {"target": self._target("a.py"), "action": "vscode_open", "request_id": "req-dup"}
        self._post("/api/v1/open", body, csrf=csrf)
        response = self._post("/api/v1/open", body, csrf=csrf)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.opener.events()), 1)

    def test_open_bad_action_error_envelope(self):
        csrf = self._session()
        response = self._post("/api/v1/open", {"target": self._target("a.py"), "action": "nope",
                                               "request_id": "req-2"}, csrf=csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")
        self.assertIn("request_id", response.get_json()["error"])

    def test_open_traversal_error_envelope(self):
        csrf = self._session()
        response = self._post("/api/v1/open", {"target": self._target("../evil"),
                                               "action": "vscode_open", "request_id": "req-3"},
                              csrf=csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")

    def test_preferences_roundtrip(self):
        csrf = self._session()
        response = self.client.patch("/api/v1/preferences",
                                     json={"pinned_project_ids": [PID_A]},
                                     headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        get = self.client.get("/api/v1/preferences")
        self.assertEqual(get.get_json()["data"]["pinned_project_ids"], [PID_A])

    def test_shutdown_hook_invoked(self):
        csrf = self._session()
        called = []
        self.app.extensions["shutdown_hook"] = lambda: called.append(True)
        response = self.client.post("/api/v1/shutdown", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(called, [True])

    def test_restart_hook_invoked_and_accepted(self):
        csrf = self._session()
        called = []
        self.app.extensions["restart_hook"] = lambda: called.append(True)
        response = self.client.post("/api/v1/restart", json={}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["data"]["restarting"], True)
        self.assertEqual(called, [True])

    def test_restart_without_hook_is_409(self):
        csrf = self._session()
        self.app.extensions.pop("restart_hook", None)
        response = self.client.post("/api/v1/restart", json={}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "RESTART_UNAVAILABLE")

    def test_restart_requires_csrf(self):
        self._session()
        response = self.client.post("/api/v1/restart", json={}, headers={"X-CSRF-Token": "bad"})
        self.assertEqual(response.status_code, 403)

    def test_search_unauthenticated_401(self):
        response = self.client.get("/api/v1/search?q=分析")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "UNAUTHORIZED")

    def test_search_authenticated_returns_results(self):
        self._session()
        # 项目规定位置补 README（含 project_id）与任务，使 search 能命中 p/t/r/文件。
        vault = self.ws / "d" / "vault"
        (vault / "README.md").write_text(
            "---\nproject_id: %s\ntitle: 工作台项目\nstatus: active\n---\n" % PID_A, encoding="utf-8")
        task = "[task 1][20260921]需求分析"
        (vault / task).mkdir()
        (vault / task / "README.md").write_text(
            "---\ntask_id: task-1\ntitle: 需求分析\nstatus: active\n---\n", encoding="utf-8")
        response = self.client.get("/api/v1/search?q=分析")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertIn("results", data)
        types = {r["type"] for r in data["results"]}
        self.assertIn("task", types)
        self.assertIn("file", types)

    def test_search_invalid_types_400(self):
        self._session()
        response = self.client.get("/api/v1/search?q=x&types=bogus")
        self.assertEqual(response.status_code, 400)

    def test_search_type_filter_query(self):
        self._session()
        vault = self.ws / "d" / "vault"
        (vault / "README.md").write_text(
            "---\nproject_id: %s\ntitle: 工作台项目\nstatus: active\n---\n" % PID_A, encoding="utf-8")
        response = self.client.get("/api/v1/search?q=项目&types=project")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["results"])
        self.assertTrue(all(r["type"] == "project" for r in data["results"]))


if __name__ == "__main__":
    unittest.main()
