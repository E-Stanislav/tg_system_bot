#!/usr/bin/env python3
"""
Telegram Remote Monitoring & Management Bot for Linux Servers
=============================================================

Single-file aiogram-based bot that allows **one authorized administrator** to remotely monitor and
perform selected management operations on a Linux server. The bot is intentionally conservative:
all privileged system-changing operations are performed via `sudo` and are *explicitly gated* by
admin confirmation (inline buttons) to reduce the risk of an accidental tap.

> ⚠️ **Security reminder**: Ensure the `telegram-bot` runtime user on the server has only the minimal
> sudo privileges required for the actions you enable (e.g., NOPASSWD: /sbin/reboot, /sbin/shutdown,
> /usr/bin/apt, /bin/systemctl). Never grant full passwordless root unless you accept the risk.

---
Table of Contents
-----------------
1. Quick Start
2. Configuration (Environment Variables / config.py)
3. Safety & Sudo Configuration Notes
4. Runtime Dependencies
5. Code Overview
6. Full Source

---
1. Quick Start
--------------
```bash
python3 -m venv venv
source venv/bin/activate
pip install aiogram psutil python-dotenv
# (optional) sensors support: sudo apt install lm-sensors && sudo sensors-detect

# Set environment variables (recommended)
export BOT_TOKEN="123456:ABC..."
export ADMIN_ID="123456789"   # your Telegram numeric user id
export LOG_LEVEL="INFO"       # optional: DEBUG, INFO, WARNING ...

python3 bot.py
```

---
2. Configuration
----------------
The bot will load its runtime configuration by the following precedence order:
1. Environment variables (strongly recommended for production).
2. `config.py` in the same directory (fallback during development).

Supported variables:
- `BOT_TOKEN`   : Telegram bot token from BotFather.
- `ADMIN_ID`    : Integer Telegram user ID of the single allowed administrator.
- `LOG_LEVEL`   : Python logging level name (default: INFO).
- `TEMP_SENSORS_COMMAND` : Optional override shell command to read CPU temp. Default auto-detect.

Create a *minimal* `config.py` if you prefer that route:
```python
BOT_TOKEN = "123456:ABC..."
ADMIN_ID = 123456789
LOG_LEVEL = "INFO"
# TEMP_SENSORS_COMMAND = "sensors -u"
```

---
3. Safety & Sudo Configuration Notes
------------------------------------
To allow the bot (running as user `telegrambot`, adjust as needed) to reboot, shutdown, update, and
control services without an interactive password, create a sudoers drop-in file:

```bash
sudo visudo -f /etc/sudoers.d/telegrambot
```
Example contents (tailor to your distro paths!):
```text
telegrambot ALL=(root) NOPASSWD:/sbin/reboot,/sbin/shutdown,/usr/bin/apt,/usr/bin/apt-get,/usr/bin/systemctl
```
> *Check actual binary paths with `which reboot`, `which shutdown`, `which systemctl`, etc.*

---
4. Runtime Dependencies
-----------------------
- python >= 3.9 recommended
- aiogram >= 3.4 (uses the Dispatcher + Router style)
- psutil
- python-dotenv (optional; for .env usage)
- platform (stdlib)
- subprocess (stdlib)
- os (stdlib)
- datetime (stdlib)
- socket (stdlib)
- logging (stdlib)
- shlex (stdlib)
- typing (stdlib)

---
5. Code Overview
----------------
**Project Structure** (single file):
- Config loading helpers
- Auth guard decorator (`admin_only`)
- System information gatherers (CPU, memory, swap, disk, uptime, temp, users, OS info)
- Command execution helpers (sudo-safe wrappers, systemctl management, apt update/upgrade)
- Inline keyboard builders
- Command handlers (`/start`, `/help`, `/status`, `/services`, `/restart`, `/shutdown`, `/update`, `/ip`, `/service <action> <name>`)
- Callback query handlers for confirmation buttons
- Main entrypoint `async def main()` + `if __name__ == "__main__":` runner

---
6. Full Source
--------------
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import socket
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict, Awaitable

import psutil
import platform
import subprocess

# Optional: load .env if present ------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:  # pragma: no cover - optional dependency
    pass

# ----------------------------------------------------------------------------
# Configuration helpers
# ----------------------------------------------------------------------------

DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Fallback to config.py if present ------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
TEMP_SENSORS_COMMAND = os.getenv("TEMP_SENSORS_COMMAND")  # e.g. "sensors -u" or custom script

if Path(__file__).with_name("config.py").exists():
    # Import lazily so environment variables still override.
    import importlib.util
    _spec = importlib.util.spec_from_file_location("bot_config", str(Path(__file__).with_name("config.py")))
    if _spec and _spec.loader:  # pragma: no cover - defensive
        _config = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_config)  # type: ignore
        BOT_TOKEN = BOT_TOKEN or getattr(_config, "BOT_TOKEN", None)
        ADMIN_ID = ADMIN_ID or str(getattr(_config, "ADMIN_ID", ""))
        DEFAULT_LOG_LEVEL = DEFAULT_LOG_LEVEL or getattr(_config, "LOG_LEVEL", "INFO")
        if not TEMP_SENSORS_COMMAND:
            TEMP_SENSORS_COMMAND = getattr(_config, "TEMP_SENSORS_COMMAND", None)

# Validate required config -------------------------------------------------------
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

# ----------------------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------------------

LOG_FILE = os.getenv("BOT_LOG_FILE", "bot.log")
logging.basicConfig(
    level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ],
)
logger = logging.getLogger("linux_admin_bot")

logger.info("Bot starting up...")

# ----------------------------------------------------------------------------
# aiogram imports AFTER config to avoid circular import confusion
# ----------------------------------------------------------------------------
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           BotCommand, BotCommandScopeDefault)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ----------------------------------------------------------------------------
# Global bot / dispatcher
# ----------------------------------------------------------------------------

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()  # We attach all handlers to this router

dp.include_router(router)

# ----------------------------------------------------------------------------
# Utility: admin-only access decorator / guard
# ----------------------------------------------------------------------------

def is_admin(user_id: int | None) -> bool:
    return user_id == ADMIN_ID_INT


def admin_only(func: Callable[[Message, ...], Awaitable[None]]):  # type: ignore[override]
    """Decorator to restrict commands to the configured admin.

    If a non-admin attempts to use a command, they receive a refusal message and the
    action is logged.
    """
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id if message.from_user else None
        if not is_admin(user_id):
            logger.warning("Unauthorized access attempt from user_id=%s username=%s", user_id, message.from_user.username if message.from_user else None)
            await message.answer("❌ Доступ запрещён. Вы не являетесь администратором этого бота.")
            return
        return await func(message, *args, **kwargs)
    return wrapper


async def admin_only_callback(callback: CallbackQuery, *, silent: bool = False) -> bool:
    """Check admin for callback queries.

    Returns True if authorized, False otherwise.
    If not authorized, optionally send message unless silent=True.
    """
    user_id = callback.from_user.id if callback.from_user else None
    if not is_admin(user_id):
        logger.warning("Unauthorized callback attempt from user_id=%s username=%s", user_id, callback.from_user.username if callback.from_user else None)
        if not silent:
            await callback.answer("Доступ запрещён", show_alert=True)
        return False
    return True

# ----------------------------------------------------------------------------
# System Information Helpers
# ----------------------------------------------------------------------------

@dataclass
class CpuLoad:
    percent: float

@dataclass
class MemoryUsage:
    total: int
    used: int
    percent: float

@dataclass
class SwapUsage:
    total: int
    used: int
    percent: float

@dataclass
class DiskUsage:
    mount: str
    total: int
    used: int
    percent: float

@dataclass
class SystemStatus:
    cpu: CpuLoad
    memory: MemoryUsage
    swap: SwapUsage
    disks: List[DiskUsage]
    uptime: timedelta
    cpu_temp_c: Optional[float]
    logged_in_users: List[str]
    os_name: str
    kernel: str


def get_cpu_load(interval: float = 0.5) -> CpuLoad:
    percent = psutil.cpu_percent(interval=interval)
    return CpuLoad(percent=percent)


def get_memory_usage() -> MemoryUsage:
    vm = psutil.virtual_memory()
    return MemoryUsage(total=vm.total, used=vm.total - vm.available, percent=vm.percent)


def get_swap_usage() -> SwapUsage:
    sm = psutil.swap_memory()
    return SwapUsage(total=sm.total, used=sm.used, percent=sm.percent)


def get_disk_usage(all_partitions: bool = False) -> List[DiskUsage]:
    disks: List[DiskUsage] = []
    for part in psutil.disk_partitions(all=all_partitions):
        # Skip pseudo FSs sometimes not accessible
        if part.fstype == '' or part.device.startswith('tmpfs') or part.device.startswith('devtmpfs'):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:  # pragma: no cover - depends on host
            continue
        disks.append(DiskUsage(mount=part.mountpoint, total=usage.total, used=usage.used, percent=usage.percent))
    return disks


def get_uptime() -> timedelta:
    boot_ts = psutil.boot_time()
    return datetime.utcnow() - datetime.utcfromtimestamp(boot_ts)

# --- CPU temperature ----------------------------------------------------------

def _read_temp_via_psutil_sensors() -> Optional[float]:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - some builds lack sensors
        return None
    if not temps:
        return None
    # Prefer 'coretemp' / 'cpu_thermal' / first entry
    preferred_keys = ["coretemp", "cpu_thermal", "k10temp", "acpitz"]
    for key in preferred_keys:
        if key in temps and temps[key]:
            vals = [t.current for t in temps[key] if t.current is not None]
            if vals:
                return sum(vals) / len(vals)
    # fallback: flatten
    flat = []
    for arr in temps.values():
        flat.extend([t.current for t in arr if t.current is not None])
    return sum(flat)/len(flat) if flat else None


def _read_temp_via_sensors_cmd(cmd: str) -> Optional[float]:
    """Parse output of `sensors -u` or custom command; try to locate a temp in Celsius.
    Heuristic parse: look for numbers that look like temperatures in a plausible range -20..150.
    """
    try:
        out = subprocess.check_output(shlex.split(cmd), stderr=subprocess.STDOUT, text=True, timeout=5)
    except Exception as e:  # pragma: no cover - host dependent
        logger.debug("Temp command failed: %s", e)
        return None
    temps: List[float] = []
    for token in out.replace("=", " ").split():
        try:
            val = float(token)
        except ValueError:
            continue
        if -20.0 <= val <= 150.0:  # plausible CPU temp range C
            temps.append(val)
    if temps:
        return sum(temps)/len(temps)
    return None


def get_cpu_temperature() -> Optional[float]:
    # Try psutil first
    temp = _read_temp_via_psutil_sensors()
    if temp is not None:
        return temp
    # Try env-configured command
    if TEMP_SENSORS_COMMAND:
        temp = _read_temp_via_sensors_cmd(TEMP_SENSORS_COMMAND)
        if temp is not None:
            return temp
    # Try common fallback commands
    for cmd in ("sensors -u", "sensors", "cat /sys/class/thermal/thermal_zone0/temp"):
        temp = _read_temp_via_sensors_cmd(cmd)
        if temp is not None:
            # handle millidegree if /sys path
            if cmd.startswith("cat ") and temp > 200:  # e.g., 42000 mC -> 42000
                temp = temp / 1000.0
            return temp
    return None

# --- Logged in users ----------------------------------------------------------

def get_logged_in_users() -> List[str]:
    try:
        users = psutil.users()
    except Exception:  # pragma: no cover - host
        return []
    names = []
    for u in users:
        if u.name not in names:
            names.append(u.name)
    return names

# --- OS Info ------------------------------------------------------------------

def get_os_info() -> Tuple[str, str]:
    os_name = platform.platform(aliased=True, terse=False)
    kernel = platform.release()
    return os_name, kernel

# --- Aggregate ---------------------------------------------------------------

def gather_system_status() -> SystemStatus:
    cpu = get_cpu_load()
    mem = get_memory_usage()
    swap = get_swap_usage()
    disks = get_disk_usage()
    uptime = get_uptime()
    temp = get_cpu_temperature()
    users = get_logged_in_users()
    os_name, kernel = get_os_info()
    return SystemStatus(cpu=cpu, memory=mem, swap=swap, disks=disks, uptime=uptime,
                        cpu_temp_c=temp, logged_in_users=users, os_name=os_name, kernel=kernel)

# ----------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------

def fmt_bytes(num: int, suffix: str = "B") -> str:
    # human readable
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Y{suffix}"


def fmt_timedelta(td: timedelta) -> str:
    secs = int(td.total_seconds())
    days, secs = divmod(secs, 86400)
    hrs, secs = divmod(secs, 3600)
    mins, secs = divmod(secs, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hrs: parts.append(f"{hrs}h")
    if mins: parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return ' '.join(parts)


def render_status_html(status: SystemStatus) -> str:
    lines = []
    now = datetime.now().strftime('%H:%M:%S')
    lines.append(f"<b>📊 Статистика сервера</b>\nВремя: <code>{now}</code>")
    lines.append(f"CPU: <code>{status.cpu.percent:.1f}%</code>")
    lines.append(f"RAM: <code>{fmt_bytes(status.memory.used)}/{fmt_bytes(status.memory.total)} ({status.memory.percent:.1f}%)</code>")
    lines.append(f"Swap: <code>{fmt_bytes(status.swap.used)}/{fmt_bytes(status.swap.total)} ({status.swap.percent:.1f}%)</code>")
    if status.cpu_temp_c is not None:
        lines.append(f"CPU Temp: <code>{status.cpu_temp_c:.1f}°C</code>")
    lines.append(f"Uptime: <code>{fmt_timedelta(status.uptime)}</code>")
    if status.logged_in_users:
        lines.append("Users: " + ", ".join(f"<code>{u}</code>" for u in status.logged_in_users))
    else:
        lines.append("Users: <i>none</i>")
    # disks
    if status.disks:
        lines.append("\n<b>Диски:</b>")
        for d in status.disks:
            lines.append(f"{d.mount}: <code>{fmt_bytes(d.used)}/{fmt_bytes(d.total)} ({d.percent:.1f}%)</code>")
    # os
    lines.append("\n<b>Система:</b>")
    lines.append(f"OS: <code>{status.os_name}</code>")
    lines.append(f"Kernel: <code>{status.kernel}</code>")
    return '\n'.join(lines)

# ----------------------------------------------------------------------------
# Command Execution Helpers (sudo wrappers)
# ----------------------------------------------------------------------------

async def run_command(cmd: str, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a shell command (async) and capture output.

    Returns (returncode, stdout, stderr).
    """
    logger.debug("Executing command: %s", cmd)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"Command timed out after {timeout}s"
    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    logger.debug("Command finished rc=%s", proc.returncode)
    return proc.returncode, stdout, stderr


def sudo_prefix() -> str:
    # Add -n to prevent password prompts from hanging. If password required it will fail quickly.
    return "sudo -n "

async def sudo_reboot() -> Tuple[int, str, str]:
    return await run_command(sudo_prefix() + "reboot")

async def sudo_shutdown_now() -> Tuple[int, str, str]:
    return await run_command(sudo_prefix() + "shutdown -h now")

async def sudo_apt_update_upgrade() -> Tuple[int, str, str]:
    # Using apt-get for scripting reliability
    cmd = sudo_prefix() + "apt-get update && " + sudo_prefix() + "DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"
    return await run_command(cmd)

async def sudo_systemctl(action: str, service: str) -> Tuple[int, str, str]:
    # sanitize service
    safe_service = shlex.quote(service)
    cmd = sudo_prefix() + f"systemctl {action} {safe_service}"
    return await run_command(cmd)

async def list_running_services() -> Tuple[int, str, str]:
    cmd = sudo_prefix() + "systemctl list-units --type=service --state=running --no-pager"
    return await run_command(cmd)

# ----------------------------------------------------------------------------
# Inline Keyboards
# ----------------------------------------------------------------------------

# Callback data schema (simple): ACTION::<optional_arg>
# We'll use short codes to keep callback data under Telegram limits (~64 bytes).

# ACTIONS: CONFIRM_REBOOT, CONFIRM_SHUTDOWN, CONFIRM_UPDATE, REFRESH_STATUS, SHOW_SERVICES, RESTART_SVC::<name>, START_SVC::<name>, STOP_SVC::<name>

from enum import Enum
class CBA(str, Enum):
    CONFIRM_REBOOT = "CRB"
    CONFIRM_SHUTDOWN = "CSD"
    CONFIRM_UPDATE = "CUP"
    REFRESH_STATUS = "RST"
    SHOW_SERVICES = "SRV"
    # dynamic service actions prefixed at runtime

CB_PREFIX_RESTART = "RSVC:"  # + service
CB_PREFIX_START = "SSVC:"
CB_PREFIX_STOP = "XSVC:"


def kb_main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статус", callback_data=CBA.REFRESH_STATUS.value)],
        [InlineKeyboardButton(text="🧰 Сервисы", callback_data=CBA.SHOW_SERVICES.value)],
        [InlineKeyboardButton(text="🔄 Reboot", callback_data=CBA.CONFIRM_REBOOT.value),
         InlineKeyboardButton(text="⏹ Shutdown", callback_data=CBA.CONFIRM_SHUTDOWN.value)],
        [InlineKeyboardButton(text="⬆ Update", callback_data=CBA.CONFIRM_UPDATE.value)],
        [InlineKeyboardButton(text="🌐 IP", callback_data="GET_IP")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_confirm(action_code: str, yes_data: str, no_data: str = "IGNORE") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=yes_data), InlineKeyboardButton(text="❌ Отмена", callback_data=no_data)]
    ])


def kb_services_action(service_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 restart", callback_data=CB_PREFIX_RESTART + service_name)],
        [InlineKeyboardButton(text="▶ start", callback_data=CB_PREFIX_START + service_name),
         InlineKeyboardButton(text="⏸ stop", callback_data=CB_PREFIX_STOP + service_name)],
    ])

# ----------------------------------------------------------------------------
# Command Handlers
# ----------------------------------------------------------------------------

@router.message(Command("start"))
@admin_only
async def cmd_start(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/start from admin")
    await message.answer(
        "👋 Привет! Я бот для удалённого мониторинга и управления сервером. Используй /help для списка команд.",
        reply_markup=kb_main_menu()
    )


@router.message(Command("help"))
@admin_only
async def cmd_help(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/help from admin")
    help_text = textwrap.dedent(
        """
        <b>Доступные команды</b>
        /start - Главное меню
        /help - Эта справка
        /status - Показать статистику сервера
        /services - Показать запущенные сервисы (systemd)
        /restart - Перезагрузка сервера (подтверждение)
        /shutdown - Завершение работы (подтверждение)
        /update - apt update && upgrade (подтверждение)
        /ip - Публичный IP сервера
        /service &lt;action&gt; &lt;name&gt; - Управление сервисом (start|stop|restart). Пример: /service restart nginx
        """
    ).strip()
    await message.answer(help_text, reply_markup=kb_main_menu())


@router.message(Command("status"))
@admin_only
async def cmd_status(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/status from admin")
    status = gather_system_status()
    await message.answer(render_status_html(status), reply_markup=kb_main_menu())


@router.message(Command("services"))
@admin_only
async def cmd_services(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/services from admin")
    rc, out, err = await list_running_services()
    if rc != 0:
        text = f"Не удалось получить список сервисов (rc={rc}).\n<pre>{err or out}</pre>"
    else:
        # Provide a trimmed version; very long outputs can flood chat.
        max_lines = 40
        lines = out.strip().splitlines()
        shown = lines[:max_lines]
        if len(lines) > max_lines:
            shown.append(f"... ({len(lines)-max_lines} строк скрыто)")
        text = "<b>Активные сервисы</b>\n<pre>" + "\n".join(shown) + "</pre>\nВыберите конкретный сервис командой /service ..."
    await message.answer(text, reply_markup=kb_main_menu())


@router.message(Command("restart"))
@admin_only
async def cmd_restart(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/restart from admin")
    await message.answer("Подтвердите перезагрузку сервера.", reply_markup=kb_confirm("reboot", CBA.CONFIRM_REBOOT.value))


@router.message(Command("shutdown"))
@admin_only
async def cmd_shutdown(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/shutdown from admin")
    await message.answer("Подтвердите завершение работы сервера.", reply_markup=kb_confirm("shutdown", CBA.CONFIRM_SHUTDOWN.value))


@router.message(Command("update"))
@admin_only
async def cmd_update(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/update from admin")
    await message.answer("Подтвердите обновление пакетов (apt-get update && upgrade).", reply_markup=kb_confirm("update", CBA.CONFIRM_UPDATE.value))


@router.message(Command("ip"))
@admin_only
async def cmd_ip(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/ip from admin")
    public_ip = await get_public_ip_async()
    if public_ip:
        await message.answer(f"Публичный IP: <code>{public_ip}</code>", reply_markup=kb_main_menu())
    else:
        await message.answer("Не удалось определить публичный IP.", reply_markup=kb_main_menu())


@router.message(Command("service"))
@admin_only
async def cmd_service(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/service from admin args=%s", command.args)
    if not command.args:
        await message.answer("Использование: /service &lt;start|stop|restart&gt; &lt;service_name&gt;", reply_markup=kb_main_menu())
        return
    parts = command.args.strip().split()
    if len(parts) < 2:
        await message.answer("Нужно указать действие и имя сервиса. Пример: /service restart nginx", reply_markup=kb_main_menu())
        return
    action, service = parts[0].lower(), ' '.join(parts[1:])
    if action not in ("start", "stop", "restart", "status"):
        await message.answer("Действие должно быть start|stop|restart|status.", reply_markup=kb_main_menu())
        return
    rc, out, err = await sudo_systemctl(action, service)
    if rc == 0:
        prefix = "✅ Успех"
    else:
        prefix = f"❌ Ошибка rc={rc}"
    txt = f"{prefix} при выполнении systemctl {action} {service}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await message.answer(txt, reply_markup=kb_main_menu())

# ----------------------------------------------------------------------------
# Callback Query Handlers
# ----------------------------------------------------------------------------

@router.callback_query(F.data == CBA.REFRESH_STATUS.value)
async def cb_refresh_status(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    status = gather_system_status()
    await callback.message.edit_text(render_status_html(status), reply_markup=kb_main_menu())  # type: ignore[arg-type]
    await callback.answer()


@router.callback_query(F.data == CBA.SHOW_SERVICES.value)
async def cb_show_services(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    rc, out, err = await list_running_services()
    if rc != 0:
        text = f"Не удалось получить список сервисов (rc={rc}).\n<pre>{err or out}</pre>"
    else:
        max_lines = 40
        lines = out.strip().splitlines()
        shown = lines[:max_lines]
        if len(lines) > max_lines:
            shown.append(f"... ({len(lines)-max_lines} строк скрыто)")
        text = "<b>Активные сервисы</b>\n<pre>" + "\n".join(shown) + "</pre>\nИспользуйте /service ..."
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())  # type: ignore[arg-type]
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data == CBA.CONFIRM_REBOOT.value)
async def cb_confirm_reboot(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    await callback.answer("Перезагрузка...", show_alert=False)
    logger.warning("Admin confirmed reboot via inline button")
    rc, out, err = await sudo_reboot()
    # Usually system will reboot before message is delivered, but try.
    try:
        await callback.message.answer(f"Команда reboot отправлена (rc={rc}).")
    except Exception:  # pragma: no cover - system may be down
        pass


@router.callback_query(F.data == CBA.CONFIRM_SHUTDOWN.value)
async def cb_confirm_shutdown(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    await callback.answer("Завершение работы...", show_alert=False)
    logger.warning("Admin confirmed shutdown via inline button")
    rc, out, err = await sudo_shutdown_now()
    try:
        await callback.message.answer(f"Команда shutdown отправлена (rc={rc}).")
    except Exception:  # pragma: no cover
        pass


@router.callback_query(F.data == CBA.CONFIRM_UPDATE.value)
async def cb_confirm_update(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    await callback.answer("Обновление пакетов...", show_alert=False)
    logger.warning("Admin confirmed apt update/upgrade via inline button")
    rc, out, err = await sudo_apt_update_upgrade()
    txt = f"apt update/upgrade завершено rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    try:
        await callback.message.answer(txt, reply_markup=kb_main_menu())
    except Exception:
        pass


# Dynamic service action callbacks --------------------------------------------
@router.callback_query(F.data.startswith(CB_PREFIX_RESTART))
async def cb_restart_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_RESTART):]
    logger.info("Restart service via button: %s", service)
    rc, out, err = await sudo_systemctl("restart", service)
    txt = f"systemctl restart {service} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await callback.message.answer(txt, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PREFIX_START))
async def cb_start_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_START):]
    logger.info("Start service via button: %s", service)
    rc, out, err = await sudo_systemctl("start", service)
    txt = f"systemctl start {service} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await callback.message.answer(txt, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PREFIX_STOP))
async def cb_stop_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_STOP):]
    logger.info("Stop service via button: %s", service)
    rc, out, err = await sudo_systemctl("stop", service)
    txt = f"systemctl stop {service} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await callback.message.answer(txt, reply_markup=kb_main_menu())
    await callback.answer()

# ----------------------------------------------------------------------------
# Public IP helper
# ----------------------------------------------------------------------------

async def get_public_ip_async() -> Optional[str]:
    """Try to discover public IP.
    Strategy: attempt DNS to resolver opendns/ifconfig.me; fallback to external commands.
    Because we avoid external HTTP libs in this minimal script, we'll try simple shell curls if available.
    """
    # lightweight attempt: dig +short myip.opendns.com @resolver1.opendns.com
    # This may fail if dig isn't installed.
    for cmd in (
        "dig +short myip.opendns.com @resolver1.opendns.com",
        "curl -s ifconfig.me",
        "curl -s https://api.ipify.org",
    ):
        rc, out, err = await run_command(cmd, timeout=10)
        if rc == 0 and out.strip():
            ip = out.strip().split()[0]
            # quick sanity
            if len(ip) <= 64:  # IPv4/6
                return ip
    # fallback: try to guess outward interface
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return ip
    except Exception:  # pragma: no cover - environment dependent
        return None

@router.callback_query(F.data == "GET_IP")
async def cb_get_ip(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    public_ip = await get_public_ip_async()
    if public_ip:
        await callback.message.answer(f"Публичный IP: <code>{public_ip}</code>", reply_markup=kb_main_menu())
    else:
        await callback.message.answer("Не удалось определить публичный IP.", reply_markup=kb_main_menu())
    await callback.answer()  # Закрыть спиннер

# ----------------------------------------------------------------------------
# Bot command list (for Telegram client UI)
# ----------------------------------------------------------------------------

async def set_bot_commands() -> None:
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="status", description="Статистика сервера"),
        BotCommand(command="services", description="Запущенные сервисы"),
        BotCommand(command="restart", description="Перезагрузка сервера"),
        BotCommand(command="shutdown", description="Выключение сервера"),
        BotCommand(command="update", description="Обновление пакетов"),
        BotCommand(command="ip", description="Публичный IP"),
        BotCommand(command="service", description="Управление сервисом"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())

# ----------------------------------------------------------------------------
# Startup / polling
# ----------------------------------------------------------------------------

async def main() -> None:  # pragma: no cover - runtime
    await set_bot_commands()
    # Уведомление админу о запуске
    try:
        await bot.send_message(ADMIN_ID_INT, "✅ Сервер запущен и бот активен.")
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение админу при запуске: {e}")
    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":  # pragma: no cover - runtime
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
