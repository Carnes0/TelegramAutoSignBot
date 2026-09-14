"""Create a local deployment password without third-party dependencies."""
import os
import secrets
from pathlib import Path


def main():
    path = Path(__file__).resolve().parent / '.env'
    if path.exists():
        print('.env 已存在，未覆盖。请从该文件读取 PANEL_PASSWORD。')
        return
    os.umask(0o077)
    with path.open('x', encoding='utf-8') as handle:
        handle.write('PANEL_PASSWORD=' + secrets.token_urlsafe(24) + '\nCOOKIE_SECURE=false\n')
    print('已创建 .env，内含随机管理密码。请在服务器上读取并妥善保存。')


if __name__ == '__main__':
    main()
