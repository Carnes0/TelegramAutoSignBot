from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8), 'UTC+8')
INTERVAL = 1800
DAILY_LIMIT = 15
GRACE = 300


@dataclass(frozen=True)
class Slot:
    day: str
    index: int
    start: datetime

    @property
    def deadline(self):
        return self.start + timedelta(seconds=GRACE)


def due_slot(now: datetime, not_before: float = 0) -> Slot | None:
    if now.tzinfo is None:
        raise ValueError('An aware datetime is required')
    local = now.astimezone(BEIJING)
    start = local.replace(hour=8, minute=0, second=0, microsecond=0)
    elapsed = (local - start).total_seconds()
    index = int(elapsed // INTERVAL)
    if not 0 <= index < DAILY_LIMIT or now.timestamp() < not_before:
        return None
    slot = Slot(local.date().isoformat(), index, start + timedelta(seconds=index * INTERVAL))
    return slot if local < slot.deadline else None
