import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from autochat.content import ChatLine
from autochat.service import Service, RateLimited
from autochat.state import State
from test_core import moment


class FakeTelegram:
    def __init__(self):
        self.lines = [ChatLine(10, '大家最近在看什么书', '成员1')]
        self.sent = []
        self.failure = None

    async def context(self, now):
        return self.lines

    async def send(self, text, reply_to):
        self.sent.append((text, reply_to))
        if self.failure:
            raise self.failure


class FakeAI:
    def __init__(self):
        self.text = '最近在看科幻小说'
        self.calls = 0
        self.failure = None

    async def generate(self, lines):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.text


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.tmp.name) / 'state.db')
        self.now = moment()
        self.tg, self.ai = FakeTelegram(), FakeAI()
        self.service = Service('group', self.state, self.tg, self.ai, lambda: self.now)

    async def asyncTearDown(self):
        self.state.close()
        self.tmp.cleanup()

    async def test_sends_once_and_restart_does_not_repeat(self):
        self.assertEqual(await self.service.tick(), 'sent')
        again = Service('group', self.state, self.tg, self.ai, lambda: self.now)
        await again.tick()
        self.assertEqual(self.tg.sent, [('最近在看科幻小说', 10)])

    async def test_no_new_context_skips_without_api_call(self):
        await self.service.tick()
        self.now += timedelta(minutes=30)
        self.assertEqual(await self.service.tick(), 'no_new_context')
        self.assertEqual(self.ai.calls, 1)

    async def test_invalid_reply_gets_two_attempts_without_send(self):
        self.ai.text = '好'
        self.assertEqual(await self.service.tick(), 'invalid_reply')
        self.assertEqual(self.ai.calls, 2)
        self.assertEqual(self.tg.sent, [])

    async def test_duplicate_reply_not_sent(self):
        await self.service.tick()
        self.now += timedelta(minutes=30)
        self.tg.lines.append(ChatLine(11, '你觉得这本怎么样', '成员2'))
        self.assertEqual(await self.service.tick(), 'invalid_reply')
        self.assertEqual(len(self.tg.sent), 1)

    async def test_generation_error_does_not_send(self):
        self.ai.failure = TimeoutError('do not log secret text')
        self.assertEqual(await self.service.tick(), 'generation_failed')
        self.assertEqual(self.tg.sent, [])

    async def test_uncertain_send_blocks_future_slots(self):
        self.tg.failure = TimeoutError()
        self.assertEqual(await self.service.tick(), 'uncertain')
        self.now += timedelta(minutes=30)
        self.assertEqual(await self.service.tick(), 'blocked')
        self.assertEqual(len(self.tg.sent), 1)

    async def test_rate_limit_persists_cooldown(self):
        self.tg.failure = RateLimited(3600)
        self.assertEqual(await self.service.tick(), 'rate_limited')
        self.assertGreaterEqual(self.state.not_before('group'), self.now.timestamp() + 3600)
        self.assertFalse(self.state.blocked('group'))

    async def test_acknowledged_uncertain_send_does_not_repeat_context(self):
        self.tg.failure = TimeoutError()
        await self.service.tick()
        self.state.resolve_uncertain('group')
        self.tg.failure = None
        self.now += timedelta(minutes=30)
        self.assertEqual(await self.service.tick(), 'no_new_context')
        self.assertEqual(len(self.tg.sent), 1)

    async def test_delayed_generation_does_not_send_after_slot_deadline(self):
        async def generate(lines):
            self.now += timedelta(minutes=6)
            return '这个方法挺实用'
        self.ai.generate = generate
        self.assertEqual(await self.service.tick(), 'expired')
        self.assertEqual(self.tg.sent, [])

    async def test_pause_during_generation_prevents_send(self):
        enabled = [True]
        async def generate(lines):
            enabled[0] = False
            return '这个方法挺实用'
        self.ai.generate = generate
        self.service.enabled = lambda: enabled[0]
        self.assertEqual(await self.service.tick(), 'paused')
        self.assertEqual(self.tg.sent, [])
