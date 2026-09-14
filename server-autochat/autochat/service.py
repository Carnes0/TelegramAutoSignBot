import asyncio
from datetime import datetime

from .content import reply_digest, valid_reply
from .schedule import BEIJING, due_slot


class RateLimited(Exception):
    def __init__(self, seconds: int):
        self.seconds = seconds


class RejectedSend(Exception):
    """Telegram conclusively rejected this send; no automatic retry."""


class Service:
    def __init__(self, target, state, telegram, ai, clock=None, enabled=None):
        self.target, self.state, self.telegram, self.ai = target, state, telegram, ai
        self.clock = clock or (lambda: datetime.now(BEIJING))
        self.enabled = enabled or (lambda: True)

    async def tick(self):
        if not self.enabled():
            return 'paused'
        if self.state.blocked(self.target):
            return 'blocked'
        slot = due_slot(self.clock(), self.state.not_before(self.target))
        if slot is None or not self.state.claim(self.target, slot):
            return 'idle'

        def finish(status, detail=''):
            self.state.finish(self.target, slot, status, detail)
            return status

        try:
            lines = await self.telegram.context(self.clock())
        except RateLimited as exc:
            self.state.postpone(self.target, self.clock().timestamp() + exc.seconds)
            return finish('rate_limited')
        except Exception as exc:
            return finish('context_failed', type(exc).__name__)
        if not lines or max(line.id for line in lines) <= self.state.cursor(self.target):
            return finish('no_new_context')

        try:
            for _ in range(2):
                text = (await self.ai.generate(lines)).strip()
                if text == 'SKIP':
                    return finish('model_skipped')
                if valid_reply(text) and not self.state.seen_reply(self.target, reply_digest(text)):
                    break
            else:
                return finish('invalid_reply')
        except Exception as exc:
            return finish('generation_failed', type(exc).__name__)

        if not self.enabled():
            return finish('paused')
        if self.clock() >= slot.deadline:
            return finish('expired')
        if not self.state.reserve_send(self.target, slot, self.clock().timestamp(),
                                       max(line.id for line in lines), reply_digest(text)):
            return finish('guarded')
        try:
            await self.telegram.send(text, max(line.id for line in lines))
        except RateLimited as exc:
            self.state.postpone(self.target, self.clock().timestamp() + exc.seconds)
            return finish('rate_limited')
        except RejectedSend:
            return finish('rejected')
        except asyncio.CancelledError:
            finish('uncertain')
            raise
        except Exception as exc:
            return finish('uncertain', type(exc).__name__)
        self.state.sent(self.target, slot, max(line.id for line in lines), reply_digest(text), self.clock().timestamp())
        return 'sent'
