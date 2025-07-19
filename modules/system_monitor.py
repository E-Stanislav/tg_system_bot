#!/usr/bin/env python3
"""
System monitoring module for Telegram Remote Monitoring & Management Bot
"""

import asyncio
import logging
import platform
import psutil
import re
import shlex
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict

import aiohttp
from core.config import TEMP_SENSORS_COMMAND

logger = logging.getLogger("system_monitor")

# ----------------------------------------------------------------------------
# Data classes for system information
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

@dataclass
class NetworkInfo:
    connections_count: int
    listening_ports: List[int]
    bandwidth_rx: Optional[float]  # MB/s
    bandwidth_tx: Optional[float]  # MB/s
    interface_stats: Dict[str, Dict[str, int]]

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

# ----------------------------------------------------------------------------
# System information gatherers
# ----------------------------------------------------------------------------

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

def get_os_info() -> Tuple[str, str]:
    os_name = platform.platform(aliased=True, terse=False)
    kernel = platform.release()
    return os_name, kernel

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

def get_top_processes(limit: int = 10) -> List[ProcessInfo]:
    """Получить топ процессов по использованию ресурсов"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status']):
            try:
                info = proc.info
                memory_info = info.get('memory_info')
                memory_rss = memory_info.rss if memory_info is not None else 0
                processes.append(ProcessInfo(
                    pid=info['pid'],
                    name=info['name'],
                    cpu_percent=info['cpu_percent'] if info['cpu_percent'] is not None else 0.0,
                    memory_percent=info['memory_percent'] if info['memory_percent'] is not None else 0.0,
                    memory_rss=memory_rss,
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
                parts = re.split(r'\s{2,}|\t', line, maxsplit=3)
                if len(parts) == 3:
                    parts.insert(2, '')  # PORTS пустой
                if len(parts) == 4:
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

async def get_country_by_ip(ip: str) -> Optional[str]:
    """Получить страну по IP через ip-api.com (или аналогичный сервис)"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=country"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("country")
    except Exception as e:
        logger.warning(f"Ошибка получения страны по IP: {e}")
    return None

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
# Command execution helpers
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

async def get_public_ip_async() -> tuple[Optional[str], Optional[str]]:
    """Try to discover both public IPv4 and IPv6 addresses."""
    ipv4 = None
    ipv6 = None
    # IPv4
    for cmd in (
        "dig -4 +short myip.opendns.com @resolver1.opendns.com",
        "curl -4 -s ifconfig.me",
        "curl -4 -s https://api.ipify.org",
    ):
        rc, out, err = await run_command(cmd, timeout=10)
        if rc == 0 and out.strip():
            ip = out.strip().split()[0]
            if "." in ip and len(ip) <= 64:
                ipv4 = ip
                break
    # IPv6
    for cmd in (
        "dig -6 +short myip.opendns.com @resolver1.opendns.com",
        "curl -6 -s ifconfig.me",
        "curl -6 -s https://api64.ipify.org",
    ):
        rc, out, err = await run_command(cmd, timeout=10)
        if rc == 0 and out.strip():
            ip = out.strip().split()[0]
            if ":" in ip and len(ip) <= 64:
                ipv6 = ip
                break
    return ipv4, ipv6 