import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import datetime

import httpx

from .adapters import connected, Telegram, DeepSeek
from .content import valid_reply
from .schedule import BEIJING, due_slot
from .service import Service
from .state import State

LOG = logging.getLogger('autochat')


@contextmanager
def instance_lock(path):
    with open(path, 'a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not handle.read(1):
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Runtime:
    def __init__(self, store):
        self.store = store
        self.state = State(store.directory / 'state.sqlite3')
        self.lock = asyncio.Lock()
        self.last_error = ''
        self.heartbeat = ''

    async def groups(self):
        config = self.store.require_ready(False)
        async with self.lock, connected(config) as (client, _):
            return [{'id': str(dialog.id), 'title': dialog.name}
                    async for dialog in client.iter_dialogs() if dialog.is_group]

    async def enable(self):
        config = self.store.require_ready()
        async with self.lock, connected(config) as (client, own_id):
            tg = Telegram(client, config['target'], own_id)
            target = await tg.resolve()
            if self.store.read() != config:
                raise ValueError('配置已修改，请重新点击启用')
            self.store.save({'target': target, 'enabled': True})
        return self.store.public()

    async def preview(self):
        config = self.store.require_ready()
        async with self.lock, connected(config) as (client, own_id), httpx.AsyncClient() as http:
            tg = Telegram(client, config['target'], own_id)
            await tg.resolve()
            lines = await tg.context(datetime.now(BEIJING))
            if not lines:
                return {'reply': '', 'valid': False, 'message': '最近两小时没有可用聊天内容', 'context_count': 0}
            reply = await DeepSeek(config['deepseek_api_key'], config['model'], http).generate(lines)
            return {'reply': reply, 'valid': valid_reply(reply), 'context_count': len(lines),
                    'message': '预览不会向 Telegram 发消息，也不计入每日次数'}

    async def cycle(self):
        config = self.store.read()
        self.heartbeat = datetime.now(BEIJING).isoformat()
        if not config['enabled']:
            return
        slot = due_slot(datetime.now(BEIJING), self.state.not_before(config['target']))
        if not slot or self.state.blocked(config['target']):
            return
        if self.state.db.execute('SELECT 1 FROM slots WHERE target=? AND day=? AND slot=?',
                                 (config['target'], slot.day, slot.index)).fetchone():
            return
        async with self.lock:
            # Configuration may have changed while waiting for a panel operation.
            if self.store.read() != config:
                return
            async with connected(config) as (client, own_id), httpx.AsyncClient() as http:
                tg = Telegram(client, config['target'], own_id)
                target = await tg.resolve()
                if target != config['target']:
                    self.store.save({'enabled': False})
                    raise ValueError('Target must be resolved before enabling')
                service = Service(target, self.state, tg,
                    DeepSeek(config['deepseek_api_key'], config['model'], http),
                    enabled=lambda: self.store.read() == config)
                result = await service.tick()
                if result != 'idle':
                    LOG.info('slot=%s result=%s', slot.index + 1, result)
                self.last_error = ''

    async def loop(self):
        while True:
            try:
                await asyncio.wait_for(self.cycle(), timeout=240)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Avoid repeating authentication/connection failures every 2 seconds.
                self.last_error = type(exc).__name__
                LOG.error('Worker stopped: %s', self.last_error)
                self.store.save({'enabled': False})
            await asyncio.sleep(2)

    def status(self):
        now = datetime.now(BEIJING)
        config = self.store.read()
        return {**self.state.status(config['target'], now.date().isoformat()),
                'enabled': config['enabled'], 'server_time': now.isoformat(),
                'heartbeat': self.heartbeat, 'last_error': self.last_error,
                'target': config['target'], 'daily_limit': 15,
                'schedule': '北京时间 08:00–15:00 / 每 30 分钟 / 每天最多 15 次'}
