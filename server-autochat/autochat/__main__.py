import argparse
import asyncio
import getpass
import logging
import os
from pathlib import Path

from .config import SettingsStore


async def login(directory):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from .runtime import instance_lock
    store = SettingsStore(directory)
    with instance_lock(directory / 'instance.lock'):
        data = store.read()
        api_id = input('Telegram API ID: ').strip() or data['api_id']
        api_hash = getpass.getpass('Telegram API Hash（输入隐藏）: ').strip() or data['api_hash']
        # Validate before opening a network connection.
        store.save({'api_id': api_id, 'api_hash': api_hash, 'enabled': False})
        client = TelegramClient(StringSession(), int(api_id), api_hash)
        try:
            await client.start(phone=lambda: input('手机号（包含国家区号）: '),
                               code_callback=lambda: getpass.getpass('Telegram 验证码: '),
                               password=lambda: getpass.getpass('Telegram 两步验证密码: '))
            store.save({'session_string': client.session.save(), 'enabled': False})
            print('登录已保存到私有数据目录。启动面板后读取群组并配置 DeepSeek 即可。')
        finally:
            await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description='Telegram 自动群聊服务器和管理面板')
    parser.add_argument('command', nargs='?', choices=['serve', 'login'], default='serve')
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR', 'data'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('telethon').setLevel(logging.CRITICAL)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        if args.command == 'login':
            asyncio.run(login(Path(args.data_dir)))
        else:
            import uvicorn
            from .web import create_app
            app = create_app(Path(args.data_dir), os.environ.get('PANEL_PASSWORD', ''),
                             os.environ.get('COOKIE_SECURE', 'false').lower() == 'true')
            uvicorn.run(app, host=args.host, port=args.port, workers=1, access_log=False,
                        proxy_headers=False, timeout_graceful_shutdown=50)
    except KeyboardInterrupt:
        return
    except Exception as exc:
        # Exception messages from remote providers can include request data.
        print('启动失败：' + type(exc).__name__ + '。请检查配置、面板密码长度及是否已有实例运行。')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
