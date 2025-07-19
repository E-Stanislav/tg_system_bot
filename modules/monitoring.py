#!/usr/bin/env python3
"""
Background monitoring module for Telegram Remote Monitoring & Management Bot
"""

import asyncio
import logging
import shlex
from typing import Set

from aiogram import Bot

from core.config import (
    ADMIN_ID_INT, ALERT_CPU_THRESHOLD, ALERT_RAM_THRESHOLD, 
    ALERT_DISK_THRESHOLD, ALERT_SERVICES, ALERT_DOCKER_CONTAINERS,
    STATUS_SCHEDULE_SECONDS
)
from modules.system_monitor import (
    gather_system_status, get_top_processes, get_docker_info,
    run_command
)
from modules.formatters import render_status_html
from modules.keyboards import kb_main_menu

logger = logging.getLogger("monitoring")

# ----------------------------------------------------------------------------
# Background monitoring and alerting
# ----------------------------------------------------------------------------

async def background_monitoring(bot: Bot):
    """Фоновый мониторинг системы с отправкой уведомлений"""
    last_alerts = {"cpu": False, "ram": False, "disk": set(), "service": set()}
    
    while True:
        try:
            status = gather_system_status()
            
            # CPU alerts
            if status.cpu.percent > ALERT_CPU_THRESHOLD:
                if not last_alerts["cpu"]:
                    await bot.send_message(
                        ADMIN_ID_INT, 
                        f"⚠️ Высокая загрузка CPU: <b>{status.cpu.percent:.1f}%</b>"
                    )
                    last_alerts["cpu"] = True
            else:
                last_alerts["cpu"] = False
            
            # RAM alerts
            if status.memory.percent > ALERT_RAM_THRESHOLD:
                if not last_alerts["ram"]:
                    await bot.send_message(
                        ADMIN_ID_INT, 
                        f"⚠️ Высокое использование RAM: <b>{status.memory.percent:.1f}%</b>"
                    )
                    last_alerts["ram"] = True
            else:
                last_alerts["ram"] = False
            
            # Disk alerts
            for d in status.disks:
                free_percent = 100.0 - d.percent
                if free_percent < ALERT_DISK_THRESHOLD:
                    if d.mount not in last_alerts["disk"]:
                        from formatters import fmt_bytes
                        await bot.send_message(
                            ADMIN_ID_INT, 
                            f"⚠️ Мало места на диске <b>{d.mount}</b>: "
                            f"<b>{fmt_bytes(d.used)}/{fmt_bytes(d.total)}</b> ({free_percent:.1f}% свободно)"
                        )
                        last_alerts["disk"].add(d.mount)
                else:
                    last_alerts["disk"].discard(d.mount)
            
            # Service alerts
            for svc in ALERT_SERVICES:
                rc, out, err = await run_command(f"systemctl is-active {shlex.quote(svc)}")
                if rc != 0 or "inactive" in out or "failed" in out:
                    if svc not in last_alerts["service"]:
                        await bot.send_message(
                            ADMIN_ID_INT, 
                            f"❗️ Важный сервис <b>{svc}</b> не работает!"
                        )
                        last_alerts["service"].add(svc)
                else:
                    last_alerts["service"].discard(svc)
            
            # Docker container alerts
            docker_info = await get_docker_info()
            if docker_info.containers_total > 0:
                for container_name in ALERT_DOCKER_CONTAINERS:
                    container_found = False
                    for container in docker_info.containers:
                        if container['name'] == container_name:
                            container_found = True
                            if 'Up' not in container['status']:
                                if container_name not in last_alerts["service"]:
                                    await bot.send_message(
                                        ADMIN_ID_INT, 
                                        f"❗️ Важный Docker контейнер <b>{container_name}</b> не работает!"
                                    )
                                    last_alerts["service"].add(container_name)
                            else:
                                last_alerts["service"].discard(container_name)
                            break
                    if not container_found:
                        if container_name not in last_alerts["service"]:
                            await bot.send_message(
                                ADMIN_ID_INT, 
                                f"❗️ Важный Docker контейнер <b>{container_name}</b> не найден!"
                            )
                            last_alerts["service"].add(container_name)
                            
        except Exception as e:
            logger.warning(f"Ошибка в background_monitoring: {e}")
        
        await asyncio.sleep(60)  # Проверять каждую минуту

# ----------------------------------------------------------------------------
# Scheduled status reports
# ----------------------------------------------------------------------------

async def scheduled_status(bot: Bot):
    """Отправка регулярных отчетов о состоянии системы"""
    
    while True:
        try:
            status = gather_system_status()
            await bot.send_message(
                ADMIN_ID_INT, 
                render_status_html(status), 
                reply_markup=kb_main_menu()
            )
        except Exception as e:
            logger.warning(f"Ошибка в scheduled_status: {e}")
        
        await asyncio.sleep(STATUS_SCHEDULE_SECONDS) 