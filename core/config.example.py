# Пример конфигурационного файла для Telegram System Monitoring Bot
# Скопируйте этот файл в config.py и настройте под свои нужды

# Основные настройки бота
BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"  # Токен от @BotFather
ADMIN_ID = 123456789  # Ваш Telegram ID (можно узнать у @userinfobot)

# Настройки логирования
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR

# Настройки мониторинга температуры CPU
# Для Orange Pi Zero 3 используйте эту команду:
TEMP_SENSORS_COMMAND = """for zone in /sys/class/thermal/thermal_zone*/temp; do 
    zone_name=$(basename $(dirname $zone))
    zone_type=$(cat /sys/class/thermal/$zone_name/type 2>/dev/null || echo "Unknown")
    temp=$(cat $zone)
    temp_c=$(echo "scale=1; $temp/1000" | bc -l)
    
    # Маппинг типов на понятные названия
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

# Альтернативные команды для температуры:
# TEMP_SENSORS_COMMAND = "cat /sys/class/thermal/thermal_zone0/temp | awk '{print $1/1000}'"
# TEMP_SENSORS_COMMAND = "sensors -u"  # если установлен lm-sensors

# Пороги для уведомлений (в процентах)
ALERT_CPU_THRESHOLD = 90.0      # Загрузка CPU
ALERT_RAM_THRESHOLD = 90.0      # Использование RAM
ALERT_DISK_THRESHOLD = 10.0     # Свободное место на диске
ALERT_TEMP_THRESHOLD = 70.0     # Температура CPU в °C

# Важные сервисы для мониторинга
ALERT_SERVICES = [
    "nginx",
    "postgresql", 
    "mysql",
    "docker",
    "redis-server",
    "apache2"
]

# Важные Docker контейнеры для мониторинга
ALERT_DOCKER_CONTAINERS = [
    "nginx",
    "postgres",
    "mysql", 
    "redis",
    "app",
    "database"
]

# Настройки уведомлений
NOTIFICATION_SETTINGS = {
    "enable_daily_report": True,     # Ежедневный отчет
    "daily_report_time": "00:00",    # Время отправки отчета
    "check_interval": 60,            # Интервал проверки в секундах
    "enable_escalation": False,      # Эскалация уведомлений
    "escalation_timeout": 300,       # Таймаут эскалации в секундах
}

# Настройки безопасности
SECURITY_SETTINGS = {
    "max_login_attempts": 5,         # Максимум попыток входа
    "block_time": 300,               # Время блокировки в секундах
    "enable_2fa": False,             # Двухфакторная аутентификация
    "session_timeout": 3600,         # Таймаут сессии в секундах
}

# Настройки резервного копирования
BACKUP_SETTINGS = {
    "enable_auto_backup": False,     # Автоматические бэкапы
    "backup_path": "/backups",       # Путь для бэкапов
    "backup_retention": 7,           # Количество дней хранения
    "backup_time": "02:00",          # Время бэкапа
}

# Настройки веб-интерфейса (опционально)
WEB_SETTINGS = {
    "enable_web_interface": False,   # Веб-интерфейс
    "web_port": 8080,                # Порт веб-интерфейса
    "web_host": "0.0.0.0",           # Хост веб-интерфейса
    "enable_api": False,             # REST API
}

# Настройки интеграций
INTEGRATION_SETTINGS = {
    "enable_prometheus": False,      # Prometheus метрики
    "prometheus_port": 9090,         # Порт Prometheus
    "enable_slack": False,           # Slack уведомления
    "slack_webhook": "",             # Slack webhook URL
    "enable_email": False,           # Email уведомления
    "smtp_server": "",               # SMTP сервер
    "smtp_port": 587,                # SMTP порт
    "smtp_user": "",                 # SMTP пользователь
    "smtp_password": "",             # SMTP пароль
}

# Настройки мониторинга приложений
APP_MONITORING = {
    "enable_web_checks": False,      # Проверка веб-приложений
    "web_endpoints": [               # Список URL для проверки
        "http://localhost:80",
        "http://localhost:8080/api/health",
        "https://example.com"
    ],
    "enable_db_checks": False,       # Проверка баз данных
    "database_connections": [        # Строки подключения к БД
        "postgresql://user:pass@localhost/db",
        "mysql://user:pass@localhost/db"
    ]
}

# Настройки планировщика задач
SCHEDULED_TASKS = [
    {
        "name": "daily_backup",
        "schedule": "0 2 * * *",     # Cron выражение: 2:00 каждый день
        "command": "backup_script.sh",
        "enabled": False,
        "description": "Ежедневный бэкап"
    },
    {
        "name": "log_rotation", 
        "schedule": "0 0 * * 0",     # Каждое воскресенье в 00:00
        "command": "logrotate",
        "enabled": False,
        "description": "Ротация логов"
    },
    {
        "name": "system_update",
        "schedule": "0 3 * * 0",     # Каждое воскресенье в 3:00
        "command": "apt update && apt upgrade -y",
        "enabled": False,
        "description": "Обновление системы"
    }
]

# Настройки конфигурационных файлов для мониторинга
CONFIG_FILES = [
    "/etc/nginx/nginx.conf",
    "/etc/postgresql/postgresql.conf", 
    "/etc/redis/redis.conf",
    "/etc/mysql/mysql.conf.d/mysqld.cnf"
]

# Настройки метрик и мониторинга
METRICS_SETTINGS = {
    "enable_bot_metrics": True,      # Метрики самого бота
    "metrics_retention": 30,         # Дни хранения метрик
    "enable_performance_logging": True,  # Логирование производительности
    "performance_log_file": "performance.log"  # Файл логов производительности
} 