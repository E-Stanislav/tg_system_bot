#!/usr/bin/env python3
"""
Keyboards module for Telegram Remote Monitoring & Management Bot
"""

from enum import Enum
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ----------------------------------------------------------------------------
# Callback data schema
# ----------------------------------------------------------------------------

class CBA(str, Enum):
    ASK_REBOOT = "ARB"
    ASK_SHUTDOWN = "ASD"
    ASK_UPDATE = "AUP"
    CONFIRM_REBOOT = "CRB"
    CONFIRM_SHUTDOWN = "CSD"
    CONFIRM_UPDATE = "CUP"
    REFRESH_STATUS = "RST"
    SHOW_SERVICES = "SRV"
    SHOW_PROCESSES = "PRC"
    SHOW_DOCKER = "DOC"
    SHOW_NETWORK = "NET"
    SHOW_TEMPERATURE = "TEMP"
    SHOW_TEMPERATURE_LIVE = "TEMP_LIVE"
    OUTLINE_AUDIT = "OUTLINE_AUDIT"
    SHELL_CTRL_C = "SHELL_CTRL_C"
    SHELL_STOP = "SHELL_STOP"

# Dynamic service actions prefixed at runtime
CB_PREFIX_RESTART = "RSVC:"  # + service
CB_PREFIX_START = "SSVC:"
CB_PREFIX_STOP = "XSVC:"

# Docker prefixes
CB_PREFIX_DOCKER_START = "DSTART:"
CB_PREFIX_DOCKER_STOP = "DSTOP:"
CB_PREFIX_DOCKER_RESTART = "DRESTART:"

# ----------------------------------------------------------------------------
# Keyboard builders
# ----------------------------------------------------------------------------

def kb_main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статус", callback_data=CBA.REFRESH_STATUS.value)],
        [InlineKeyboardButton(text="🧰 Сервисы", callback_data=CBA.SHOW_SERVICES.value),
         InlineKeyboardButton(text="📈 Процессы", callback_data=CBA.SHOW_PROCESSES.value)],
        [InlineKeyboardButton(text="🐳 Docker", callback_data=CBA.SHOW_DOCKER.value),
         InlineKeyboardButton(text="🌐 Сеть", callback_data=CBA.SHOW_NETWORK.value)],
        [InlineKeyboardButton(text="🌡 Температура", callback_data=CBA.SHOW_TEMPERATURE.value),
         InlineKeyboardButton(text="🌡 Live", callback_data=CBA.SHOW_TEMPERATURE_LIVE.value)],
        # [InlineKeyboardButton(text="🛡 Outline Audit", callback_data=CBA.OUTLINE_AUDIT.value)],
        [InlineKeyboardButton(text="🔄 Reboot", callback_data=CBA.ASK_REBOOT.value),
         InlineKeyboardButton(text="⏹ Shutdown", callback_data=CBA.ASK_SHUTDOWN.value)],
        [InlineKeyboardButton(text="⬆ Update", callback_data=CBA.ASK_UPDATE.value)],
        [InlineKeyboardButton(text="🌐 IP", callback_data="GET_IP")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_confirm(action_code: str, yes_data: str, no_data: str = "IGNORE") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=yes_data), 
         InlineKeyboardButton(text="❌ Отмена", callback_data=no_data)]
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

def kb_shell_session() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ctrl+C", callback_data=CBA.SHELL_CTRL_C.value),
         InlineKeyboardButton(text="⏹ Завершить", callback_data=CBA.SHELL_STOP.value)],
    ])