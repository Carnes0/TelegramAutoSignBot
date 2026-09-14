# Telegram AutoChat · 服务器管理面板

基于 Telethon 个人账号和 DeepSeek 的自动群聊程序。支持 Docker Compose，适合已有 Docker 的 Ubuntu 服务器。此目录可独立运行，原仓库的 `/checkin` 签到程序无需改动。

## 功能

- 中文管理面板：密码登录、运行统计、配置保存、群组列表、生成预览、启用／暂停、今日发送记录。
- 北京时间每天 **08:00、08:30……15:00**，共 15 个时段，每条 **5–10 个汉字**，允许少量标点。
- 每次读取最近两小时内最多 20 条有效文字作为上下文，过滤本人消息、机器人、命令和服务消息。只回复上次成功发送后新增的有效聊天。
- 字数检查、不重复近期回复、SQLite 持久去重、实际发送至少间隔 30 分钟。
- 没有新消息、生成失败、群组限流或错过时段时跳过，当天可能少于 15 条。每个时段最多允许 5 分钟启动延迟，不补发错过的时段。
- 密钥仅保存到服务器私有数据卷，面板不回显，普通运行日志不记录聊天正文。选取的群聊文字会提交给 DeepSeek，产生其 API 用量费用。

## 1. 在 Ubuntu 服务器启动

以下命令在**服务器 SSH 终端**执行。需要 Docker Compose V2（`docker compose version` 可检查），以及到 Telegram、DeepSeek、Docker Hub 和 PyPI 的出站网络。

```bash
git clone https://github.com/Carnes0/TelegramAutoSignBot.git
cd TelegramAutoSignBot/server-autochat
python3 setup.py
cat .env
docker compose up -d --build
docker compose ps
```

`setup.py` 生成随机面板密码，已有 `.env` 时不会覆盖。请保存 `PANEL_PASSWORD`，只在你自己的终端查看。无需将 API Key 或 Telegram Session 写进 GitHub。

## 2. 在自己的电脑打开面板

默认只开放服务器本机 `127.0.0.1:8080`，通过 SSH 隧道访问。在**你自己的电脑终端**执行（替换用户名和服务器地址）：

```bash
ssh -N -L 8080:127.0.0.1:8080 ubuntu@你的服务器IP
```

保持此窗口运行，在电脑浏览器打开 **http://127.0.0.1:8080**，用 `.env` 中的密码登录。

已有域名和 HTTPS 反向代理时，可将代理指向服务器 `127.0.0.1:8080`，并在 `.env` 设置 `COOKIE_SECURE=true` 后执行 `docker compose up -d`。代理需支持至少 150 秒的上游超时。不要直接把 HTTP 管理面板暴露到公网。SSH 隧道方式保持 `COOKIE_SECURE=false`。

## 3. 填写 Telegram 和 DeepSeek 配置

面板「连接与配置」填写：

| 配置项 | 如何填写 |
| --- | --- |
| Telegram API ID | 在 [my.telegram.org](https://my.telegram.org) 创建应用取得；与原签到项目的 `API_ID` 含义相同 |
| API Hash | 同一应用的 `API_HASH`，32 位十六进制 |
| Telegram Session | Telethon `StringSession`；推荐为这个服务器新建专用会话，见下节 |
| DeepSeek API Key | 在 [DeepSeek 平台](https://platform.deepseek.com/) 创建 |
| 模型名称 | 默认 `deepseek-flash`；可填写账号支持的其他模型名称 |
| 目标群组 | 负数群 ID（例如 `-100…`），或者公开群的 `@用户名` |

1. 保存账号凭据后点击 **读取我的群组**，从下拉框选择群组。
2. 填好 DeepSeek Key，再次 **保存配置**。
3. 点击 **生成回复预览** 检查连接和效果。预览会调用 DeepSeek，但不发送、不占用每日次数；若近期没有有效聊天，将显示跳过。
4. 点击 **启用自动回复**。这会验证 Telegram 登录和目标群组，之后在计划时段运行；首次启动默认暂停。

已保存的密钥字段留空表示保留，不会用空值覆盖。修改配置后会暂停自动回复，需要再次启用。只有点击暂停前尚未提交的发送可以被阻止，已经提交给 Telegram 的消息不会撤回。

请仅用于允许自动回复的群组。账号必须已加入目标群，并具有查看历史和发言权限。普通私聊和广播频道不会被接受为目标。论坛群当前没有话题选择功能；程序回复最近的有效消息所在位置。

## 可选：在服务器创建独立 Telegram 会话

可以复用原项目的 API ID / API Hash。为了避免同一个 Session 在 GitHub Actions 和服务器两地同时使用，建议通过下列命令创建服务器专用 Session：

```bash
docker compose stop autochat
docker compose run --rm autochat python -m autochat login
docker compose up -d
```

依提示输入 API ID、API Hash、带国家区号的手机号、Telegram 验证码及两步验证密码（如有）。程序把新会话直接保存进私有数据卷，**不打印 Session**。回到面板刷新即可看到 Session 已保存。该命令不会发送群消息。

必须先停服务再运行登录命令，否则实例锁会阻止多个进程同时使用数据目录。

## 运维

```bash
# 状态、日志
docker compose ps
docker compose logs --tail=100 -f

# 停止服务器程序；仅暂停发言也可在面板操作
docker compose stop

# 更新源码后重新构建
git pull --ff-only
docker compose up -d --build
```

数据保存在 Compose 命名卷 `autochat-data`，重启、更新镜像和普通 `docker compose down` 都会保留。**不要使用 `docker compose down -v`，否则会删除密钥、Session 和发送状态。** 只运行一个实例；不要复制数据到第二个同时运行的服务器。

同一天，同一个目标群最多预约 15 次发送。计数包含已经发起但失败或结果不确定的尝试，以避免重试造成超发；面板分别显示实际成功和运行记录。变更目标群后按该群自己的持久记录计算，不是多群轮发工具。

发送前先将预约写入 SQLite。如果进程在发送时崩溃或网络超时，不能判断 Telegram 是否收到，因此会阻止该群后续自动发送。面板出现核查提示后，在 Telegram 检查，再点击 **我已核查，解除保护**；不会重发原消息，也不会清除 30 分钟冷却。普通限流会按平台给出的时间冷却。

服务器重启会保持上次启用／暂停状态，但不会补发已错过的时段。若连接失败导致自动暂停，面板会显示错误类别，修复配置或网络后重新启用。确保服务器系统时间同步；程序固定按 UTC+8 计算，不依赖宿主机时区。

面板密码修改：编辑服务器 `.env` 中 `PANEL_PASSWORD`（至少 16 字符），执行 `docker compose up -d` 重建容器，已有面板登录会失效。密钥及 Session 保存文件权限为仅容器用户可读写；数据卷本身仍需按凭据备份保护。

## 不使用 Docker

Python 3.12 或更高版本，在本目录安装依赖并启动：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python setup.py
set -a
. ./.env
set +a
python -m autochat serve
```

如需生成会话，先停止面板，再执行 `python -m autochat login`。直接运行时数据默认位于 `data/`，也可用 `--data-dir` 指定。不要使用多个 Uvicorn worker。生产常驻推荐前面的 Docker 方式。

## 开发与验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q autochat setup.py
```

离线测试使用临时 SQLite 和模拟的 Telegram／HTTP 边界，不消耗真实 API 费用、不向群发送消息。真实账号登录、DeepSeek 调用和服务器 Docker 构建需在部署时按上述预览步骤验证。

接口与实现参考：[DeepSeek API](https://api-docs.deepseek.com/)、[Telethon 客户端](https://docs.telethon.dev/en/stable/modules/client.html)、[FastAPI 生命周期](https://fastapi.tiangolo.com/advanced/events/)。
