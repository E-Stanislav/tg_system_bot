#!/usr/bin/env python3
"""
Configuration module for Telegram Remote Monitoring & Management Bot
"""

import os
import sys
from pathlib import Path

# Optional: load .env if present
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:  # pragma: no cover - optional dependency
    pass

# Configuration helpers
DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Fallback to config.py if present
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
TEMP_SENSORS_COMMAND = os.getenv("TEMP_SENSORS_COMMAND")  # e.g. "sensors -u" or custom script

# Try to load from config.py if it exists and we're not already loading it
config_path = Path(__file__).with_name("config.py")
if config_path.exists() and config_path.resolve() != Path(__file__).resolve():
    # Import lazily so environment variables still override.
    import importlib.util
    _spec = importlib.util.spec_from_file_location("bot_config", str(config_path))
    if _spec and _spec.loader:  # pragma: no cover - defensive
        _config = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_config)  # type: ignore
        BOT_TOKEN = BOT_TOKEN or getattr(_config, "BOT_TOKEN", None)
        ADMIN_ID = ADMIN_ID or str(getattr(_config, "ADMIN_ID", ""))
        DEFAULT_LOG_LEVEL = DEFAULT_LOG_LEVEL or getattr(_config, "LOG_LEVEL", "INFO")
        if not TEMP_SENSORS_COMMAND:
            TEMP_SENSORS_COMMAND = getattr(_config, "TEMP_SENSORS_COMMAND", None)

# Validate required config
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set (env or config.py).", file=sys.stderr)
    sys.exit(1)

try:
    ADMIN_ID_INT = int(ADMIN_ID) if ADMIN_ID else None
except ValueError:  # pragma: no cover - defensive
    print("ERROR: ADMIN_ID must be an integer.", file=sys.stderr)
    sys.exit(1)

if ADMIN_ID_INT is None:
    print("ERROR: ADMIN_ID is not set (env or config.py).", file=sys.stderr)
    sys.exit(1)

# Logging configuration
LOG_FILE = os.getenv("BOT_LOG_FILE", "bot.log")

# Alert thresholds
ALERT_CPU_THRESHOLD = 90.0  # %
ALERT_RAM_THRESHOLD = 90.0  # %
ALERT_DISK_THRESHOLD = 10.0  # % свободного места
ALERT_SERVICES = ["nginx", "postgresql", "mysql", "docker"]  # важные сервисы
ALERT_DOCKER_CONTAINERS = ["nginx", "postgres", "mysql", "redis"]  # важные контейнеры
STATUS_SCHEDULE_SECONDS = 24 * 60 * 60  # раз в сутки 