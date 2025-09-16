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
    STATUS_SCHEDULE_SECONDS,
    ALERT_TEMP_THRESHOLD,
    TEMP_MONITOR_INTERVAL_SECONDS,
    TEMP_ALERT_HYSTERESIS,
)
from modules.system_monitor import (
    gather_system_status, get_top_processes, get_docker_info,
    run_command,
    get_thermal_zone_temperatures,
)
from modules.formatters import fmt_bytes, render_status_html
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
                    # Получить топ-5 процессов по CPU
                    top_processes = get_top_processes(limit=5)
                    proc_lines = [
                        f"<b>{p.name}</b> (PID: {p.pid}) — {p.cpu_percent:.1f}% CPU"
                        for p in top_processes if p.cpu_percent > 0.1
                    ] if top_processes else []
                    msg = f"⚠️ Высокая загрузка CPU: <b>{status.cpu.percent:.1f}%</b>"
                    if proc_lines:
                        msg += "\n\nТоп процессов по CPU:\n" + "\n".join(proc_lines)
                    else:
                        msg += "\n\nНет активных процессов с высокой загрузкой CPU."
                    await bot.send_message(
                        ADMIN_ID_INT,
                        msg
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
# Background temperature overheat alerts
# ----------------------------------------------------------------------------

async def background_temperature_alerts(bot: Bot):
    """Проверяет температуры по компонентам и шлет алерты при перегреве.

    - Порог: ALERT_TEMP_THRESHOLD (°C)
    - Интервал: TEMP_MONITOR_INTERVAL_SECONDS
    - Гистерезис: TEMP_ALERT_HYSTERESIS — чтобы не спамить при колебаниях
    """
    logger.info(
        "Запуск температурного мониторинга: порог=%.1f°C, интервал=%ss, гистерезис=%.1f°C",
        ALERT_TEMP_THRESHOLD, TEMP_MONITOR_INTERVAL_SECONDS, TEMP_ALERT_HYSTERESIS,
    )

    overheated_now: Set[str] = set()  # компоненты, по которым уже отправлен алерт

    while True:
        try:
            temps = get_thermal_zone_temperatures()
            if not temps:
                # Нечего мониторить на этой системе — спим дольше
                await asyncio.sleep(TEMP_MONITOR_INTERVAL_SECONDS)
                continue

            for component_name, temp_c in temps.items():
                if temp_c >= ALERT_TEMP_THRESHOLD:
                    if component_name not in overheated_now:
                        try:
                            await bot.send_message(
                                ADMIN_ID_INT,
                                (
                                    f"🔥 Перегрев компонента <b>{component_name}</b>: "
                                    f"<b>{temp_c:.1f}°C</b> (порог {ALERT_TEMP_THRESHOLD:.1f}°C)"
                                ),
                            )
                            logger.info(
                                "Температурный алерт: %s=%.1f°C (порог=%.1f°C)",
                                component_name, temp_c, ALERT_TEMP_THRESHOLD,
                            )
                        except Exception as e:
                            logger.warning("Не удалось отправить алерт о температуре: %s", e)
                        overheated_now.add(component_name)
                else:
                    # Сброс алерта, когда температура опустится ниже порога - гистерезис
                    if component_name in overheated_now and temp_c <= ALERT_TEMP_THRESHOLD - TEMP_ALERT_HYSTERESIS:
                        overheated_now.discard(component_name)
                        try:
                            await bot.send_message(
                                ADMIN_ID_INT,
                                (
                                    f"✅ Температура <b>{component_name}</b> вернулась в норму: "
                                    f"<b>{temp_c:.1f}°C</b>"
                                ),
                            )
                            logger.info(
                                "Температура нормализована: %s=%.1f°C (порог=%.1f°C, гистерезис=%.1f°C)",
                                component_name, temp_c, ALERT_TEMP_THRESHOLD, TEMP_ALERT_HYSTERESIS,
                            )
                        except Exception as e:
                            logger.warning("Не удалось отправить сообщение о нормализации температуры: %s", e)

        except Exception as e:
            logger.warning(f"Ошибка в background_temperature_alerts: {e}")

        await asyncio.sleep(TEMP_MONITOR_INTERVAL_SECONDS)

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