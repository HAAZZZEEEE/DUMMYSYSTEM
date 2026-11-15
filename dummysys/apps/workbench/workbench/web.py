"""HTTP 契约：实例来源、内存会话、输入校验及统一错误响应。"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

from flask import Flask, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from .application import ERROR_CODE, ERROR_STATUS, Application
from .catalog import InvalidTarget
from .preferences import Preferences, PreferenceConflict
from .dmy import DmyError
from .release_info import release_info
from .tracing import trace
from .homepage import Homepage

STATIC_DIR = Path(__file__).resolve().parent / 'static'
MAX_CONTENT_LENGTH = 256 * 1024
BOOTSTRAP_TTL = 60.0


def create_app(application: Application, instance: dict, token_provider=None,
               static_dir: Path = STATIC_DIR) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
    tokens, sessions = {}, {}
    lock = threading.RLock()
    # 生产由生命周期提供实际端口；localhost:80 用于 Flask 内存测试。
    host = instance.get('host', '127.0.0.1' if instance.get('port') else 'localhost')
    expected_origin = ('http', host, instance.get('port', 80))
    cookie_name = 'workbench_session'
    homepage = Homepage(application.catalog)
    page_grants = {}

    def expire():
        now = time.monotonic()
        for key in [k for k, created in tokens.items() if now - created >= BOOTSTRAP_TTL]:
            tokens.pop(key, None)
        # 本地窗口会话与服务实例同寿命，退出服务即失效。任意时限会使
        # 已激活的 Edge 窗口失去恢复入口；只有一次性启动令牌按时间过期。

    def issue_bootstrap():
        with lock:
            expire()
            token = token_provider() if token_provider else secrets.token_urlsafe(32)
            tokens[token] = time.monotonic()
            return token

    app.extensions['bootstrap_issuer'] = issue_bootstrap

    def result(data, status=200):
        return jsonify({'schema_version': 1, 'data': data}), status

    def failure(code, message, status):
        return jsonify({'schema_version': 1, 'error': {
            'code': code, 'message': message, 'request_id': getattr(g, 'request_id', str(uuid.uuid4())),
        }}), status

    @app.errorhandler(Exception)
    def handle_error(error):
        if isinstance(error, DmyError):
            # dmy 的 error.code 多样，不塞进按异常类型映射的 ERROR_STATUS；
            # details 与 next_action 一并透传给前端，供诊断与下一步提示。
            payload = {'code': error.code, 'message': str(error),
                       'request_id': getattr(g, 'request_id', str(uuid.uuid4()))}
            if error.details:
                payload['details'] = error.details
            if error.next_action:
                payload['next_action'] = error.next_action
            return jsonify({'schema_version': 1, 'error': payload}), error.status
        if isinstance(error, PreferenceConflict):
            return failure('PREFERENCE_CONFLICT', str(error), 409)
        if isinstance(error, HTTPException):
            code = 'NOT_FOUND' if error.code == 404 else 'INVALID_REQUEST'
            return failure(code, '请求资源不存在' if error.code == 404 else '请求格式或大小不合法', error.code)
        if isinstance(error, PermissionError):
            return failure('FORBIDDEN', '没有访问该目标的权限', 403)
        if isinstance(error, FileNotFoundError):
            return failure('NOT_FOUND', '目标不存在', 404)
        for kind in type(error).__mro__:
            if kind in ERROR_STATUS:
                return failure(ERROR_CODE[kind], str(error), ERROR_STATUS[kind])
        app.logger.error('请求处理失败 request_id=%s type=%s', g.request_id, type(error).__name__)
        return failure('INTERNAL_ERROR', '内部错误，请查看运行记录', 500)

    def origin_tuple(value):
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (80 if parsed.scheme == 'http' else 443)

    @app.before_request
    def guard():
        g.request_id = str(uuid.uuid4())
        g.trace_token = trace.set(g.request_id)
        try:
            actual_host = origin_tuple('http://' + request.headers.get('Host', ''))
            origin = request.headers.get('Origin')
            # 沙箱页面是 opaque origin；只允许持有页面包能力的 GET 资源请求。
            page_request = request.path.startswith('/project-pages/') and request.method in ('GET', 'HEAD')
            if actual_host != expected_origin or (origin is not None and not (page_request and origin == 'null') and origin_tuple(origin) != expected_origin):
                return failure('FORBIDDEN', '请求来源与工作台实例不匹配', 403)
        except ValueError:
            return failure('FORBIDDEN', '请求来源不合法', 403)
        if not request.path.startswith('/api/v1/') or request.path == '/api/v1/session':
            return None
        with lock:
            expire()
            sid = request.cookies.get(cookie_name)
            user_session = sessions.get(sid)
            if not user_session:
                return failure('UNAUTHORIZED', '会话已失效，请重新启动工作台入口', 401)
            g.session_id = sid
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), user_session['csrf']):
                    return failure('FORBIDDEN', 'CSRF 校验失败', 403)

    @app.after_request
    def response_headers(response):
        response.headers['X-Diagnostic-ID'] = getattr(g, 'request_id', '')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.teardown_request
    def clear_trace(error):
        token=getattr(g,'trace_token',None)
        if token is not None:
            trace.reset(token)
            g.trace_token=None

    running_release=release_info()

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise InvalidTarget('请求正文必须是 JSON 对象')
        return data

    @app.get('/api/v1/overview')
    def overview():
        return result(application.overview())

    @app.get('/api/v1/storage')
    def storage():
        return result(application.storage.snapshot())

    @app.post('/api/v1/storage/refresh')
    def storage_refresh():
        return result(application.storage.snapshot(refresh=True))

    @app.get('/healthz')
    def health():
        return result({'app_id': instance.get('app_id'), 'schema_version': instance.get('schema_version'),
                       'instance_id': instance.get('instance_id'), 'ready': True, 'running_release':running_release})

    @app.post('/api/v1/session')
    def create_session():
        token = body().get('bootstrap_token')
        if not isinstance(token, str):
            return failure('UNAUTHORIZED', '一次性令牌无效或已过期', 401)
        with lock:
            expire()
            if tokens.pop(token, None) is None:
                return failure('UNAUTHORIZED', '一次性令牌无效或已过期', 401)
            sid = request.cookies.get(cookie_name)
            if sid not in sessions:
                sid = secrets.token_urlsafe(32)
                sessions[sid] = {'csrf': secrets.token_hex(16)}
            # 同一 Edge profile 的窗口共享 cookie，保留已有 CSRF，避免
            # 第二个启动窗口令第一个窗口的写操作全部失败。
            csrf = sessions[sid]['csrf']
        response = jsonify({'schema_version': 1, 'data': {
            'authenticated': True, 'instance_id': instance.get('instance_id'), 'csrf': csrf,
        }})
        response.set_cookie(cookie_name, sid, httponly=True, samesite='Strict', secure=False)
        return response

    @app.get('/api/v1/session')
    def current_session():
        with lock:
            user_session = sessions.get(request.cookies.get(cookie_name))
            if not user_session:
                return failure('UNAUTHORIZED', '会话已失效，请关闭窗口后重新启动工作台入口', 401)
            return result({'authenticated': True, 'instance_id': instance.get('instance_id'),
                           'csrf': user_session['csrf']})

    @app.get('/api/v1/meta')
    def meta():
        # 只读展示版本/源码提交/安装来源，不参与鉴权或实例身份判断。
        current=release_info()
        current['running_release']=running_release
        current['restart_required']=any(current.get(k)!=running_release.get(k) for k in ('version','sha','source_fingerprint'))
        return result(current)

    @app.get('/api/v1/projects')
    def projects():
        return result(application.list_projects(request.args.get('q'),
                      request.args.get('include_archived') in ('1', 'true')))

    @app.post('/api/v1/projects/refresh')
    def refresh():
        return result(application.refresh())

    @app.get('/api/v1/roots')
    def roots():
        project_id = request.args.get('project_id')
        if not project_id:
            raise InvalidTarget('缺少 project_id')
        return result(application.list_roots(project_id))

    @app.get('/api/v1/homepage')
    def project_homepage():
        project_id = request.args.get('project_id')
        if not project_id:
            raise InvalidTarget('缺少 project_id')
        grant = homepage.resolve(project_id)
        if grant is None:
            raise FileNotFoundError('该项目未配置首页')
        with lock:
            now = time.monotonic()
            for key in [k for k, (_, expiry) in page_grants.items() if expiry <= now]:
                page_grants.pop(key, None)
            while len(page_grants) >= 512:
                page_grants.pop(next(iter(page_grants)))
            capability = secrets.token_urlsafe(32)
            page_grants[capability] = (grant, now + 12 * 3600)
        return result({'url': f'/project-pages/{capability}/{quote(grant["entry"])}'})

    @app.get('/project-pages/<capability>/<path:relative>')
    def project_page_asset(capability, relative):
        with lock:
            entry = page_grants.get(capability)
        if not entry or entry[1] <= time.monotonic():
            return failure('FORBIDDEN', '页面访问已失效，请刷新项目首页', 403)
        path = homepage.asset(entry[0], relative)
        source = f'http://{host}:{expected_origin[2]}/project-pages/{capability}/'
        rendered = homepage.render_reference(entry[0], relative, path, source)
        response = app.response_class(rendered, mimetype='text/html') if rendered is not None else send_file(path)
        response.headers['Content-Security-Policy'] = (
            "sandbox allow-scripts; default-src 'none'; "
            f"script-src 'unsafe-inline' {source}; style-src 'unsafe-inline' {source}; "
            f"img-src {source} data: blob:; font-src {source} data:; "
            f"connect-src {source}; frame-src {source}; media-src {source} blob:; "
            "base-uri 'none'; form-action 'none'")
        response.headers['Access-Control-Allow-Origin'] = 'null'
        response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
        return response

    @app.get('/api/v1/nav')
    def project_nav():
        project_id = request.args.get('project_id')
        if not project_id:
            raise InvalidTarget('缺少 project_id')
        return result(application.project_nav(project_id))

    @app.get('/api/v1/deleted')
    def deleted():
        return result(application.list_deleted())

    @app.get('/api/v1/search')
    def global_search():
        return result(application.search(
            request.args.get('q'), request.args.getlist('types'),
            request.args.get('project_id')))

    @app.post('/api/v1/list')
    def directory():
        data = body()
        return result(application.list_directory(data.get('target'), data.get('filter'),
                                                data.get('cursor'), data.get('limit'),
                                                data.get('sort', 'name'), data.get('kind', 'all'),
                                                data.get('include_file_counts', False)))

    @app.post('/api/v1/actions')
    def actions():
        return result(application.available_actions(body().get('target')))

    @app.post('/api/v1/read')
    def read_text():
        return result(application.read_text(body().get('target')))

    @app.post('/api/v1/open')
    def open_target():
        data = body()
        return result(application.open(data.get('target'), data.get('action'), data.get('request_id'),
                                       session_id=g.session_id), 202)

    # ---- 治理读写：1:1 投影 dmy 命令组，写操作一律经子进程 ----
    @app.get('/api/v1/ptr/surface')
    def ptr_surface():
        return result(application.ptr_surface())

    @app.get('/api/v1/ptr/task')
    def ptr_task_show():
        task = request.args.get('task')
        if not task:
            raise InvalidTarget('缺少 task')
        return result(application.ptr_show_task(task))

    @app.post('/api/v1/ptr/task/create')
    def ptr_task_create():
        return result(application.ptr_create_task(body()))

    @app.post('/api/v1/ptr/task/update')
    def ptr_task_update():
        return result(application.ptr_update_task(body()))

    @app.post('/api/v1/ptr/task/handoff')
    def ptr_task_handoff():
        return result(application.ptr_handoff_task(body()))

    @app.post('/api/v1/ptr/task/rename')
    def ptr_task_rename():
        return result(application.ptr_rename_task(body()))

    @app.post('/api/v1/ptr/task/move')
    def ptr_task_move():
        return result(application.ptr_move_task(body()))

    @app.post('/api/v1/ptr/task/archive')
    def ptr_task_archive():
        return result(application.ptr_archive_task(body()))

    @app.post('/api/v1/ptr/task/unarchive')
    def ptr_task_unarchive():
        return result(application.ptr_unarchive_task(body()))

    @app.post('/api/v1/ptr/task/delete')
    def ptr_task_delete():
        return result(application.ptr_delete_task(body()))

    @app.post('/api/v1/ptr/task/undelete')
    def ptr_task_undelete():
        return result(application.ptr_undelete_task(body()))

    @app.get('/api/v1/ptr/run')
    def ptr_run_show():
        task, run = request.args.get('task'), request.args.get('run')
        if not task or not run:
            raise InvalidTarget('缺少 task 或 run')
        return result(application.ptr_show_run(task, run))

    @app.post('/api/v1/ptr/run/create')
    def ptr_run_create():
        return result(application.ptr_create_run(body()))

    @app.post('/api/v1/ptr/run/start')
    def ptr_run_start():
        return result(application.ptr_start_run(body()))

    @app.post('/api/v1/ptr/run/finish')
    def ptr_run_finish():
        return result(application.ptr_finish_run(body()))

    @app.post('/api/v1/ptr/run/update')
    def ptr_run_update():
        return result(application.ptr_update_run(body()))

    @app.post('/api/v1/ptr/run/rename')
    def ptr_run_rename():
        return result(application.ptr_rename_run(body()))

    @app.post('/api/v1/ptr/run/archive')
    def ptr_run_archive():
        return result(application.ptr_archive_run(body()))

    @app.post('/api/v1/ptr/run/unarchive')
    def ptr_run_unarchive():
        return result(application.ptr_unarchive_run(body()))

    @app.post('/api/v1/ptr/run/delete')
    def ptr_run_delete():
        return result(application.ptr_delete_run(body()))

    @app.post('/api/v1/ptr/run/undelete')
    def ptr_run_undelete():
        return result(application.ptr_undelete_run(body()))

    @app.get('/api/v1/ptr/project')
    def ptr_project_show():
        project = request.args.get('project')
        if not project:
            raise InvalidTarget('缺少 project')
        return result(application.ptr_show_project(project))

    @app.post('/api/v1/ptr/project/create')
    def ptr_project_create():
        return result(application.ptr_create_project(body()))

    @app.post('/api/v1/ptr/project/update')
    def ptr_project_update():
        return result(application.ptr_update_project(body()))

    @app.post('/api/v1/ptr/project/rename')
    def ptr_project_rename():
        return result(application.ptr_rename_project(body()))

    @app.post('/api/v1/ptr/project/pause')
    def ptr_project_pause():
        return result(application.ptr_pause_project(body()))

    @app.post('/api/v1/ptr/project/resume')
    def ptr_project_resume():
        return result(application.ptr_resume_project(body()))

    @app.post('/api/v1/ptr/project/archive')
    def ptr_project_archive():
        return result(application.ptr_archive_project(body()))

    @app.post('/api/v1/ptr/project/unarchive')
    def ptr_project_unarchive():
        return result(application.ptr_unarchive_project(body()))

    @app.post('/api/v1/ptr/project/delete')
    def ptr_project_delete():
        return result(application.ptr_delete_project(body()))

    @app.post('/api/v1/ptr/project/undelete')
    def ptr_project_undelete():
        return result(application.ptr_undelete_project(body()))

    @app.post('/api/v1/ptr/plan')
    def ptr_plan():
        return result(application.ptr_plan(body()))

    @app.get('/api/v1/ptr/operation')
    def ptr_operation_check():
        request_id = request.args.get('request_id')
        if not request_id:
            raise InvalidTarget('缺少 request_id')
        return result(application.ptr_check_operation(request_id))

    @app.get('/api/v1/preferences')
    def preferences():
        return preference_result(application.load_preferences())

    def preference_result(data):
        response = jsonify({'schema_version': 1, 'data': data})
        response.headers['ETag'] = Preferences.revision(data)
        return response

    @app.patch('/api/v1/preferences')
    def patch_preferences():
        return preference_result(application.save_preferences(body(), request.headers.get('If-Match')))

    @app.post('/api/v1/shutdown')
    def shutdown():
        app.extensions.get('shutdown_hook', lambda: None)()
        return result({'stopping': True, 'instance_id': instance.get('instance_id')})

    @app.post('/api/v1/restart')
    def restart():
        # 由 lifecycle 注入：派生 stop+launch 子进程；本请求返回后本进程即被停止。
        hook = app.extensions.get('restart_hook')
        if hook is None:
            return failure('RESTART_UNAVAILABLE', '当前运行方式不支持重启服务，请用命令行 stop 后 launch', 409)
        hook()
        return result({'restarting': True, 'instance_id': instance.get('instance_id')}, 202)

    @app.get('/')
    def index():
        return send_from_directory(static_dir, 'index.html')

    @app.get('/<path:filename>')
    def static_file(filename):
        base = static_dir.resolve()
        if not (base / filename).resolve().is_relative_to(base):
            return failure('FORBIDDEN', '静态资源越界', 403)
        return send_from_directory(static_dir, filename)

    return app
