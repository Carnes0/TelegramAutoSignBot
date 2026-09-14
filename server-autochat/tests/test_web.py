import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from autochat.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name), 'a-long-test-password-123')
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def login(self):
        response = self.client.post('/api/login', json={'password': 'a-long-test-password-123'})
        self.assertEqual(response.status_code, 200)
        return {'X-CSRF-Token': response.json()['csrf']}

    def test_auth_required(self):
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}).status_code, 401)

    def test_login_cookie_and_csrf(self):
        headers = self.login()
        self.assertEqual(self.client.get('/api/status').status_code, 200)
        self.assertEqual(self.client.post('/api/pause').status_code, 403)
        self.assertEqual(self.client.post('/api/pause', headers=headers).status_code, 200)

    def test_config_roundtrip_redacts_keys(self):
        headers = self.login()
        result = self.client.post('/api/settings', headers=headers,
            json={'deepseek_api_key': 'never-show-this-key', 'target': '-100123'})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('never-show-this-key', result.text)
        data = self.client.get('/api/settings').json()
        self.assertTrue(data['deepseek_api_key_set'])
        self.assertFalse(data['enabled'])

    def test_enable_cannot_bypass_validation_via_settings(self):
        headers = self.login()
        response = self.client.post('/api/settings', json={'enabled': True}, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.client.get('/api/status').json()['enabled'])

    def test_login_throttled(self):
        for _ in range(5):
            self.client.post('/api/login', json={'password': 'wrong'})
        self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}).status_code, 429)

    def test_preview_uses_runtime_and_never_tick(self):
        headers = self.login()
        runtime = self.app.state.runtime
        with patch.object(runtime, 'preview', new=AsyncMock(return_value={'reply': '这个方法挺实用'})):
            self.assertEqual(self.client.post('/api/preview', headers=headers).json()['reply'], '这个方法挺实用')
        self.assertEqual(self.client.get('/api/status').json()['attempted'], 0)

    def test_logout_invalidates_session(self):
        headers = self.login()
        self.client.post('/api/logout', headers=headers)
        self.assertEqual(self.client.get('/api/status').status_code, 401)
