import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autochat.schedule import BEIJING, due_slot
from autochat.state import State
from autochat.content import valid_reply, reply_digest


def moment(hour=8, minute=0, second=0, day=14):
    return datetime(2026, 9, day, hour, minute, second, tzinfo=BEIJING)


class ScheduleTests(unittest.TestCase):
    def test_fifteen_slots_including_eight_and_fifteen(self):
        slots = [due_slot(moment() + timedelta(minutes=30 * i)) for i in range(15)]
        self.assertEqual([s.index for s in slots], list(range(15)))
        self.assertEqual(slots[-1].start.hour, 15)

    def test_no_night_or_missed_slot_catchup(self):
        for now in [moment(7, 59), moment(8, 6), moment(15, 6), moment(15, 30), moment(23)]:
            with self.subTest(now=now):
                self.assertIsNone(due_slot(now))

    def test_timezone_and_next_day(self):
        self.assertEqual(due_slot(moment().astimezone(timezone.utc)).day, '2026-09-14')
        self.assertEqual(due_slot(moment(day=15)).index, 0)

    def test_actual_cooldown_can_delay_a_slot(self):
        until = moment(8, 30, 10).timestamp()
        self.assertIsNone(due_slot(moment(8, 30), until))
        self.assertEqual(due_slot(moment(8, 30, 10), until).index, 1)


class ContentTests(unittest.TestCase):
    def test_chinese_length_and_forbidden_output(self):
        self.assertTrue(valid_reply('这个方法挺实用！'))
        for text in ['好', '这是一个非常非常非常非常长的回答', 'SKIP', '/今天大家聊什么', '@张三这个方法好', '这个方法\n挺实用', 'https://x.co', '这个方法挺实用😀']:
            with self.subTest(text=text):
                self.assertFalse(valid_reply(text))

    def test_digest_ignores_punctuation(self):
        self.assertEqual(reply_digest('这个方法挺实用'), reply_digest('这个方法挺实用！'))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.state = State(self.path)
        self.slot = due_slot(moment())

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_claim_persists_across_connections(self):
        self.assertTrue(self.state.claim('group', self.slot))
        other = State(self.path)
        try:
            self.assertFalse(other.claim('group', self.slot))
        finally:
            other.close()

    def test_pending_send_blocks_later_sends_even_after_restart(self):
        self.state.claim('group', self.slot)
        self.assertTrue(self.state.reserve_send('group', self.slot, moment().timestamp()))
        self.assertTrue(self.state.blocked('group'))
        self.state.close()
        self.state = State(self.path)
        self.assertTrue(self.state.blocked('group'))
        self.state.resolve_uncertain('group')
        self.assertFalse(self.state.blocked('group'))
        self.assertGreater(self.state.not_before('group'), moment().timestamp())

    def test_success_updates_cursor_hash_and_completion_cooldown(self):
        self.state.claim('group', self.slot)
        self.state.reserve_send('group', self.slot, moment().timestamp())
        self.state.sent('group', self.slot, 22, 'digest', moment(8, 0, 2).timestamp())
        self.assertEqual(self.state.cursor('group'), 22)
        self.assertTrue(self.state.seen_reply('group', 'digest'))
        self.assertFalse(self.state.blocked('group'))
        self.assertEqual(self.state.not_before('group'), moment(8, 30, 2).timestamp())

    def test_fifteen_attempts_and_next_day_reset(self):
        for i in range(15):
            now = moment() + timedelta(minutes=i * 30)
            slot = due_slot(now)
            self.assertTrue(self.state.claim('group', slot))
            self.assertTrue(self.state.reserve_send('group', slot, now.timestamp()))
            self.state.sent('group', slot, i + 1, str(i), now.timestamp())
        self.assertEqual(self.state.status('group', self.slot.day)['sent'], 15)
        next_slot = due_slot(moment(day=15))
        self.assertTrue(self.state.claim('group', next_slot))
        self.assertTrue(self.state.reserve_send('group', next_slot, moment(day=15).timestamp()))


if __name__ == '__main__':
    unittest.main()
