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

# Read env first
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
TEMP_SENSORS_COMMAND = os.getenv("TEMP_SENSORS_COMMAND")  # e.g. "sensors -u" or custom script

# Fallback to user config.py at project root (one level up from this file's directory)
try:
    project_root = Path(__file__).resolve().parents[1]
    user_config_path = project_root / "config.py"
    if user_config_path.exists():
        import importlib.util
        _spec = importlib.util.spec_from_file_location("user_bot_config", str(user_config_path))
        if _spec and _spec.loader:  # pragma: no cover - defensive
            _config = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_config)  # type: ignore
            BOT_TOKEN = BOT_TOKEN or getattr(_config, "BOT_TOKEN", None)
            ADMIN_ID = ADMIN_ID or str(getattr(_config, "ADMIN_ID", ""))
            # Only override default level if not explicitly set via env
            DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", getattr(_config, "LOG_LEVEL", DEFAULT_LOG_LEVEL)).upper()
            if not TEMP_SENSORS_COMMAND:
                TEMP_SENSORS_COMMAND = getattr(_config, "TEMP_SENSORS_COMMAND", None)
except Exception:
    # Silent fallback; validation happens below
    pass

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

# Temperature alert settings
# Порог критической температуры (°C), при превышении шлем уведомление
ALERT_TEMP_THRESHOLD = float(os.getenv("ALERT_TEMP_THRESHOLD", "50.0"))
# Интервал проверки температуры в секундах
TEMP_MONITOR_INTERVAL_SECONDS = int(os.getenv("TEMP_MONITOR_INTERVAL_SECONDS", "10"))
# Гистерезис (°C) для сброса состояния перегрева, чтобы избежать флаппинга
TEMP_ALERT_HYSTERESIS = float(os.getenv("TEMP_ALERT_HYSTERESIS", "3.0"))