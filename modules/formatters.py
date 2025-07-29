#!/usr/bin/env python3
"""
Formatters module for Telegram Remote Monitoring & Management Bot
"""

import textwrap
from datetime import timedelta
from typing import List

from modules.system_monitor import SystemStatus, ProcessInfo, DockerInfo, NetworkInfo

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

# ----------------------------------------------------------------------------
# HTML rendering functions
# ----------------------------------------------------------------------------

def render_status_html(status: SystemStatus) -> str:
    lines = []
    from datetime import datetime
    now = datetime.now().strftime('%H:%M:%S')
    lines.append(f"<b>📊 Статистика сервера</b>\nВремя: <code>{now}</code>")
    lines.append(f"CPU: <code>{status.cpu.percent:.1f}%</code>")
    lines.append(f"RAM: <code>{fmt_bytes(status.memory.used)}/{fmt_bytes(status.memory.total)} ({status.memory.percent:.1f}%)</code>")
    lines.append(f"Swap: <code>{fmt_bytes(status.swap.used)}/{fmt_bytes(status.swap.total)} ({status.swap.percent:.1f}%)</code>")
    if status.cpu_temp_c is not None:
        # Добавляем статус температуры
        from modules.system_monitor import get_temperature_status
        emoji, temp_status = get_temperature_status(status.cpu_temp_c)
        lines.append(f"CPU Temp: <code>{status.cpu_temp_c:.1f}°C</code> {emoji} ({temp_status})")
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

def render_processes_html(processes: List[ProcessInfo]) -> str:
    if not processes:
        return "Не удалось получить информацию о процессах."
    
    lines = ["<b>📈 Топ процессов по использованию ресурсов:</b>"]
    for i, proc in enumerate(processes, 1):
        lines.append(f"{i}. <b>{proc.name}</b> (PID: {proc.pid})")
        lines.append(f"   CPU: <code>{proc.cpu_percent:.1f}%</code> | RAM: <code>{proc.memory_percent:.1f}%</code> | Статус: <code>{proc.status}</code>")
    return '\n'.join(lines)

def render_docker_html(docker_info: DockerInfo) -> str:
    if docker_info.containers_total == 0:
        return "Docker не установлен или нет контейнеров."
    
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
    
    return '\n'.join(lines)

def render_network_html(network_info: NetworkInfo) -> str:
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
    
    return '\n'.join(lines)

def render_services_html(services_output: str, max_lines: int = 40) -> str:
    if not services_output.strip():
        return "Не удалось получить список сервисов."
    
    lines = services_output.strip().splitlines()
    shown = lines[:max_lines]
    if len(lines) > max_lines:
        shown.append(f"... ({len(lines)-max_lines} строк скрыто)")
    
    return "<b>Активные сервисы</b>\n<pre>" + "\n".join(shown) + "</pre>\nВыберите конкретный сервис командой /service ..."

def render_help_html() -> str:
    return textwrap.dedent(
        """
        <b>Доступные команды</b>
        /start - Главное меню
        /help - Эта справка
        /status - Показать статистику сервера
        /services - Показать запущенные сервисы (systemd)
        /processes - Топ процессов по использованию ресурсов
        /docker - Информация о Docker контейнерах
        /network - Сетевая информация и активные соединения
        /temp - Температура системы (CPU, GPU, RAM и др.)
        /restart - Перезагрузка сервера (подтверждение)
        /shutdown - Завершение работы (подтверждение)
        /update - apt update && upgrade (подтверждение)
        /ip - Публичный IP сервера
        /service &lt;action&gt; &lt;name&gt; - Управление сервисом (start|stop|restart). Пример: /service restart nginx
        /dockerctl &lt;action&gt; &lt;container&gt; - Управление Docker (start|stop|restart|logs). Пример: /dockerctl restart nginx
        """
    ).strip()

def render_command_result_html(action: str, target: str, rc: int, output: str, error: str) -> str:
    if rc == 0:
        prefix = "✅ Успех"
    else:
        prefix = f"❌ Ошибка rc={rc}"
    
    content = (output or error).strip()[:4000]
    return f"{prefix} при выполнении {action} {target}.\n<pre>{content}</pre>"

def render_temperature_html(temp_info: str) -> str:
    """
    Форматирует информацию о температуре для Telegram
    """
    from datetime import datetime
    import html
    
    now = datetime.now().strftime('%H:%M:%S')
    
    lines = [f"<b>🌡 Температура системы</b>\nВремя: <code>{now}</code>"]
    
    # Добавляем легенду
    lines.append("\n<b>Легенда:</b>")
    lines.append("🟢 &lt; 50°C - оптимальная")
    lines.append("🟡 50-70°C - повышенная")
    lines.append("🟠 70-85°C - высокая")
    lines.append("🔴 &gt; 85°C - критическая")
    lines.append("")
    
    if temp_info.startswith("Ошибка"):
        lines.append(f"❌ {html.escape(temp_info)}")
    else:
        # Разбираем строки с температурой
        temp_lines = temp_info.strip().split('\n')
        for line in temp_lines:
            if ':' in line and '°C' in line:
                # Добавляем эмодзи и подпись в зависимости от температуры
                try:
                    temp_value = float(line.split(':')[1].replace('°C', '').strip())
                    if temp_value < 50:
                        emoji = "🟢"  # Нормальная температура
                        status = "оптимальная"
                    elif temp_value < 70:
                        emoji = "🟡"  # Повышенная температура
                        status = "повышенная"
                    elif temp_value < 85:
                        emoji = "🟠"  # Высокая температура
                        status = "высокая"
                    else:
                        emoji = "🔴"  # Критическая температура
                        status = "критическая"
                    # Экранируем HTML-символы в строке температуры
                    safe_line = html.escape(line)
                    lines.append(f"{emoji} {safe_line} ({status})")
                except ValueError:
                    lines.append(f"📊 {html.escape(line)}")
            else:
                lines.append(f"📊 {html.escape(line)}")
    
    return '\n'.join(lines) 