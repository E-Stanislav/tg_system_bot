# Telegram System Monitoring Bot

Мощный Telegram бот для удалённого мониторинга и управления Linux серверами. Позволяет администраторам получать информацию о состоянии системы, управлять сервисами и Docker контейнерами через удобный интерфейс Telegram.

## 🚀 Основные возможности

### 📊 Мониторинг системы
- **CPU**: загрузка процессора, температура
- **RAM**: использование памяти и swap
- **Диски**: свободное место, использование
- **Сеть**: активные соединения, прослушиваемые порты, статистика интерфейсов
- **Процессы**: топ процессов по использованию ресурсов
- **Uptime**: время работы системы
- **Пользователи**: активные пользователи

### 🌡 Мониторинг температуры
- **Детальная информация**: температура CPU, GPU, RAM, SoC и других компонентов
- **Цветовая индикация**: 
  - 🟢 < 50°C - оптимальная температура
  - 🟡 50-70°C - повышенная температура
  - 🟠 70-85°C - высокая температура
  - 🔴 > 85°C - критическая температура
- **Поддержка Orange Pi Zero 3**: автоматическое определение типов сенсоров
- **Fallback режим**: работает даже если не все сенсоры доступны

### 🐳 Docker интеграция
- Список всех контейнеров
- Статус контейнеров (работает/остановлен)
- Управление контейнерами (start/stop/restart)
- Просмотр логов контейнеров
- Мониторинг важных контейнеров

### 🧰 Управление сервисами
- Просмотр запущенных systemd сервисов
- Управление сервисами (start/stop/restart)
- Мониторинг важных сервисов

### ⚡ Системные операции
- Перезагрузка сервера (с подтверждением)
- Выключение сервера (с подтверждением)
- Обновление пакетов (apt update && upgrade)
- Получение публичного IP
- Интерактивная shell-сессия через Telegram

### 🔔 Автоматические уведомления
- Высокая загрузка CPU (>90%)
- Высокое использование RAM (>90%)
- Мало места на диске (<10% свободно)
- Остановленные важные сервисы
- Остановленные Docker контейнеры

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/help` | Справка по командам |
| `/status` | Статистика сервера |
| `/services` | Запущенные сервисы |
| `/processes` | Топ процессов |
| `/docker` | Docker контейнеры |
| `/network` | Сетевая информация |
| `/temp` | Температура системы |
| `/restart` | Перезагрузка сервера |
| `/shutdown` | Выключение сервера |
| `/update` | Обновление пакетов |
| `/ip` | Публичный IP |
| `/service <action> <name>` | Управление сервисом |
| `/dockerctl <action> <container>` | Управление Docker |
| `/shell` | Открыть интерактивную bash-сессию |
| `/shell <cmd>` | Открыть shell и сразу выполнить команду |
| `/shell_exit` | Завершить shell-сессию |

## 🛠 Установка и настройка

### 1. Установка зависимостей
```bash
python3 -m venv venv
source venv/bin/activate
pip install aiogram psutil python-dotenv
```

### 2. Настройка переменных окружения
```bash
export BOT_TOKEN="123456:ABC..."  # Токен от BotFather
export ADMIN_ID="123456789"       # Ваш Telegram ID
export LOG_LEVEL="INFO"           # Уровень логирования
```

### 3. Настройка sudo прав
Создайте файл `/etc/sudoers.d/telegrambot`:
```bash
sudo visudo -f /etc/sudoers.d/telegrambot
```

Содержимое:
```text
telegrambot ALL=(root) NOPASSWD:/sbin/reboot,/sbin/shutdown,/usr/bin/apt,/usr/bin/apt-get,/usr/bin/systemctl
```

### 4. Запуск бота
```bash
python3 bot.py
```

## 🔧 Конфигурация

### Переменные окружения
- `BOT_TOKEN` - токен Telegram бота
- `ADMIN_ID` - ID администратора
- `LOG_LEVEL` - уровень логирования (DEBUG, INFO, WARNING, ERROR)
- `TEMP_SENSORS_COMMAND` - команда для получения температуры CPU
- `BOT_LOG_FILE` - файл для логов (по умолчанию: bot.log)
- `ENABLE_SHELL` - разрешить интерактивный bash через Telegram (`true/false`)

### Настройка мониторинга температуры

Для Orange Pi Zero 3 добавьте в `config.py`:
```python
TEMP_SENSORS_COMMAND = """for zone in /sys/class/thermal/thermal_zone*/temp; do 
    zone_name=$(basename $(dirname $zone))
    zone_type=$(cat /sys/class/thermal/$zone_name/type 2>/dev/null || echo "Unknown")
    temp=$(cat $zone)
    temp_c=$(echo "scale=1; $temp/1000" | bc -l)
    
    case "$zone_type" in
        "cpu-thermal") display_name="CPU" ;;
        "gpu-thermal") display_name="GPU" ;;
        "ddr-thermal") display_name="RAM" ;;
        "soc-thermal") display_name="SoC" ;;
        "pmic-thermal") display_name="PMIC" ;;
        *) display_name="$zone_type" ;;
    esac
    
    printf "%s: %.1f°C\\n" "$display_name" "$temp_c"
done"""
```

Альтернативные команды:
```bash
# Простая команда для одной thermal zone
TEMP_SENSORS_COMMAND = "cat /sys/class/thermal/thermal_zone0/temp | awk '{print $1/1000}'"

# Использование lm-sensors
TEMP_SENSORS_COMMAND = "sensors -u"
```

### Настройка мониторинга
В коде можно настроить пороги для уведомлений:
```python
ALERT_CPU_THRESHOLD = 90.0      # % загрузки CPU
ALERT_RAM_THRESHOLD = 90.0      # % использования RAM
ALERT_DISK_THRESHOLD = 10.0     # % свободного места на диске
ALERT_SERVICES = ["nginx", "postgresql", "mysql", "docker"]  # важные сервисы
ALERT_DOCKER_CONTAINERS = ["nginx", "postgres", "mysql", "redis"]  # важные контейнеры
```

## 🔒 Безопасность

- Все критические операции требуют подтверждения
- Ограниченные sudo права для бота
- Логирование всех действий администратора
- Проверка ID пользователя перед выполнением команд
- Интерактивный shell по умолчанию выключен и требует явного `ENABLE_SHELL=true`

## 📱 Интерфейс

Бот использует inline кнопки для удобной навигации:
- 📊 Статус - основная информация о системе
- 🧰 Сервисы - управление systemd сервисами
- 📈 Процессы - топ процессов
- 🐳 Docker - управление контейнерами
- 🌐 Сеть - сетевая информация
- 🔄 Reboot/Shutdown - системные операции
- ⬆ Update - обновление пакетов

## 🚨 Уведомления

Бот автоматически отправляет уведомления при:
- Превышении порогов использования ресурсов
- Остановке важных сервисов
- Проблемах с Docker контейнерами
- Запуске/остановке бота

## 📈 Мониторинг

### Ежедневные отчеты
Бот отправляет ежедневный отчет о состоянии системы в 00:00.

### Фоновая проверка
Каждую минуту проверяется:
- Загрузка CPU и RAM
- Свободное место на дисках
- Статус важных сервисов
- Статус Docker контейнеров

## 🔄 Обновления

Для обновления бота:
```bash
git pull origin main
pip install -r requirements.txt
systemctl restart telegram-bot  # если используется systemd
```

## 🐛 Устранение неполадок

### Проблемы с правами
```bash
# Проверка sudo прав
sudo -l -U telegrambot

# Проверка путей команд
which reboot
which systemctl
which docker
```

### Проблемы с Docker
```bash
# Проверка установки Docker
docker --version

# Проверка прав на Docker
sudo usermod -aG docker telegrambot
```

### Проблемы с температурой CPU
```bash
# Установка lm-sensors (опционально)
sudo apt install lm-sensors
sudo sensors-detect

# Проверка работы
sensors

# Для Orange Pi Zero 3 - проверка thermal zones
ls /sys/class/thermal/
cat /sys/class/thermal/thermal_zone*/temp

# Проверка типов сенсоров
cat /sys/class/thermal/thermal_zone*/type
```

## 📝 Логирование

Логи сохраняются в файл `bot.log` и содержат:
- Все команды администратора
- Результаты выполнения операций
- Ошибки и предупреждения
- Информацию о запуске/остановке

## 🤝 Вклад в проект

1. Fork репозитория
2. Создайте ветку для новой функции
3. Внесите изменения
4. Создайте Pull Request

## 📄 Лицензия

MIT License - см. файл LICENSE для подробностей.

## ⚠️ Отказ от ответственности

Этот бот предоставляет удалённый доступ к серверу. Используйте его ответственно и обеспечьте надлежащую безопасность. Авторы не несут ответственности за любой ущерб, причинённый использованием этого программного обеспечения.