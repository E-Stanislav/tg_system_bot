#!/usr/bin/env python3
"""
Тестовый скрипт для демонстрации работы модульной структуры
"""

import sys
import os

# Добавляем корень проекта в путь для импорта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_config():
    """Тест модуля конфигурации"""
    print("🔧 Тестирование config.py...")
    try:
        from core.config import BOT_TOKEN, ADMIN_ID_INT, DEFAULT_LOG_LEVEL
        print(f"   BOT_TOKEN: {'✅ Установлен' if BOT_TOKEN else '❌ Не установлен'}")
        print(f"   ADMIN_ID: {'✅ Установлен' if ADMIN_ID_INT else '❌ Не установлен'}")
        print(f"   LOG_LEVEL: {DEFAULT_LOG_LEVEL}")
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_auth():
    """Тест модуля аутентификации"""
    print("🔐 Тестирование auth.py...")
    try:
        from modules.auth import is_admin
        result = is_admin(123456789)
        print(f"   is_admin(123456789): {result}")
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_system_monitor():
    """Тест модуля мониторинга системы"""
    print("📊 Тестирование system_monitor.py...")
    try:
        from modules.system_monitor import gather_system_status, get_top_processes
        from modules.formatters import render_status_html
        
        # Получаем статус системы
        status = gather_system_status()
        print(f"   CPU: {status.cpu.percent:.1f}%")
        print(f"   RAM: {status.memory.percent:.1f}%")
        print(f"   Uptime: {status.uptime}")
        
        # Получаем топ процессов
        processes = get_top_processes(3)
        print(f"   Топ процессов: {len(processes)} найдено")
        
        # Тестируем форматирование
        html = render_status_html(status)
        print(f"   HTML статус: {len(html)} символов")
        
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_formatters():
    """Тест модуля форматирования"""
    print("🎨 Тестирование formatters.py...")
    try:
        from modules.formatters import fmt_bytes, fmt_timedelta
        from datetime import timedelta
        
        # Тест форматирования размеров
        size = 1024 * 1024 * 1024  # 1GB
        formatted = fmt_bytes(size)
        print(f"   fmt_bytes({size}): {formatted}")
        
        # Тест форматирования времени
        uptime = timedelta(hours=2, minutes=30, seconds=45)
        formatted = fmt_timedelta(uptime)
        print(f"   fmt_timedelta({uptime}): {formatted}")
        
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_keyboards():
    """Тест модуля клавиатур"""
    print("⌨️ Тестирование keyboards.py...")
    try:
        from modules.keyboards import kb_main_menu, CBA
        
        # Создаем главное меню
        menu = kb_main_menu()
        print(f"   Главное меню создано: {len(menu.inline_keyboard)} строк")
        
        # Проверяем callback данные
        print(f"   Callback данные: {list(CBA)}")
        
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_monitoring():
    """Тест модуля мониторинга"""
    print("🔍 Тестирование monitoring.py...")
    try:
        from modules.monitoring import background_monitoring, scheduled_status
        print("   Функции мониторинга доступны")
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🧪 Тестирование модульной структуры Telegram Bot\n")
    
    tests = [
        test_config,
        test_auth,
        test_system_monitor,
        test_formatters,
        test_keyboards,
        test_monitoring
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print(f"📈 Результаты: {passed}/{total} тестов прошли успешно")
    
    if passed == total:
        print("🎉 Все модули работают корректно!")
        print("\n💡 Теперь вы можете:")
        print("   - Запустить бота: python3 bot.py")
        print("   - Использовать модули в своих скриптах")
        print("   - Импортировать функции из любого модуля")
    else:
        print("⚠️ Некоторые модули имеют проблемы")
        print("   Проверьте зависимости и конфигурацию")

if __name__ == "__main__":
    main() 