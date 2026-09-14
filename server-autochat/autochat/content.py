import hashlib
import re
import unicodedata
from dataclasses import dataclass

HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def valid_reply(text: str) -> bool:
    if not isinstance(text, str) or not 5 <= len(HAN.findall(text)) <= 10 or len(text) > 14:
        return False
    return all(HAN.fullmatch(c) or c in '，。！？、；：,!?; ' for c in text)


def reply_digest(text: str) -> str:
    clean = ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())
    return hashlib.sha256(clean.encode()).hexdigest()


@dataclass(frozen=True)
class ChatLine:
    id: int
    text: str
    speaker: str
    reply_to: int | None = None
