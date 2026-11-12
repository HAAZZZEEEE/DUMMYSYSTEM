"""独立浏览器夹具：临时治理工作区、随机本机端口、真实 Edge。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))
sys.dont_write_bytecode = True

try:
    from playwright.sync_api import expect, sync_playwright
    from werkzeug.serving import WSGIRequestHandler, make_server
except ImportError as error:
    raise RuntimeError(
        "浏览器回归前置条件不满足：请使用 Task .venv，安装 Playwright/Flask，"
        "并提供已安装的 Microsoft Edge（channel=msedge）；不允许跳过测试。"
    ) from error

from tests.helpers import build_application, build_workspace
from workbench.web import create_app

expect.set_options(timeout=15000)

A = "browser-project-a"
B = "browser-project-b"
SPECIAL = "中文 空格[目录]#&"
DEEP = SPECIAL + "/第二层 [深]#&/第三层 空格"
SAME = "同名 文件[1]#&.txt"
MANY = "分页目录 [205]#&"

# 只延迟选定请求的真实 HTTP 响应，不替换业务数据。去掉该请求的 AbortSignal，
# 模拟响应已经越过取消点却晚交付给调用方，必须由产品的代次检查拦截。
DELAY_SCRIPT = r"""
(() => {
  const original = window.fetch.bind(window);
  window.__browserDelay = {spec: null, entered: false, delivered: false};
  window.fetch = async (input, options = {}) => {
    const gate = window.__browserDelay;
    const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch {}
    const spec = gate.spec;
    const matches = spec && !gate.entered && path.endsWith('/' + spec.endpoint)
      && (spec.project === undefined || body.target?.project_id === spec.project)
      && (spec.relative === undefined || body.target?.relative_path === spec.relative)
      && (spec.filter === undefined || body.filter === spec.filter)
      && (!spec.cursor || !!body.cursor);
    if (!matches) return original(input, options);
    gate.entered = true;
    const response = await original(input, {...options, signal: undefined});
    const text = await response.text();
    gate.ready = true;
    await new Promise(resolve => { gate.release = resolve; });
    gate.delivered = true;
    return new Response(text, {status: response.status, statusText: response.statusText,
      headers: response.headers});
  };
})();
"""


class QuietHandler(WSGIRequestHandler):
    """不记录 HTTP 地址、cookie、bootstrap token 或请求正文。"""

    def log(self, type, message, *args):
        pass


class BrowserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._output_temp = tempfile.TemporaryDirectory(prefix="wb-browser-output-")
        cls.addClassCleanup(cls._output_temp.cleanup)
        explicit = os.environ.get("WORKBENCH_TEST_OUTPUT")
        cls.output = Path(explicit).expanduser().resolve() if explicit else Path(cls._output_temp.name)
        if cls.output.is_relative_to(APP_ROOT.parents[1]):
            raise RuntimeError("WORKBENCH_TEST_OUTPUT 必须位于 Repo 之外，禁止写入仓库运行产物。")
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        try:
            cls.browser = cls.pw.chromium.launch(headless=True, **({"channel": "msedge"} if sys.platform == "win32" else {}))
        except Exception as error:
            raise RuntimeError("浏览器回归前置条件不满足：无法启动浏览器；Windows 需要 Edge，macOS 先运行 playwright install chromium。") from error
        cls.addClassCleanup(cls.browser.close)
        print(f"\n浏览器：Chromium {cls.browser.version}；headless；每例隔离 context。", flush=True)
        print(f"产物目录：{cls.output}（{'显式保留' if explicit else '退出后自动清理'}）", flush=True)
        print("验证边界：RecordingOpener 不启动系统应用；剪贴板 API 替身，不验系统剪贴板。", flush=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-browser-")
        self.addCleanup(self.temp.cleanup)
        # Windows TEMP 可能是 8.3 短路径；与真实 native_path 使用同一绝对路径。
        base = Path(self.temp.name).resolve()
        self.ws = build_workspace(base, {
            "项目 A": {"project_id": A, "title": "项目 A", "docs_root": "dmy_vault/项目 A",
                       "resource_root": "runtime/project_src/项目 A"},
            "项目 B": {"project_id": B, "title": "项目 B", "docs_root": "dmy_vault/项目 B",
                       "resource_root": "runtime/project_src/项目 B"},
        })
        self.docs = {A: self.ws / "dmy_vault/项目 A", B: self.ws / "dmy_vault/项目 B"}
        for project, root in self.docs.items():
            (root / DEEP).mkdir(parents=True)
            for folder in (root, root / SPECIAL, root / DEEP):
                (folder / SAME).write_text(project, encoding="utf-8")
            (root / "筛选-甲.txt").write_text("甲", encoding="utf-8")
            (root / "筛选-乙.txt").write_text("乙", encoding="utf-8")
            (root / MANY).mkdir()
            for number in range(205):
                (root / MANY / f"文件 {number:03d}[条目]#&.txt").write_text(str(number), encoding="utf-8")
        self.application, self.opener = build_application(self.ws, base / "task")
        self.server = make_server("127.0.0.1", 0, lambda env, start: [],
                                  threaded=True, request_handler=QuietHandler)
        self.addCleanup(self.server.server_close)
        self.app = create_app(self.application, {
            "app_id": "workbench-browser-test", "schema_version": 1,
            "instance_id": self.id(), "host": "127.0.0.1", "port": self.server.server_port,
        })
        self.server.app = self.app
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self._stop_server)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000},
                                                locale="zh-CN", color_scheme="light")
        self.addCleanup(self.context.close)
        self.context.add_init_script(DELAY_SCRIPT)
        self.page = self.context.new_page()
        self.page.set_default_timeout(12000)
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.list_calls = []
        self.open_calls = []
        self.response_codes = []
        self.page.on("request", self._record_request)
        self.page.on("response", self._record_response)
        self.addCleanup(self._capture_failure)
        token = self.app.extensions["bootstrap_issuer"]()
        try:
            self.page.goto(self.origin + "/#token=" + token)
        except Exception:
            raise RuntimeError("隔离测试服务 bootstrap 导航失败（隐藏含一次性令牌的 URL）。") from None
        expect(self.page.locator("#app")).to_be_visible()
        self.assertNotIn("#", self.page.url)

    def _stop_server(self):
        self.server.shutdown()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise RuntimeError("本测试创建的隔离 server 未正常退出。")

    def _record_request(self, request):
        endpoint = urlsplit(request.url).path
        if endpoint in ("/api/v1/list", "/api/v1/open"):
            (self.list_calls if endpoint.endswith("/list") else self.open_calls).append(request.post_data_json)

    def _record_response(self, response):
        if urlsplit(response.url).path == "/api/v1/list":
            self.response_codes.append(response.status)

    def _capture_failure(self):
        result = self._outcome.result
        if any(test is self for test, _ in result.failures + result.errors):
            # 仅 DOM 截图；不生成可能保存 cookie/token 的 HAR 或 trace。
            self.page.screenshot(path=str(self.output / (self._testMethodName + "-failure.png")), full_page=True)

    def tearDown(self):
        self.assertEqual(self.page_errors, [], "浏览器出现未捕获的 JavaScript 异常")

    def target_locator(self, testid, relative="", project=A, root="docs"):
        key = json.dumps({"project_id": project, "root_id": root, "relative_path": relative},
                         ensure_ascii=False, separators=(",", ":"))
        return self.page.locator(f'[data-testid="{testid}"][data-target={json.dumps(key, ensure_ascii=False)}]')

    def row(self, relative, project=A):
        return self.target_locator("directory-entry", relative, project)

    def node(self, relative="", project=A):
        return self.target_locator("tree-node", relative, project)

    def ready(self, relative="", project=A, root="docs"):
        expected = {"project_id": project, "root_id": root, "relative_path": relative}
        self.page.wait_for_function("expected => Object.entries(expected).every(([k,v]) => new URL(location.href).searchParams.get(k) === v)", arg=expected)
        expect(self.page.get_by_test_id("directory-view")).to_have_attribute("aria-busy", "false")
        expect(self.page.locator("#error-view")).to_be_hidden()
        self.assertEqual({key: value[0] for key, value in parse_qs(urlsplit(self.page.url).query, keep_blank_values=True).items()}, expected)

    def project(self, project=A):
        self.page.locator(f'[data-testid="project-link"][data-id="{project}"]').click()
        self.ready(project=project)

    def enter(self, relative, project=A):
        self.row(relative, project).click()
        self.ready(relative, project)

    def delay(self, endpoint, **conditions):
        self.page.evaluate("spec => { window.__browserDelay = {spec, entered:false, delivered:false}; }", {"endpoint": endpoint, **conditions})

    def delay_ready(self):
        self.page.wait_for_function("window.__browserDelay.ready === true")

    def release(self):
        self.page.evaluate("window.__browserDelay.release()")
        self.page.wait_for_function("window.__browserDelay.delivered === true")
        # 真实 fetch/JSON 消费继续若干事件轮，再断言没有过期 DOM/open 副作用。
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    def clipboard(self, reject=False):
        self.page.evaluate("""reject => {
          window.__clipboardWrites = [];
          Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
            writeText: async text => {
              if (reject) throw new DOMException('测试权限拒绝', 'NotAllowedError');
              window.__clipboardWrites.push(text);
            }
          }});
        }""", reject)
