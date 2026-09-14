# Telegram AutoChat Server Implementation Plan

**Goal:** Deliver a runnable, tested server application for one Telegram group with context-aware DeepSeek replies.

**Architecture:** Pure scheduling and validation functions; SQLite state; an asynchronous orchestration service with Telegram and HTTP adapters. CLI and Docker wrap the same service.

**Tech Stack:** Python 3.12+, Telethon 1.45.0, httpx 0.28.1, SQLite, unittest, Docker Compose.

Implementation proceeds inline in the current task; the user's server choice approves the design. A separate reviewer checks the completed code while deployment documentation is verified.

1. Create `tests/test_core.py` for UTC+8 date boundaries, 15 slots, missed slots, real 30-minute cooldown, durable claims, quotas, unresolved sends and reply validation. Run `python -m unittest discover -s tests -v` to observe the missing implementation. Implement `autochat/schedule.py`, `state.py`, `content.py` and rerun.
2. Create `tests/test_service.py` using actual temporary SQLite, a controlled clock and fake external adapters. Exercise normal flow, restart, no new conversation, invalid or duplicate reply, HTTP failure, uncertain send and daily sequence. Implement `autochat/service.py` and rerun tests.
3. Create `tests/test_adapters.py` with httpx MockTransport and Telethon message-shaped fixtures. Check API payload, malformed responses, context filtering, private group resolution and config validation. Implement `config.py`, `adapters.py` and CLI commands in `__main__.py`.
4. Add `Dockerfile`, `compose.yaml`, `.env.example`, ignore files and Chinese `README.md`. Document direct Python use as well as Docker, private configuration, server Session creation, dry preview, status and recovery.
5. Run all offline tests and bytecode compilation; run CLI help and safe missing-config checks. Request independent code review, resolve actionable issues and rerun affected tests. Package source into ZIP with no credentials, state or bytecode. Report actual checks and any deployment limitations.
