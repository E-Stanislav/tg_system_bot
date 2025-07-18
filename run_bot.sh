#!/bin/bash

# Проверка наличия виртуального окружения
if [ ! -d "venv" ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv venv
fi

# Активация виртуального окружения
source venv/bin/activate

# Проверка наличия файла .env
if [ ! -f ".env" ]; then
    echo "Создаю пустой .env файл..."
    touch .env
fi

# Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt

# Проверка наличия pm2
if ! command -v pm2 &> /dev/null; then
    echo "pm2 не найден, устанавливаю..."
    npm install -g pm2
fi

# Запуск main.py через pm2
pm2 start main.py --interpreter venv/bin/python3 --name tg_system_bot --max-memory-restart 300M