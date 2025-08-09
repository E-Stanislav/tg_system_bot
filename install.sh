#!/bin/bash

set -e
set -o pipefail

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Определяем, нужен ли sudo
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

# Проверка менеджера пакетов (apt-get)
if ! command -v apt-get &>/dev/null; then
    print_error "Поддерживается только системы с apt-get (Debian/Ubuntu)."
    echo "Установите вручную: python3, python3-pip, python3-venv, npm (или используйте systemd)."
    exit 1
fi

APT_UPDATED=0

disable_broken_apt_repos() {
    print_info "Пытаюсь отключить проблемные репозитории (docker-ce и др.)..."
    local files_to_check=(/etc/apt/sources.list /etc/apt/sources.list.d/*.list)
    for f in "${files_to_check[@]}"; do
        [ -f "$f" ] || continue
        if grep -Eqi '(docker(-ce)?|docker-ce|download\.docker\.com|huaweicloud\.com/docker-ce)' "$f"; then
            $SUDO sed -i 's/^[[:space:]]*deb\(\-src\)\{0,1\}[[:space:]]\+/# &/' "$f"
            print_info "Отключен репозиторий в: $f"
        fi
    done
}

ensure_apt_updated() {
    if [ "$APT_UPDATED" -eq 0 ]; then
        print_info "Обновление списка пакетов..."
        if ! $SUDO apt-get update; then
            print_error "apt-get update завершился с ошибкой."
            disable_broken_apt_repos || true
            print_info "Повторная попытка обновить список пакетов после отключения проблемных репозиториев..."
            $SUDO apt-get update
        fi
        APT_UPDATED=1
    fi
}

ensure_pkg() {
    local pkg="$1"
    if ! dpkg -s "$pkg" &>/dev/null; then
        ensure_apt_updated
        print_info "Устанавливаю пакет: $pkg"
        $SUDO apt-get install -y "$pkg"
    fi
}

# Базовые зависимости ОС
ensure_pkg gcc
ensure_pkg python3
ensure_pkg python3-pip
ensure_pkg python3-venv
ensure_pkg build-essential
ensure_pkg curl
ensure_pkg dnsutils

# Проверка Python и pip (после возможной установки)
if ! command -v python3 &>/dev/null; then
    print_error "Python3 не найден после установки. Прервусь."
    exit 1
fi
if ! command -v pip3 &>/dev/null; then
    print_error "pip3 не найден после установки. Прервусь."
    exit 1
fi

# Установка системных зависимостей для компиляции
print_info "Проверка и установка системных зависимостей..."
ensure_pkg python3-dev

# Проверка и создание виртуального окружения
if [ ! -d "venv" ]; then
    print_info "Создаю виртуальное окружение..."
    python3 -m venv venv
fi

# Активация виртуального окружения
print_info "Активация виртуального окружения..."
source venv/bin/activate

# Проверка активации виртуального окружения
if [ -z "$VIRTUAL_ENV" ]; then
    print_error "Виртуальное окружение не активировано!"
    exit 1
fi
print_success "Виртуальное окружение активировано: $VIRTUAL_ENV"

# Установка outline_audit.sh (если файл существует)
if [ -f "outline_audit.sh" ]; then
    chmod +x outline_audit.sh
fi
# Проверка и создание .env файла
if [ ! -f ".env" ]; then
    print_info "Создаю пустой .env файл..."
    touch .env
fi

# Установка зависимостей
print_info "Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

# Проверка установки ключевых зависимостей
print_info "Проверка установки зависимостей..."
if ! python -c "import aiogram" 2>/dev/null; then
    print_error "aiogram не установлен! Повторная установка..."
    pip install aiogram==3.4.1
fi

if ! python -c "import psutil" 2>/dev/null; then
    print_error "psutil не установлен! Повторная установка..."
    pip install psutil==5.9.8
fi

# Проверка и установка pm2
if ! command -v pm2 &>/dev/null; then
    print_info "Установка pm2 (через npm)..."
    if ! command -v npm &>/dev/null; then
        print_info "npm не найден, устанавливаю Node.js и npm..."
        ensure_pkg nodejs
        ensure_pkg npm
    fi
    npm install -g pm2
fi

# Удаляем старый процесс, если он запускал main.py
if pm2 list --name tg_system_bot | grep -q tg_system_bot; then
    if pm2 info tg_system_bot | grep -q 'main.py'; then
        print_info "Удаляю старый процесс tg_system_bot (main.py)..."
        pm2 stop tg_system_bot || true
        pm2 delete tg_system_bot || true
    fi
fi

# Запуск или перезапуск bot.py через pm2
if pm2 list --name tg_system_bot | grep -q tg_system_bot; then
    print_info "Перезапуск tg_system_bot через pm2..."
    pm2 reload tg_system_bot || true
else
    print_info "Запуск tg_system_bot через pm2..."
    pm2 start bot.py --interpreter venv/bin/python3 --name tg_system_bot --max-memory-restart 300M --cwd $(pwd)
fi

# Сохраняем текущие процессы pm2 для автозапуска после перезагрузки, если есть хотя бы один онлайн-процесс
if [ "$(pm2 list | grep -c online)" -gt 0 ]; then
    pm2 save --force
fi

# Настраиваем автозапуск pm2 при старте системы (однократно, если не настроено)
if [ ! -f "/etc/systemd/system/pm2-$(whoami).service" ]; then
    pm2 startup
    echo -e "${YELLOW}Выполните команду, которую выведет pm2 startup, с sudo (пример: sudo env PATH=\$PATH pm2 startup systemd -u $(whoami) --hp /home/$(whoami))${NC}"
fi

print_success "Бот tg_system_bot успешно установлен и запущен через pm2!"
echo
print_info "Для управления используйте:"
echo "  pm2 status"
echo "  pm2 logs tg_system_bot"
echo "  pm2 restart tg_system_bot"
echo "  pm2 stop tg_system_bot"
echo
print_info "Для применения изменений в файлах или конфигах просто перезапустите этот скрипт или выполните pm2 reload tg_system_bot." 