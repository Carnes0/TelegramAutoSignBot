import sqlite3
from pathlib import Path

from .schedule import DAILY_LIMIT, INTERVAL, Slot


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS slots (
                target TEXT NOT NULL, day TEXT NOT NULL, slot INTEGER NOT NULL,
                status TEXT NOT NULL, attempt REAL, finished REAL,
                cursor INTEGER, digest TEXT, detail TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(target, day, slot));
            CREATE TABLE IF NOT EXISTS cooldown (target TEXT PRIMARY KEY, until REAL NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def claim(self, target: str, slot: Slot) -> bool:
        with self.db:
            return self.db.execute('INSERT OR IGNORE INTO slots(target,day,slot,status) VALUES(?,?,?,?)',
                                   (target, slot.day, slot.index, 'claimed')).rowcount == 1

    def blocked(self, target: str) -> bool:
        return self.db.execute("SELECT 1 FROM slots WHERE target=? AND status IN ('pending','uncertain') LIMIT 1", (target,)).fetchone() is not None

    def not_before(self, target: str) -> float:
        row = self.db.execute('SELECT until FROM cooldown WHERE target=?', (target,)).fetchone()
        return row[0] if row else 0

    def _cooldown(self, target: str, until: float):
        self.db.execute('INSERT INTO cooldown VALUES(?,?) ON CONFLICT(target) DO UPDATE SET until=MAX(until,excluded.until)', (target, until))

    def postpone(self, target: str, until: float):
        with self.db:
            self._cooldown(target, until)

    def reserve_send(self, target: str, slot: Slot, now: float, cursor: int = 0, digest: str = '') -> bool:
        try:
            self.db.execute('BEGIN IMMEDIATE')
            count = self.db.execute('SELECT COUNT(*) FROM slots WHERE target=? AND day=? AND attempt IS NOT NULL', (target, slot.day)).fetchone()[0]
            if self.blocked(target) or now < self.not_before(target) or count >= DAILY_LIMIT:
                self.db.rollback()
                return False
            changed = self.db.execute("UPDATE slots SET status='pending',attempt=?,cursor=?,digest=? WHERE target=? AND day=? AND slot=? AND status='claimed'", (now, cursor, digest, target, slot.day, slot.index)).rowcount
            if changed:
                self._cooldown(target, now + INTERVAL)
            self.db.commit()
            return bool(changed)
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, target: str, slot: Slot, status: str, detail: str = ''):
        with self.db:
            self.db.execute('UPDATE slots SET status=?,detail=? WHERE target=? AND day=? AND slot=?', (status, detail, target, slot.day, slot.index))

    def sent(self, target: str, slot: Slot, cursor: int, digest: str, now: float):
        with self.db:
            self.db.execute("UPDATE slots SET status='sent',finished=?,cursor=?,digest=? WHERE target=? AND day=? AND slot=?", (now, cursor, digest, target, slot.day, slot.index))
            self._cooldown(target, now + INTERVAL)

    def cursor(self, target: str) -> int:
        return self.db.execute("SELECT COALESCE(MAX(cursor),0) FROM slots WHERE target=? AND status IN ('sent','acknowledged')", (target,)).fetchone()[0]

    def seen_reply(self, target: str, digest: str) -> bool:
        rows = self.db.execute("SELECT digest FROM slots WHERE target=? AND status IN ('sent','acknowledged') ORDER BY attempt DESC LIMIT 30", (target,))
        return any(row[0] == digest for row in rows)

    def resolve_uncertain(self, target: str):
        with self.db:
            self.db.execute("UPDATE slots SET status='acknowledged',detail='用户已核查；不重发' WHERE target=? AND status IN ('pending','uncertain')", (target,))

    def status(self, target: str, day: str) -> dict:
        rows = self.db.execute('SELECT * FROM slots WHERE target=? AND day=? ORDER BY slot DESC', (target, day)).fetchall()
        return {'sent': sum(r['status'] == 'sent' for r in rows),
                'attempted': sum(r['attempt'] is not None for r in rows),
                'blocked': self.blocked(target), 'not_before': self.not_before(target),
                'records': [dict(r) for r in rows]}
