import json
import os
import re
import tempfile
from pathlib import Path

SECRET_FIELDS = ('api_hash', 'session_string', 'deepseek_api_key')
DEFAULTS = {'api_id': '', 'api_hash': '', 'session_string': '', 'deepseek_api_key': '',
            'target': '', 'model': 'deepseek-flash', 'enabled': False}


class SettingsStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'settings.json'
        if not self.path.exists():
            data = dict(DEFAULTS)
            for key in DEFAULTS:
                if key != 'enabled' and os.environ.get(key.upper()):
                    data[key] = os.environ[key.upper()]
            self._write(data)

    def read(self):
        return {**DEFAULTS, **json.loads(self.path.read_text(encoding='utf-8'))}

    def _write(self, data):
        fd, name = tempfile.mkstemp(prefix='.settings-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def save(self, changes):
        if not isinstance(changes, dict) or any(k not in DEFAULTS for k in changes):
            raise ValueError('配置字段不正确')
        data = self.read()
        for key, value in changes.items():
            if key == 'enabled':
                if not isinstance(value, bool):
                    raise ValueError('运行开关必须是布尔值')
            else:
                if not isinstance(value, str) or len(value) > 4096:
                    raise ValueError('配置值格式不正确')
                value = value.strip()
                if key in SECRET_FIELDS and not value:
                    continue
            data[key] = value
        if data['target'] and not re.fullmatch(r'(?:-\d{3,20}|@[A-Za-z][A-Za-z0-9_]{3,31})', data['target']):
            raise ValueError('群组请填写负数 ID 或 @群用户名')
        if data['api_id'] and (not data['api_id'].isdigit() or int(data['api_id']) <= 0):
            raise ValueError('API ID 必须是正整数')
        if data['api_hash'] and not re.fullmatch(r'[0-9a-fA-F]{32}', data['api_hash']):
            raise ValueError('API Hash 必须是 32 位十六进制字符')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', data['model']):
            raise ValueError('模型名称格式不正确')
        data['_revision'] = data.get('_revision', 0) + 1
        self._write(data)
        return self.public()

    def public(self):
        data = self.read()
        data.pop('_revision', None)
        for key in SECRET_FIELDS:
            data[key + '_set'] = bool(data.pop(key))
        return data

    def require_ready(self, need_target=True):
        data = self.read()
        required = ['api_id', 'api_hash', 'session_string']
        if need_target:
            required += ['target', 'deepseek_api_key']
        missing = [k for k in required if not data[k]]
        if missing:
            raise ValueError('请先填写：' + '、'.join(missing))
        return data
