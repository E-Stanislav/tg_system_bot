#!/bin/bash

set -e

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Проверка Python и pip
if ! command -v python3 &>/dev/null; then
    print_error "Python3 не установлен!"
    exit 1
fi
if ! command -v pip3 &>/dev/null; then
    print_error "pip3 не установлен!"
    exit 1
fi

# Установка системных зависимостей для компиляции
print_info "Проверка и установка системных зависимостей..."
if ! dpkg -l | grep -q python3-dev; then
    print_info "Установка python3-dev..."
    sudo apt-get update
    sudo apt-get install -y gcc python3-dev
fi

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

# Установка outline_audit.sh
chmod +x outline_audit.sh
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
        print_error "npm не установлен! Установите Node.js и npm."
        exit 1
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