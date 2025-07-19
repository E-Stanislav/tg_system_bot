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

@dataclass
class NetworkInfo:
    connections_count: int
    listening_ports: List[int]
    bandwidth_rx: Optional[float]  # MB/s
    bandwidth_tx: Optional[float]  # MB/s
    interface_stats: Dict[str, Dict[str, int]]

def get_network_info() -> NetworkInfo:
    """Получить информацию о сети"""
    try:
        # Активные соединения
        connections = psutil.net_connections()
        connections_count = len(connections)
        
        # Прослушиваемые порты
        listening_ports = []
        for conn in connections:
            if conn.status == 'LISTEN' and conn.laddr.port not in listening_ports:
                listening_ports.append(conn.laddr.port)
        
        # Статистика интерфейсов
        interface_stats = {}
        net_io = psutil.net_io_counters(pernic=True)
        for interface, stats in net_io.items():
            interface_stats[interface] = {
                'bytes_sent': stats.bytes_sent,
                'bytes_recv': stats.bytes_recv,
                'packets_sent': stats.packets_sent,
                'packets_recv': stats.packets_recv
            }
        
        return NetworkInfo(
            connections_count=connections_count,
            listening_ports=sorted(listening_ports),
            bandwidth_rx=None,  # TODO: implement bandwidth calculation
            bandwidth_tx=None,
            interface_stats=interface_stats
        )
    except Exception as e:
        logger.warning(f"Ошибка получения сетевой информации: {e}")
        return NetworkInfo(0, [], None, None, {})

# --- Process and Docker monitoring --------------------------------------------

@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_rss: int
    status: str

@dataclass
class DockerInfo:
    containers_running: int
    containers_total: int
    containers: List[Dict[str, str]]

def get_top_processes(limit: int = 10) -> List[ProcessInfo]:
    """Получить топ процессов по использованию ресурсов"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status']):
            try:
                info = proc.info
                processes.append(ProcessInfo(
                    pid=info['pid'],
                    name=info['name'],
                    cpu_percent=info['cpu_percent'],
                    memory_percent=info['memory_percent'],
                    memory_rss=info['memory_info'].rss,
                    status=info['status']
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Сортировка по CPU, затем по памяти
        processes.sort(key=lambda x: (x.cpu_percent, x.memory_percent), reverse=True)
        return processes[:limit]
    except Exception as e:
        logger.warning(f"Ошибка получения процессов: {e}")
        return []

async def get_docker_info() -> DockerInfo:
    """Получить информацию о Docker контейнерах"""
    try:
        # Проверяем, установлен ли Docker
        rc, out, err = await run_command("which docker", timeout=5)
        if rc != 0:
            return DockerInfo(0, 0, [])
        
        # Получаем список контейнеров
        rc, out, err = await run_command("docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'", timeout=10)
        if rc != 0:
            return DockerInfo(0, 0, [])
        
        containers = []
        lines = out.strip().splitlines()
        if len(lines) > 1:  # Пропускаем заголовок
            for line in lines[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    containers.append({
                        'name': parts[0],
                        'status': parts[1],
                        'ports': parts[2],
                        'image': parts[3]
                    })
        
        running = sum(1 for c in containers if 'Up' in c['status'])
        
        return DockerInfo(
            containers_running=running,
            containers_total=len(containers),
            containers=containers
        )
    except Exception as e:
        logger.warning(f"Ошибка получения Docker информации: {e}")
        return DockerInfo(0, 0, [])

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

async def docker_action(action: str, container: str) -> Tuple[int, str, str]:
    """Выполнить действие с Docker контейнером"""
    safe_container = shlex.quote(container)
    cmd = f"docker {action} {safe_container}"
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
    SHOW_PROCESSES = "PRC"
    SHOW_DOCKER = "DOC"
    SHOW_NETWORK = "NET"
    # dynamic service actions prefixed at runtime

CB_PREFIX_RESTART = "RSVC:"  # + service
CB_PREFIX_START = "SSVC:"
CB_PREFIX_STOP = "XSVC:"
# Docker prefixes
CB_PREFIX_DOCKER_START = "DSTART:"
CB_PREFIX_DOCKER_STOP = "DSTOP:"
CB_PREFIX_DOCKER_RESTART = "DRESTART:"


def kb_main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статус", callback_data=CBA.REFRESH_STATUS.value)],
        [InlineKeyboardButton(text="🧰 Сервисы", callback_data=CBA.SHOW_SERVICES.value),
         InlineKeyboardButton(text="📈 Процессы", callback_data=CBA.SHOW_PROCESSES.value)],
        [InlineKeyboardButton(text="🐳 Docker", callback_data=CBA.SHOW_DOCKER.value),
         InlineKeyboardButton(text="🌐 Сеть", callback_data=CBA.SHOW_NETWORK.value)],
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


def kb_docker_action(container_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 restart", callback_data=CB_PREFIX_DOCKER_RESTART + container_name)],
        [InlineKeyboardButton(text="▶ start", callback_data=CB_PREFIX_DOCKER_START + container_name),
         InlineKeyboardButton(text="⏸ stop", callback_data=CB_PREFIX_DOCKER_STOP + container_name)],
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
        /processes - Топ процессов по использованию ресурсов
        /docker - Информация о Docker контейнерах
        /network - Сетевая информация и активные соединения
        /restart - Перезагрузка сервера (подтверждение)
        /shutdown - Завершение работы (подтверждение)
        /update - apt update && upgrade (подтверждение)
        /ip - Публичный IP сервера
        /service &lt;action&gt; &lt;name&gt; - Управление сервисом (start|stop|restart). Пример: /service restart nginx
        /dockerctl &lt;action&gt; &lt;container&gt; - Управление Docker (start|stop|restart|logs). Пример: /dockerctl restart nginx
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


@router.message(Command("processes"))
@admin_only
async def cmd_processes(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/processes from admin")
    processes = get_top_processes(15)
    if not processes:
        await message.answer("Не удалось получить информацию о процессах.", reply_markup=kb_main_menu())
        return
    
    lines = ["<b>📈 Топ процессов по использованию ресурсов:</b>"]
    for i, proc in enumerate(processes, 1):
        lines.append(f"{i}. <b>{proc.name}</b> (PID: {proc.pid})")
        lines.append(f"   CPU: <code>{proc.cpu_percent:.1f}%</code> | RAM: <code>{proc.memory_percent:.1f}%</code> | Статус: <code>{proc.status}</code>")
    
    await message.answer('\n'.join(lines), reply_markup=kb_main_menu())


@router.message(Command("docker"))
@admin_only
async def cmd_docker(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/docker from admin")
    docker_info = await get_docker_info()
    
    if docker_info.containers_total == 0:
        await message.answer("Docker не установлен или нет контейнеров.", reply_markup=kb_main_menu())
        return
    
    lines = [f"<b>🐳 Docker контейнеры:</b>"]
    lines.append(f"Запущено: <code>{docker_info.containers_running}/{docker_info.containers_total}</code>")
    
    if docker_info.containers:
        lines.append("\n<b>Контейнеры:</b>")
        for container in docker_info.containers:
            status_icon = "🟢" if "Up" in container['status'] else "🔴"
            lines.append(f"{status_icon} <b>{container['name']}</b>")
            lines.append(f"   Статус: <code>{container['status']}</code>")
            lines.append(f"   Образ: <code>{container['image']}</code>")
            if container['ports']:
                lines.append(f"   Порты: <code>{container['ports']}</code>")
            lines.append("")
    
    await message.answer('\n'.join(lines), reply_markup=kb_main_menu())


@router.message(Command("network"))
@admin_only
async def cmd_network(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/network from admin")
    network_info = get_network_info()
    
    lines = ["<b>🌐 Сетевая информация:</b>"]
    lines.append(f"Активные соединения: <code>{network_info.connections_count}</code>")
    
    if network_info.listening_ports:
        lines.append(f"Прослушиваемые порты: <code>{', '.join(map(str, network_info.listening_ports[:20]))}</code>")
        if len(network_info.listening_ports) > 20:
            lines.append(f"... и еще {len(network_info.listening_ports) - 20} портов")
    
    if network_info.interface_stats:
        lines.append("\n<b>Интерфейсы:</b>")
        for interface, stats in network_info.interface_stats.items():
            lines.append(f"<b>{interface}:</b>")
            lines.append(f"   Отправлено: <code>{fmt_bytes(stats['bytes_sent'])}</code>")
            lines.append(f"   Получено: <code>{fmt_bytes(stats['bytes_recv'])}</code>")
    
    await message.answer('\n'.join(lines), reply_markup=kb_main_menu())


@router.message(Command("dockerctl"))
@admin_only
async def cmd_dockerctl(message: Message, command: CommandObject, **kwargs):  # type: ignore[override]
    logger.info("/dockerctl from admin args=%s", command.args)
    if not command.args:
        await message.answer("Использование: /dockerctl &lt;start|stop|restart&gt; &lt;container_name&gt;", reply_markup=kb_main_menu())
        return
    parts = command.args.strip().split()
    if len(parts) < 2:
        await message.answer("Нужно указать действие и имя контейнера. Пример: /dockerctl restart nginx", reply_markup=kb_main_menu())
        return
    action, container = parts[0].lower(), ' '.join(parts[1:])
    if action not in ("start", "stop", "restart", "logs"):
        await message.answer("Действие должно быть start|stop|restart|logs.", reply_markup=kb_main_menu())
        return
    
    if action == "logs":
        # Для логов используем docker logs
        rc, out, err = await run_command(f"docker logs --tail 50 {shlex.quote(container)}")
        if rc == 0:
            text = f"<b>📋 Логи контейнера {container}:</b>\n<pre>{out.strip()[:4000]}</pre>"
        else:
            text = f"❌ Ошибка получения логов (rc={rc}).\n<pre>{err.strip()[:4000]}</pre>"
    else:
        rc, out, err = await docker_action(action, container)
        if rc == 0:
            prefix = "✅ Успех"
        else:
            prefix = f"❌ Ошибка rc={rc}"
        text = f"{prefix} при выполнении docker {action} {container}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    
    await message.answer(text, reply_markup=kb_main_menu())

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


@router.callback_query(F.data == CBA.SHOW_PROCESSES.value)
async def cb_show_processes(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    processes = get_top_processes(15)
    if not processes:
        text = "Не удалось получить информацию о процессах."
    else:
        lines = ["<b>📈 Топ процессов по использованию ресурсов:</b>"]
        for i, proc in enumerate(processes, 1):
            lines.append(f"{i}. <b>{proc.name}</b> (PID: {proc.pid})")
            lines.append(f"   CPU: <code>{proc.cpu_percent:.1f}%</code> | RAM: <code>{proc.memory_percent:.1f}%</code> | Статус: <code>{proc.status}</code>")
        text = '\n'.join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())  # type: ignore[arg-type]
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data == CBA.SHOW_DOCKER.value)
async def cb_show_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    docker_info = await get_docker_info()
    
    if docker_info.containers_total == 0:
        text = "Docker не установлен или нет контейнеров."
    else:
        lines = [f"<b>🐳 Docker контейнеры:</b>"]
        lines.append(f"Запущено: <code>{docker_info.containers_running}/{docker_info.containers_total}</code>")
        
        if docker_info.containers:
            lines.append("\n<b>Контейнеры:</b>")
            for container in docker_info.containers:
                status_icon = "🟢" if "Up" in container['status'] else "🔴"
                lines.append(f"{status_icon} <b>{container['name']}</b>")
                lines.append(f"   Статус: <code>{container['status']}</code>")
                lines.append(f"   Образ: <code>{container['image']}</code>")
                if container['ports']:
                    lines.append(f"   Порты: <code>{container['ports']}</code>")
                lines.append("")
        text = '\n'.join(lines)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())  # type: ignore[arg-type]
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data == CBA.SHOW_NETWORK.value)
async def cb_show_network(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    network_info = get_network_info()
    
    lines = ["<b>🌐 Сетевая информация:</b>"]
    lines.append(f"Активные соединения: <code>{network_info.connections_count}</code>")
    
    if network_info.listening_ports:
        lines.append(f"Прослушиваемые порты: <code>{', '.join(map(str, network_info.listening_ports[:20]))}</code>")
        if len(network_info.listening_ports) > 20:
            lines.append(f"... и еще {len(network_info.listening_ports) - 20} портов")
    
    if network_info.interface_stats:
        lines.append("\n<b>Интерфейсы:</b>")
        for interface, stats in network_info.interface_stats.items():
            lines.append(f"<b>{interface}:</b>")
            lines.append(f"   Отправлено: <code>{fmt_bytes(stats['bytes_sent'])}</code>")
            lines.append(f"   Получено: <code>{fmt_bytes(stats['bytes_recv'])}</code>")
    
    text = '\n'.join(lines)
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


# Docker action callbacks
@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_RESTART))
async def cb_restart_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_RESTART):]
    logger.info("Restart docker container via button: %s", container)
    rc, out, err = await docker_action("restart", container)
    txt = f"docker restart {container} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await callback.message.answer(txt, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_START))
async def cb_start_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_START):]
    logger.info("Start docker container via button: %s", container)
    rc, out, err = await docker_action("start", container)
    txt = f"docker start {container} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
    await callback.message.answer(txt, reply_markup=kb_main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_STOP))
async def cb_stop_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_STOP):]
    logger.info("Stop docker container via button: %s", container)
    rc, out, err = await docker_action("stop", container)
    txt = f"docker stop {container} rc={rc}.\n<pre>{(out or err).strip()[:4000]}</pre>"
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
        BotCommand(command="processes", description="Топ процессов"),
        BotCommand(command="docker", description="Docker контейнеры"),
        BotCommand(command="network", description="Сетевая информация"),
        BotCommand(command="restart", description="Перезагрузка сервера"),
        BotCommand(command="shutdown", description="Выключение сервера"),
        BotCommand(command="update", description="Обновление пакетов"),
        BotCommand(command="ip", description="Публичный IP"),
        BotCommand(command="service", description="Управление сервисом"),
        BotCommand(command="dockerctl", description="Управление Docker"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())

# ----------------------------------------------------------------------------
# Background monitoring and alerting
# ----------------------------------------------------------------------------

ALERT_CPU_THRESHOLD = 90.0  # %
ALERT_RAM_THRESHOLD = 90.0  # %
ALERT_DISK_THRESHOLD = 10.0  # % свободного места
ALERT_SERVICES = ["nginx", "postgresql", "mysql", "docker"]  # важные сервисы, можно расширить
ALERT_DOCKER_CONTAINERS = ["nginx", "postgres", "mysql", "redis"]  # важные контейнеры
STATUS_SCHEDULE_SECONDS = 24 * 60 * 60  # раз в сутки

async def background_monitoring():
    last_alerts = {"cpu": False, "ram": False, "disk": set(), "service": set()}
    while True:
        try:
            status = gather_system_status()
            # CPU
            if status.cpu.percent > ALERT_CPU_THRESHOLD:
                if not last_alerts["cpu"]:
                    await bot.send_message(ADMIN_ID_INT, f"⚠️ Высокая загрузка CPU: <b>{status.cpu.percent:.1f}%</b>")
                    last_alerts["cpu"] = True
            else:
                last_alerts["cpu"] = False
            # RAM
            if status.memory.percent > ALERT_RAM_THRESHOLD:
                if not last_alerts["ram"]:
                    await bot.send_message(ADMIN_ID_INT, f"⚠️ Высокое использование RAM: <b>{status.memory.percent:.1f}%</b>")
                    last_alerts["ram"] = True
            else:
                last_alerts["ram"] = False
            # Диски
            for d in status.disks:
                free_percent = 100.0 - d.percent
                if free_percent < ALERT_DISK_THRESHOLD:
                    if d.mount not in last_alerts["disk"]:
                        await bot.send_message(ADMIN_ID_INT, f"⚠️ Мало места на диске <b>{d.mount}</b>: <b>{fmt_bytes(d.used)}/{fmt_bytes(d.total)}</b> ({free_percent:.1f}% свободно)")
                        last_alerts["disk"].add(d.mount)
                else:
                    last_alerts["disk"].discard(d.mount)
            # Важные сервисы
            for svc in ALERT_SERVICES:
                rc, out, err = await run_command(f"systemctl is-active {shlex.quote(svc)}")
                if rc != 0 or "inactive" in out or "failed" in out:
                    if svc not in last_alerts["service"]:
                        await bot.send_message(ADMIN_ID_INT, f"❗️ Важный сервис <b>{svc}</b> не работает!")
                        last_alerts["service"].add(svc)
                else:
                    last_alerts["service"].discard(svc)
            
            # Docker контейнеры
            docker_info = await get_docker_info()
            if docker_info.containers_total > 0:
                for container_name in ALERT_DOCKER_CONTAINERS:
                    container_found = False
                    for container in docker_info.containers:
                        if container['name'] == container_name:
                            container_found = True
                            if 'Up' not in container['status']:
                                if container_name not in last_alerts["service"]:
                                    await bot.send_message(ADMIN_ID_INT, f"❗️ Важный Docker контейнер <b>{container_name}</b> не работает!")
                                    last_alerts["service"].add(container_name)
                            else:
                                last_alerts["service"].discard(container_name)
                            break
                    if not container_found:
                        if container_name not in last_alerts["service"]:
                            await bot.send_message(ADMIN_ID_INT, f"❗️ Важный Docker контейнер <b>{container_name}</b> не найден!")
                            last_alerts["service"].add(container_name)
        except Exception as e:
            logger.warning(f"Ошибка в background_monitoring: {e}")
        await asyncio.sleep(60)  # Проверять каждую минуту

# ----------------------------------------------------------------------------
# Status scheduler (раз в сутки)
# ----------------------------------------------------------------------------

async def scheduled_status():
    while True:
        try:
            status = gather_system_status()
            await bot.send_message(ADMIN_ID_INT, render_status_html(status), reply_markup=kb_main_menu())
        except Exception as e:
            logger.warning(f"Ошибка в scheduled_status: {e}")
        await asyncio.sleep(STATUS_SCHEDULE_SECONDS)

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
    # Start background monitoring and scheduler
    asyncio.create_task(background_monitoring())
    asyncio.create_task(scheduled_status())
    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":  # pragma: no cover - runtime
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
