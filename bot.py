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
from typing import Optional
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
    get_public_ip_async
)
from modules.formatters import (
    render_status_html, render_processes_html, render_docker_html,
    render_network_html, render_services_html, render_help_html,
    render_command_result_html
)
from modules.monitoring import background_monitoring, scheduled_status

async def run_outline_audit():
    """
    Запускает outline_audit.sh, возвращает (summary_text, recommendations, full_json_path)
    """
    proc = await asyncio.create_subprocess_exec(
        './outline_audit.sh', '--json-only',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode not in (0, 1, 2):
        return (f"❌ Ошибка запуска outline_audit.sh (код {proc.returncode})\n<pre>{stderr.decode(errors='ignore')}</pre>", [], None)
    # stdout содержит JSON
    try:
        data = json.loads(stdout.decode())
    except Exception as e:
        return (f"❌ Не удалось распарсить JSON из outline_audit.sh: {e}", [], None)
    # Собираем summary и рекомендации
    tests = data.get('tests', {})
    summary = tests.get('summary', {})
    recs = []
    for t in tests.values():
        if 'message' in t and 'рекомендац' in t['message'].lower():
            recs.append(t['message'])
    # Также собираем RECOMMENDATIONS из тестов, если есть
    for t in tests.values():
        for k, v in t.items():
            if isinstance(v, str) and 'рекомендац' in v.lower():
                recs.append(v)
    # Формируем summary
    summary_text = f"<b>Outline Audit</b>\nСтатус: <b>{summary.get('status','?')}</b>\n{summary.get('message','')}\n"
    if recs:
        summary_text += '\n<b>Рекомендации:</b>\n' + '\n'.join(f'- {r}' for r in set(recs))
    # Сохраняем полный JSON во временный файл
    with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        json_path = f.name
    return (summary_text, recs, json_path)

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
        text.append(f"Публичный IPv4: <code>{ipv4}</code>")
    else:
        text.append("Публичный IPv4: <i>не найден</i>")
    if ipv6:
        text.append(f"Публичный IPv6: <code>{ipv6}</code>")
    else:
        text.append("Публичный IPv6: <i>не найден</i>")
    await message.answer("\n".join(text), reply_markup=kb_main_menu())

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

@router.message(Command("outline_audit"))
@admin_only
async def cmd_outline_audit(message: Message, command: CommandObject, **kwargs):
    logger.info("/outline_audit from admin")
    await message.answer("⏳ Аудит Outline VPN, подождите...")
    summary_text, recs, json_path = await run_outline_audit()
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
        text.append(f"Публичный IPv4: <code>{ipv4}</code>")
    else:
        text.append("Публичный IPv4: <i>не найден</i>")
    if ipv6:
        text.append(f"Публичный IPv6: <code>{ipv6}</code>")
    else:
        text.append("Публичный IPv6: <i>не найден</i>")
    await callback.message.answer("\n".join(text), reply_markup=kb_main_menu())
    try:
        await callback.answer()  # Закрыть спиннер
    except Exception:
        pass

@router.callback_query(F.data == CBA.OUTLINE_AUDIT.value)
@admin_only_callback
async def cb_outline_audit(callback: CallbackQuery):
    logger.info("Outline Audit button pressed by admin")
    await callback.answer("Запуск аудита Outline VPN...", show_alert=False)
    summary_text, recs, json_path = await run_outline_audit()
    await callback.message.answer(summary_text, reply_markup=kb_main_menu())
    if json_path:
        with open(json_path, 'rb') as f:
            await callback.message.answer_document(f, caption="Полный JSON отчёт Outline Audit")

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
    
    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.") 