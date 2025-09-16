#!/usr/bin/env python3
"""
Telegram Remote Monitoring & Management Bot
===========================================

Main bot file that handles Telegram commands and callbacks.
Uses modular architecture with separate modules for different functionalities.
"""

import asyncio
import logging
import shlex
import sys
from typing import Optional, Dict
import json
import tempfile

# Import configuration first
from core.config import (
    BOT_TOKEN, ADMIN_ID_INT, DEFAULT_LOG_LEVEL, LOG_FILE
)

# Setup logging
logging.basicConfig(
    level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ],
)
logger = logging.getLogger("linux_admin_bot")

# Live temperature sessions per chat
# chat_id -> asyncio.Task running updater
live_temp_sessions: Dict[int, asyncio.Task] = {}
# chat_id -> message_id of the live message
live_temp_message_ids: Dict[int, int] = {}

logger.info("Bot starting up...")

# Import aiogram components
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, BotCommand, BotCommandScopeDefault
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Import our modules
from modules.auth import admin_only, admin_only_callback
from modules.keyboards import (
    CBA, CB_PREFIX_RESTART, CB_PREFIX_START, CB_PREFIX_STOP,
    CB_PREFIX_DOCKER_START, CB_PREFIX_DOCKER_STOP, CB_PREFIX_DOCKER_RESTART,
    kb_main_menu, kb_confirm, kb_services_action, kb_docker_action
)
from modules.system_monitor import (
    gather_system_status, get_top_processes, get_docker_info, get_network_info,
    sudo_reboot, sudo_shutdown_now, sudo_apt_update_upgrade,
    sudo_systemctl, list_running_services, docker_action, run_command,
    get_public_ip_async,
    get_country_by_ip,  # добавляем импорт
    get_detailed_temperature_info,  # добавляем импорт
    get_local_ip_addresses,
)
from modules.formatters import (
    render_status_html, render_processes_html, render_docker_html,
    render_network_html, render_services_html, render_help_html,
    render_command_result_html, render_temperature_html
)
from modules.monitoring import background_monitoring, scheduled_status, background_temperature_alerts

async def run_outline_audit():
    """
    Запускает outline_audit.sh, возвращает (summary_text, recommendations, full_json_path, raw_text)
    """
    proc = await asyncio.create_subprocess_exec(
        './outline_audit.sh', '--json-only',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode not in (0, 1, 2):
        return (f"❌ Ошибка запуска outline_audit.sh (код {proc.returncode})\n<pre>{stderr.decode(errors='ignore')}</pre>", [], None, stdout.decode(errors='ignore'))
    # stdout содержит JSON или текст
    try:
        data = json.loads(stdout.decode())

        # --- Формируем списки OK и проблем ---
        tests: dict = data.get('tests', {})
        summary = tests.get('summary', {})

        ok_results: list[str] = []
        recs: list[str] = []
        speedtest_checked = False
        speedtest_ok = False
        for tid, t in tests.items():
            status = t.get('status', '').upper()
            message = t.get('message', '')

            # OK-результаты
            if status == "OK" and message:
                ok_results.append(f"{tid}: {message}")
            # speedtest отдельная логика для альтернативы
            if tid == "speedtest":
                speedtest_checked = True
                if status == "OK":
                    speedtest_ok = True
            # 1) Явные рекомендации в тексте
            if 'рекомендац' in message.lower():
                recs.append(message)
            # 2) Любой WARN/FAIL считаем «рекомендацией/проблемой»
            if status in {"WARN", "FAIL"} and message:
                recs.append(f"{tid}: {message}")
            # 3) Поищем ключи/значения содержащие рекомендацию
            for v in t.values():
                if isinstance(v, str) and 'рекомендац' in v.lower():
                    recs.append(v)

        # Альтернативная проверка speedtest через curl, если speedtest отсутствует
        if speedtest_checked and not speedtest_ok:
            import shutil
            if shutil.which('curl'):
                import time
                test_url = 'http://speedtest.tele2.net/10MB.zip'
                try:
                    t0 = time.time()
                    proc = await asyncio.create_subprocess_exec(
                        'curl', '-o', '/dev/null', '-s', test_url,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.communicate()
                    t1 = time.time()
                    duration = t1 - t0
                    speed_mbps = round(10 / duration * 8, 2) if duration > 0 else 0
                    ok_results.append(f"curl_speedtest: ~{speed_mbps} Mbps (10MB за {duration:.1f} сек)")
                except Exception as e:
                    recs.append(f"curl_speedtest: ошибка проверки скорости через curl: {e}")
            else:
                recs.append("curl_speedtest: curl не установлен, невозможно проверить скорость альтернативно.")

        # Убираем дубликаты при сохранении порядка
        seen = set()
        uniq_recs = []
        for r in recs:
            if r not in seen:
                uniq_recs.append(r)
                seen.add(r)

        # --- Собираем HTML для Telegram ---
        summary_text = (
            f"<b>Outline Audit</b>\n"
            f"Статус: <b>{summary.get('status', '?')}</b>\n"
            f"{summary.get('message', '')}\n"
        )

        if ok_results:
            summary_text += '\n<b>OK:</b>\n' + '\n'.join(f'- {r}' for r in ok_results)
        if uniq_recs:
            summary_text += '\n\n<b>Рекомендации / проблемы:</b>\n' + '\n'.join(f'- {r}' for r in uniq_recs)

        # Сохраняем полный JSON во временный файл (для кнопки «скачать отчёт»)
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            json_path = f.name

        return (summary_text, uniq_recs, json_path, None)

    except Exception as e:
        # Если не удалось распарсить JSON, возвращаем текстовый вывод
        return (
            f"❌ Не удалось распарсить JSON из outline_audit.sh: {e}",
            [],
            None,
            stdout.decode(errors='ignore')
        )

# ----------------------------------------------------------------------------
# Bot setup
# ----------------------------------------------------------------------------

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

dp.include_router(router)

# ----------------------------------------------------------------------------
# Command Handlers
# ----------------------------------------------------------------------------

@router.message(Command("start"))
@admin_only
async def cmd_start(message: Message, command: CommandObject, **kwargs):
    logger.info("/start from admin")
    await message.answer(
        "👋 Привет! Я бот для удалённого мониторинга и управления сервером. Используй /help для списка команд.",
        reply_markup=kb_main_menu()
    )

@router.message(Command("help"))
@admin_only
async def cmd_help(message: Message, command: CommandObject, **kwargs):
    logger.info("/help from admin")
    await message.answer(render_help_html(), reply_markup=kb_main_menu())

@router.message(Command("status"))
@admin_only
async def cmd_status(message: Message, command: CommandObject, **kwargs):
    logger.info("/status from admin")
    status = gather_system_status()
    await message.answer(render_status_html(status), reply_markup=kb_main_menu())

@router.message(Command("services"))
@admin_only
async def cmd_services(message: Message, command: CommandObject, **kwargs):
    logger.info("/services from admin")
    rc, out, err = await list_running_services()
    if rc != 0:
        text = f"Не удалось получить список сервисов (rc={rc}).\n<pre>{err or out}</pre>"
    else:
        text = render_services_html(out)
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("restart"))
@admin_only
async def cmd_restart(message: Message, command: CommandObject, **kwargs):
    logger.info("/restart from admin")
    await message.answer("Подтвердите перезагрузку сервера.", 
                        reply_markup=kb_confirm("reboot", CBA.CONFIRM_REBOOT.value))

@router.message(Command("shutdown"))
@admin_only
async def cmd_shutdown(message: Message, command: CommandObject, **kwargs):
    logger.info("/shutdown from admin")
    await message.answer("Подтвердите завершение работы сервера.", 
                        reply_markup=kb_confirm("shutdown", CBA.CONFIRM_SHUTDOWN.value))

@router.message(Command("update"))
@admin_only
async def cmd_update(message: Message, command: CommandObject, **kwargs):
    logger.info("/update from admin")
    await message.answer("Подтвердите обновление пакетов (apt-get update && upgrade).", 
                        reply_markup=kb_confirm("update", CBA.CONFIRM_UPDATE.value))

@router.message(Command("ip"))
@admin_only
async def cmd_ip(message: Message, command: CommandObject, **kwargs):
    logger.info("/ip from admin")
    ipv4, ipv6 = await get_public_ip_async()
    text = []
    if ipv4:
        country4 = await get_country_by_ip(ipv4)
        if country4:
            text.append(f"Публичный IPv4: <code>{ipv4}</code>\nСтрана: <b>{country4}</b>")
        else:
            text.append(f"Публичный IPv4: <code>{ipv4}</code>\nСтрана: <i>не определена</i>")
    else:
        text.append("Публичный IPv4: <i>не найден</i>")
    if ipv6:
        country6 = await get_country_by_ip(ipv6)
        if country6:
            text.append(f"Публичный IPv6: <code>{ipv6}</code>\nСтрана: <b>{country6}</b>")
        else:
            text.append(f"Публичный IPv6: <code>{ipv6}</code>\nСтрана: <i>не определена</i>")
    else:
        text.append("Публичный IPv6: <i>не найден</i>")
    # Локальные IP
    local_ips = get_local_ip_addresses(include_ipv6=True)
    if local_ips:
        lines = ["<b>Локальные IP (LAN):</b>"]
        for iface, ips in local_ips.items():
            lines.append(f"{iface}: <code>{', '.join(ips)}</code>")
        text.append("\n".join(lines))
    await message.answer("\n\n".join(text), reply_markup=kb_main_menu())

@router.message(Command("service"))
@admin_only
async def cmd_service(message: Message, command: CommandObject, **kwargs):
    logger.info("/service from admin args=%s", command.args)
    if not command.args:
        await message.answer("Использование: /service &lt;start|stop|restart&gt; &lt;service_name&gt;", 
                            reply_markup=kb_main_menu())
        return
    
    parts = command.args.strip().split()
    if len(parts) < 2:
        await message.answer("Нужно указать действие и имя сервиса. Пример: /service restart nginx", 
                            reply_markup=kb_main_menu())
        return
    
    action, service = parts[0].lower(), ' '.join(parts[1:])
    if action not in ("start", "stop", "restart", "status"):
        await message.answer("Действие должно быть start|stop|restart|status.", reply_markup=kb_main_menu())
        return
    
    rc, out, err = await sudo_systemctl(action, service)
    text = render_command_result_html(f"systemctl {action}", service, rc, out, err)
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("processes"))
@admin_only
async def cmd_processes(message: Message, command: CommandObject, **kwargs):
    logger.info("/processes from admin")
    processes = get_top_processes(15)
    text = render_processes_html(processes)
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("docker"))
@admin_only
async def cmd_docker(message: Message, command: CommandObject, **kwargs):
    logger.info("/docker from admin")
    docker_info = await get_docker_info()
    text = render_docker_html(docker_info)
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("network"))
@admin_only
async def cmd_network(message: Message, command: CommandObject, **kwargs):
    logger.info("/network from admin")
    network_info = get_network_info()
    text = render_network_html(network_info)
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("dockerctl"))
@admin_only
async def cmd_dockerctl(message: Message, command: CommandObject, **kwargs):
    logger.info("/dockerctl from admin args=%s", command.args)
    if not command.args:
        await message.answer("Использование: /dockerctl &lt;start|stop|restart&gt; &lt;container_name&gt;", 
                            reply_markup=kb_main_menu())
        return
    
    parts = command.args.strip().split()
    if len(parts) < 2:
        await message.answer("Нужно указать действие и имя контейнера. Пример: /dockerctl restart nginx", 
                            reply_markup=kb_main_menu())
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
        text = render_command_result_html(f"docker {action}", container, rc, out, err)
    
    await message.answer(text, reply_markup=kb_main_menu())

@router.message(Command("temp"))
@admin_only
async def cmd_temp(message: Message, command: CommandObject, **kwargs):
    logger.info("/temp from admin")
    try:
        temp_info = get_detailed_temperature_info()
        text = render_temperature_html(temp_info)
        await message.answer(text, reply_markup=kb_main_menu())
    except Exception as e:
        logger.error(f"Error in temp command: {e}")
        error_text = "❌ Ошибка при получении информации о температуре"
        await message.answer(error_text, reply_markup=kb_main_menu())

@router.message(Command("outline_audit"))
@admin_only
async def cmd_outline_audit(message: Message, command: CommandObject, **kwargs):
    logger.info("/outline_audit from admin")
    wait_msg = await message.answer("⏳ Запуск аудита Outline VPN...")
    summary_text, recs, json_path, raw_text = await run_outline_audit()
    try:
        if raw_text and not json_path:
            # Если не удалось распарсить JSON, отправляем читаемый текстовый вывод
            await wait_msg.edit_text(f"<pre>{raw_text}</pre>", reply_markup=kb_main_menu())
        else:
            await wait_msg.edit_text(summary_text, reply_markup=kb_main_menu())
            if json_path:
                with open(json_path, 'rb') as f:
                    await message.answer_document(f, caption="Полный JSON отчёт Outline Audit")
    except Exception:
        # Если не удалось отредактировать (например, сообщение слишком старое), просто отправляем новое
        if raw_text and not json_path:
            await message.answer(f"<pre>{raw_text}</pre>", reply_markup=kb_main_menu())
        else:
            await message.answer(summary_text, reply_markup=kb_main_menu())
            if json_path:
                with open(json_path, 'rb') as f:
                    await message.answer_document(f, caption="Полный JSON отчёт Outline Audit")

# ----------------------------------------------------------------------------
# Callback Query Handlers
# ----------------------------------------------------------------------------

@router.callback_query(F.data == CBA.REFRESH_STATUS.value)
async def cb_refresh_status(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    status = gather_system_status()
    try:
        await callback.message.edit_text(render_status_html(status), reply_markup=kb_main_menu())
    except Exception:
        await callback.message.answer(render_status_html(status), reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_SERVICES.value)
async def cb_show_services(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    rc, out, err = await list_running_services()
    if rc != 0:
        text = f"Не удалось получить список сервисов (rc={rc}).\n<pre>{err or out}</pre>"
    else:
        text = render_services_html(out)
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_PROCESSES.value)
async def cb_show_processes(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    processes = get_top_processes(15)
    text = render_processes_html(processes)
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_DOCKER.value)
async def cb_show_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    docker_info = await get_docker_info()
    text = render_docker_html(docker_info)
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_NETWORK.value)
async def cb_show_network(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    network_info = get_network_info()
    text = render_network_html(network_info)
    try:
        await callback.message.edit_text(text, reply_markup=kb_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

# Double-confirmation ask steps
@router.callback_query(F.data == CBA.ASK_REBOOT.value)
async def cb_ask_reboot(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    try:
        await callback.message.answer(
            "Подтвердите перезагрузку сервера.",
            reply_markup=kb_confirm("reboot", CBA.CONFIRM_REBOOT.value)
        )
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == CBA.ASK_SHUTDOWN.value)
async def cb_ask_shutdown(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    try:
        await callback.message.answer(
            "Подтвердите завершение работы сервера.",
            reply_markup=kb_confirm("shutdown", CBA.CONFIRM_SHUTDOWN.value)
        )
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == CBA.ASK_UPDATE.value)
async def cb_ask_update(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    try:
        await callback.message.answer(
            "Подтвердите обновление пакетов (apt-get update && upgrade).",
            reply_markup=kb_confirm("update", CBA.CONFIRM_UPDATE.value)
        )
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_TEMPERATURE.value)
async def cb_show_temperature(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    try:
        temp_info = get_detailed_temperature_info()
        text = render_temperature_html(temp_info)
        try:
            await callback.message.edit_text(text, reply_markup=kb_main_menu())
        except Exception as e:
            logger.warning(f"Failed to edit message, sending new one: {e}")
            await callback.message.answer(text, reply_markup=kb_main_menu())
    except Exception as e:
        logger.error(f"Error in temperature callback: {e}")
        error_text = "❌ Ошибка при получении информации о температуре"
        try:
            await callback.message.answer(error_text, reply_markup=kb_main_menu())
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data == CBA.SHOW_TEMPERATURE_LIVE.value)
async def cb_show_temperature_live(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    
    chat_id = callback.message.chat.id
    # Создаем клавиатуру с кнопкой остановки
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    stop_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹ Остановить", callback_data="STOP_LIVE_TEMP")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=CBA.SHOW_TEMPERATURE_LIVE.value)]
    ])
    
    try:
        # Если сессия уже есть и активна — не создаем новое сообщение, просто обновим существующее
        existing_task = live_temp_sessions.get(chat_id)
        if existing_task and not existing_task.done():
            try:
                temp_info = get_detailed_temperature_info()
                text = render_temperature_html(temp_info)
                text += "\n\n🔄 <b>Live режим уже активен</b>\nОбновление каждые 2 секунды"
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=live_temp_message_ids.get(chat_id),
                    text=text,
                    reply_markup=stop_keyboard
                )
            except Exception:
                # Игнорируем ошибки редактирования, например, если сообщение слишком старое
                pass
            await callback.answer("Live уже активен", show_alert=False)
            return
        # Если сессия была, но уже завершилась — очистим следы
        if existing_task and existing_task.done():
            live_temp_sessions.pop(chat_id, None)
            live_temp_message_ids.pop(chat_id, None)

        # Запускаем новую live-сессию: отправляем сообщение и стартуем обновление
        temp_info = get_detailed_temperature_info()
        text = render_temperature_html(temp_info)
        text += "\n\n🔄 <b>Live режим активен</b>\nОбновление каждые 2 секунды"

        live_message = await callback.message.answer(text, reply_markup=stop_keyboard)
        live_temp_message_ids[chat_id] = live_message.message_id

        task = asyncio.create_task(update_temperature_live(chat_id, live_message.message_id, stop_keyboard))
        live_temp_sessions[chat_id] = task
        
    except Exception as e:
        logger.error(f"Error in live temperature callback: {e}")
        error_text = "❌ Ошибка при получении информации о температуре"
        await callback.message.answer(error_text, reply_markup=kb_main_menu())
    
    await callback.answer()

@router.callback_query(F.data == "STOP_LIVE_TEMP")
async def cb_stop_live_temperature(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    
    # Останавливаем live сессию в этом чате
    chat_id = callback.message.chat.id
    task = live_temp_sessions.pop(chat_id, None)
    live_temp_message_ids.pop(chat_id, None)
    if task and not task.done():
        try:
            task.cancel()
        except Exception:
            pass
    
    try:
        await callback.message.edit_text(
            "⏹ Live режим температуры остановлен",
            reply_markup=kb_main_menu()
        )
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")
        await callback.message.answer("⏹ Live режим температуры остановлен", reply_markup=kb_main_menu())
    
    await callback.answer()

@router.callback_query(F.data == CBA.CONFIRM_REBOOT.value)
async def cb_confirm_reboot(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    await callback.answer("Перезагрузка...", show_alert=False)
    logger.warning("Admin confirmed reboot via inline button")
    rc, out, err = await sudo_reboot()
    try:
        await callback.message.answer(f"Команда reboot отправлена (rc={rc}).")
    except Exception:
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
    except Exception:
        pass

@router.callback_query(F.data == CBA.CONFIRM_UPDATE.value)
async def cb_confirm_update(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    await callback.answer("Обновление пакетов...", show_alert=False)
    logger.warning("Admin confirmed apt update/upgrade via inline button")
    rc, out, err = await sudo_apt_update_upgrade()
    text = render_command_result_html("apt update/upgrade", "", rc, out, err)
    try:
        await callback.message.answer(text, reply_markup=kb_main_menu())
    except Exception:
        pass

# Dynamic service action callbacks
@router.callback_query(F.data.startswith(CB_PREFIX_RESTART))
async def cb_restart_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_RESTART):]
    logger.info("Restart service via button: %s", service)
    rc, out, err = await sudo_systemctl("restart", service)
    text = render_command_result_html("systemctl restart", service, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data.startswith(CB_PREFIX_START))
async def cb_start_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_START):]
    logger.info("Start service via button: %s", service)
    rc, out, err = await sudo_systemctl("start", service)
    text = render_command_result_html("systemctl start", service, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data.startswith(CB_PREFIX_STOP))
async def cb_stop_service(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    service = callback.data[len(CB_PREFIX_STOP):]
    logger.info("Stop service via button: %s", service)
    rc, out, err = await sudo_systemctl("stop", service)
    text = render_command_result_html("systemctl stop", service, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

# Docker action callbacks
@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_RESTART))
async def cb_restart_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_RESTART):]
    logger.info("Restart docker container via button: %s", container)
    rc, out, err = await docker_action("restart", container)
    text = render_command_result_html("docker restart", container, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_START))
async def cb_start_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_START):]
    logger.info("Start docker container via button: %s", container)
    rc, out, err = await docker_action("start", container)
    text = render_command_result_html("docker start", container, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data.startswith(CB_PREFIX_DOCKER_STOP))
async def cb_stop_docker(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    container = callback.data[len(CB_PREFIX_DOCKER_STOP):]
    logger.info("Stop docker container via button: %s", container)
    rc, out, err = await docker_action("stop", container)
    text = render_command_result_html("docker stop", container, rc, out, err)
    await callback.message.answer(text, reply_markup=kb_main_menu())
    await callback.answer()

@router.callback_query(F.data == "GET_IP")
async def cb_get_ip(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    ipv4, ipv6 = await get_public_ip_async()
    text = []
    if ipv4:
        country4 = await get_country_by_ip(ipv4)
        if country4:
            text.append(f"Публичный IPv4: <code>{ipv4}</code>\nСтрана: <b>{country4}</b>")
        else:
            text.append(f"Публичный IPv4: <code>{ipv4}</code>\nСтрана: <i>не определена</i>")
    else:
        text.append("Публичный IPv4: <i>не найден</i>")
    if ipv6:
        country6 = await get_country_by_ip(ipv6)
        if country6:
            text.append(f"Публичный IPv6: <code>{ipv6}</code>\nСтрана: <b>{country6}</b>")
        else:
            text.append(f"Публичный IPv6: <code>{ipv6}</code>\nСтрана: <i>не определена</i>")
    else:
        text.append("Публичный IPv6: <i>не найден</i>")
    # Локальные IP
    local_ips = get_local_ip_addresses(include_ipv6=True)
    if local_ips:
        lines = ["<b>Локальные IP (LAN):</b>"]
        for iface, ips in local_ips.items():
            lines.append(f"{iface}: <code>{', '.join(ips)}</code>")
        text.append("\n".join(lines))
    await callback.message.answer("\n\n".join(text), reply_markup=kb_main_menu())
    try:
        await callback.answer()  # Закрыть спиннер
    except Exception:
        pass

@router.callback_query(F.data == CBA.OUTLINE_AUDIT.value)
async def cb_outline_audit(callback: CallbackQuery):
    if not await admin_only_callback(callback):
        return
    logger.info("Outline Audit button pressed by admin")
    await callback.answer("Запуск аудита Outline VPN...", show_alert=False)
    summary_text, recs, json_path, raw_text = await run_outline_audit()
    if raw_text and not json_path:
        await callback.message.answer(f"<pre>{raw_text}</pre>", reply_markup=kb_main_menu())
    else:
        await callback.message.answer(summary_text, reply_markup=kb_main_menu())
        if json_path:
            with open(json_path, 'rb') as f:
                await callback.message.answer_document(f, caption="Полный JSON отчёт Outline Audit")

# Generic cancel handler for confirmation dialogs
@router.callback_query(F.data == "IGNORE")
async def cb_ignore(callback: CallbackQuery):
    if not await admin_only_callback(callback, silent=True):
        return
    # Close spinner
    try:
        await callback.answer("Отменено", show_alert=False)
    except Exception:
        pass
    # Replace confirmation with cancelled notice
    try:
        await callback.message.edit_text("❎ Действие отменено.", reply_markup=kb_main_menu())
    except Exception:
        try:
            await callback.message.answer("❎ Действие отменено.", reply_markup=kb_main_menu())
        except Exception:
            pass

# ----------------------------------------------------------------------------
# Live temperature update function
# ----------------------------------------------------------------------------

async def update_temperature_live(chat_id: int, message_id: int, keyboard):
    """
    Обновляет температуру в реальном времени каждые 2 секунды
    """
    max_updates = 300  # Максимум ~10 минут
    update_count = 0
    try:
        while update_count < max_updates:
            # Получаем новую информацию о температуре
            temp_info = get_detailed_temperature_info()
            text = render_temperature_html(temp_info)
            text += f"\n\n🔄 <b>Live режим активен</b>\nОбновление каждые 2 секунды\nОбновлений: {update_count + 1}/{max_updates}"

            # Обновляем сообщение
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard
            )

            update_count += 1
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        # Нормальное завершение по отмене
        pass
    except Exception as e:
        logger.error(f"Error updating live temperature: {e}")
    finally:
        # Очистка сессии, если она всё ещё указывает на нас
        cur = live_temp_sessions.get(chat_id)
        if cur and cur.done():
            live_temp_sessions.pop(chat_id, None)
            live_temp_message_ids.pop(chat_id, None)

# ----------------------------------------------------------------------------
# Bot command list setup
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
        BotCommand(command="temp", description="Температура системы"),
        BotCommand(command="restart", description="Перезагрузка сервера"),
        BotCommand(command="shutdown", description="Выключение сервера"),
        BotCommand(command="update", description="Обновление пакетов"),
        BotCommand(command="ip", description="Публичный IP"),
        BotCommand(command="service", description="Управление сервисом"),
        BotCommand(command="dockerctl", description="Управление Docker"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())

# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

async def main() -> None:
    await set_bot_commands()
    
    # Уведомление админу о запуске
    try:
        await bot.send_message(ADMIN_ID_INT, "✅ Сервер запущен и бот активен.")
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение админу при запуске: {e}")
    
    # Start background monitoring and scheduler
    asyncio.create_task(background_monitoring(bot))
    asyncio.create_task(scheduled_status(bot))
    asyncio.create_task(background_temperature_alerts(bot))
    
    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.") 