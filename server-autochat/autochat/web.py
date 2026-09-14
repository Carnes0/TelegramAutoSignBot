import asyncio
import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import SettingsStore
from .runtime import Runtime, instance_lock

STATIC = Path(__file__).parent / 'static'


def create_app(directory: Path, password: str, secure_cookie: bool = False):
    if len(password) < 16:
        raise ValueError('PANEL_PASSWORD 至少需要 16 个字符，请先运行 python setup.py')
    password_hash = hashlib.sha256(password.encode()).digest()
    sessions, failures = {}, {}

    @asynccontextmanager
    async def lifespan(app):
        store = SettingsStore(directory)
        with instance_lock(directory / 'instance.lock'):
            runtime = Runtime(store)
            app.state.runtime = runtime
            task = asyncio.create_task(runtime.loop())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                runtime.state.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    async def body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, '请使用 JSON 请求')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, '请求内容过大')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'JSON 格式不正确') from None
        if not isinstance(data, dict):
            raise HTTPException(400, '请求必须是 JSON 对象')
        return data

    def authorize(request, write=False):
        session = sessions.get(request.cookies.get('autochat_session', ''))
        if not session or session['expires'] < time.monotonic():
            raise HTTPException(401, '请先登录面板')
        if write and not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        return session

    @app.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.get('/healthz')
    async def health():
        return {'ok': True}

    @app.post('/api/login')
    async def login(request: Request):
        now = time.monotonic()
        for key in list(failures):
            failures[key] = [t for t in failures[key] if t > now - 60]
            if not failures[key]:
                failures.pop(key)
        peer = request.client.host if request.client else 'unknown'
        if len(failures.get(peer, [])) >= 5 or len(failures) >= 1000:
            raise HTTPException(429, '尝试过于频繁，请一分钟后再试')
        data = await body(request)
        submitted = data.get('password', '')
        if not isinstance(submitted, str) or not hmac.compare_digest(hashlib.sha256(submitted.encode()).digest(), password_hash):
            failures.setdefault(peer, []).append(now)
            raise HTTPException(401, '密码不正确')
        failures.pop(peer, None)
        for token in list(sessions):
            if sessions[token]['expires'] < now:
                sessions.pop(token)
        if len(sessions) >= 20:
            sessions.pop(next(iter(sessions)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[token] = {'csrf': csrf, 'expires': now + 8 * 3600}
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('autochat_session', token, httponly=True, secure=secure_cookie,
                            samesite='strict', max_age=8 * 3600)
        return response

    @app.get('/api/session')
    async def session(request: Request):
        return {'csrf': authorize(request)['csrf']}

    @app.post('/api/logout')
    async def logout(request: Request):
        authorize(request, True)
        sessions.pop(request.cookies.get('autochat_session'), None)
        response = JSONResponse({'ok': True})
        response.delete_cookie('autochat_session')
        return response

    @app.get('/api/status')
    async def status(request: Request):
        authorize(request)
        return app.state.runtime.status()

    @app.get('/api/settings')
    async def settings(request: Request):
        authorize(request)
        return app.state.runtime.store.public()

    @app.post('/api/settings')
    async def save_settings(request: Request):
        authorize(request, True)
        data = await body(request)
        if 'enabled' in data:
            raise HTTPException(400, '请使用启用或暂停按钮')
        try:
            return app.state.runtime.store.save({**data, 'enabled': False})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post('/api/{action}')
    async def action(action: str, request: Request):
        authorize(request, True)
        runtime = app.state.runtime
        try:
            if action == 'pause':
                return runtime.store.save({'enabled': False})
            if action == 'resolve-uncertain':
                data = await body(request)
                if data.get('confirmed') is not True:
                    raise HTTPException(400, '请先在 Telegram 核查发送结果')
                if runtime.lock.locked():
                    raise HTTPException(409, '操作正在进行，请稍后核查')
                runtime.state.resolve_uncertain(runtime.store.read()['target'])
                return {'ok': True}
            functions = {'enable': runtime.enable, 'groups': runtime.groups, 'preview': runtime.preview}
            if action not in functions:
                raise HTTPException(404, '操作不存在')
            if runtime.lock.locked():
                raise HTTPException(409, '正在处理上一项操作，请稍后再试')
            return await asyncio.wait_for(functions[action](), 120)
        except ValueError:
            raise HTTPException(400, '配置不完整或无效，请检查凭据、Session 和群组') from None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, '连接操作失败：' + type(exc).__name__ + '。请检查配置及服务器网络。') from None

    return app
