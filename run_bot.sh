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

# Запуск main.py
python main.py 