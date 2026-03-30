# Примеры использования Telegram System Monitoring Bot

## 🚀 Быстрый старт

### 1. Первый запуск
```bash
# Установка и запуск через pm2
./install.sh

# Настройка конфигурации (если используете config.py)
nano config.py

# Или настройка переменных окружения в .env файле
nano .env
```

### 2. Проверка работы
```bash
# Статус процесса
pm2 status

# Просмотр логов
pm2 logs tg_system_bot

# Проверка конфигурации
./venv/bin/python main.py --test-config
```

### 3. Настройка переменных окружения
```bash
# Создание .env файла (если не создан автоматически)
touch .env

# Добавление переменных в .env
echo "BOT_TOKEN=your_bot_token_here" >> .env
echo "ADMIN_ID=your_telegram_id" >> .env
echo "LOG_LEVEL=INFO" >> .env
```

## 📱 Использование в Telegram

### Основные команды

#### Получение статуса системы
```
/status
```
**Результат:**
```
📊 Статистика сервера
Время: 14:30:25
CPU: 15.2%
RAM: 2.1GB/8.0GB (26.3%)
Swap: 0B/2.0GB (0.0%)
CPU Temp: 45.2°C
Uptime: 5d 12h 30m 15s
Users: admin, user1

Диски:
/: 45.2GB/120GB (37.7%)
/home: 120GB/500GB (24.0%)

Система:
OS: Ubuntu 22.04.3 LTS
Kernel: 5.15.0-88-generic
```

#### Просмотр процессов
```
/processes
```
**Результат:**
```
📈 Топ процессов по использованию ресурсов:
1. nginx (PID: 1234)
   CPU: 2.1% | RAM: 1.2% | Статус: running
2. postgres (PID: 5678)
   CPU: 1.8% | RAM: 8.5% | Статус: running
3. docker (PID: 9012)
   CPU: 0.5% | RAM: 2.1% | Статус: running
```

#### Docker контейнеры
```
/docker
```
**Результат:**
```
🐳 Docker контейнеры:
Запущено: 3/4

Контейнеры:
🟢 nginx
   Статус: Up 2 hours
   Образ: nginx:latest
   Порты: 80:80, 443:443

🟢 postgres
   Статус: Up 1 day
   Образ: postgres:13
   Порты: 5432:5432

🔴 redis
   Статус: Exited (1) 2 hours ago
   Образ: redis:alpine
   Порты: 6379:6379
```

#### Сетевая информация
```
/network
```
**Результат:**
```
🌐 Сетевая информация:
Активные соединения: 156
Прослушиваемые порты: 22, 80, 443, 5432, 6379, 8080

Интерфейсы:
eth0:
   Отправлено: 1.2GB
   Получено: 5.8GB

lo:
   Отправлено: 45.2MB
   Получено: 45.2MB
```

### Управление сервисами

#### Просмотр сервисов
```
/services
```
**Результат:**
```
🧰 Активные сервисы:
UNIT                    LOAD   ACTIVE SUB     DESCRIPTION
nginx.service          loaded active running A high performance web server
postgresql.service     loaded active running PostgreSQL RDBMS
docker.service         loaded active running Docker Application Container Engine
redis-server.service   loaded active running Advanced key-value store
```

#### Управление сервисом
```
/service restart nginx
```
**Результат:**
```
✅ Успех при выполнении systemctl restart nginx.
```

#### Управление Docker контейнером
```
/dockerctl restart redis
```
**Результат:**
```
✅ Успех при выполнении docker restart redis.
```

#### Просмотр логов контейнера
```
/dockerctl logs nginx
```
**Результат:**
```
📋 Логи контейнера nginx:
2024/01/15 14:30:25 [notice] 1#1: start worker processes
2024/01/15 14:30:25 [notice] 1#1: start worker process 1234
2024/01/15 14:30:25 [notice] 1#1: start worker process 1235
```

#### Интерактивная shell-сессия
```
/shell
```
**Пример использования:**
```
pwd
cd /opt
ls -la
tail -f /var/log/syslog
```

**Завершение сессии:**
```
/shell_exit
```

> Для включения режима нужно задать `ENABLE_SHELL=true` в `.env` или `config.py`.

### Системные операции

#### Перезагрузка сервера
```
/restart
```
**Результат:** Появится кнопка подтверждения

#### Обновление пакетов
```
/update
```
**Результат:**
```
✅ apt update/upgrade завершено rc=0.
Reading package lists... Done
Building dependency tree... Done
Reading state information... Done
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
```

## 🔧 Продвинутое использование

### Управление ботом через pm2

#### Основные команды pm2
```bash
# Статус всех процессов
pm2 status

# Статус конкретного процесса
pm2 status tg_system_bot

# Просмотр логов
pm2 logs tg_system_bot

# Просмотр логов в реальном времени
pm2 logs tg_system_bot --lines 100 -f

# Перезапуск бота
pm2 restart tg_system_bot

# Остановка бота
pm2 stop tg_system_bot

# Запуск бота
pm2 start tg_system_bot

# Удаление процесса из pm2
pm2 delete tg_system_bot

# Сохранение текущего состояния
pm2 save

# Настройка автозапуска
pm2 startup
```

#### Применение изменений в коде
```bash
# После изменения main.py или config.py
./install.sh

# Или просто перезапуск
pm2 reload tg_system_bot

# Или полный перезапуск
pm2 restart tg_system_bot
```

#### Мониторинг ресурсов
```bash
# Просмотр использования ресурсов
pm2 monit

# Детальная информация о процессе
pm2 show tg_system_bot

# Просмотр всех логов
pm2 logs
```

### Настройка мониторинга

#### Изменение порогов уведомлений
```python
# В config.py
ALERT_CPU_THRESHOLD = 80.0      # Уведомление при 80% CPU
ALERT_RAM_THRESHOLD = 85.0      # Уведомление при 85% RAM
ALERT_DISK_THRESHOLD = 15.0     # Уведомление при 15% свободного места
```

#### Добавление важных сервисов
```python
# В config.py
ALERT_SERVICES = [
    "nginx",
    "postgresql", 
    "mysql",
    "docker",
    "redis-server",
    "apache2",
    "your-custom-service"  # Добавьте свой сервис
]
```

#### Добавление Docker контейнеров
```python
# В config.py
ALERT_DOCKER_CONTAINERS = [
    "nginx",
    "postgres",
    "mysql", 
    "redis",
    "your-app",           # Добавьте свой контейнер
    "database"
]
```

### Автоматизация

#### Создание скрипта для массовых операций
```bash
#!/bin/bash
# restart_services.sh

# Перезапуск всех важных сервисов
services=("nginx" "postgresql" "redis-server")

for service in "${services[@]}"; do
    echo "Перезапуск $service..."
    sudo systemctl restart $service
    sleep 2
done
```

#### Настройка cron для автоматических задач
```bash
# Добавить в crontab
0 2 * * * cd /path/to/bot && ./venv/bin/python main.py --backup
0 3 * * 0 cd /path/to/bot && ./venv/bin/python main.py --update
```

### Интеграция с внешними системами

#### Prometheus метрики
```python
# Добавить в config.py
INTEGRATION_SETTINGS = {
    "enable_prometheus": True,
    "prometheus_port": 9090,
}
```

#### Slack уведомления
```python
# Добавить в config.py
INTEGRATION_SETTINGS = {
    "enable_slack": True,
    "slack_webhook": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
}
```

## 🚨 Устранение неполадок

### Проблемы с pm2
```bash
# Проверка статуса pm2
pm2 status

# Проверка логов pm2
pm2 logs

# Перезапуск pm2
pm2 kill
pm2 start main.py --interpreter venv/bin/python3 --name tg_system_bot

# Проверка автозапуска pm2
pm2 startup
pm2 save
```

### Проблемы с правами
```bash
# Проверка sudo прав (если нужны)
sudo -l

# Проверка путей команд
which reboot
which systemctl
which docker

# Проверка прав на файлы
ls -la main.py
ls -la config.py
ls -la .env
```

### Проблемы с Docker
```bash
# Проверка Docker
docker --version
docker ps

# Добавление пользователя в группу docker
sudo usermod -aG docker $USER

# Перезапуск Docker
sudo systemctl restart docker
```

### Проблемы с температурой CPU
```bash
# Установка lm-sensors
sudo apt install lm-sensors
sudo sensors-detect --auto

# Проверка работы
sensors

# Настройка в config.py
TEMP_SENSORS_COMMAND = "sensors -u"
```

### Проблемы с сетевыми соединениями
```bash
# Проверка сетевых интерфейсов
ip addr show

# Проверка открытых портов
netstat -tlnp

# Проверка firewall
sudo ufw status
```

### Проблемы с переменными окружения
```bash
# Проверка .env файла
cat .env

# Проверка переменных окружения
env | grep BOT
env | grep ADMIN

# Тестирование загрузки переменных
./venv/bin/python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('BOT_TOKEN:', os.getenv('BOT_TOKEN'))"
```

## 📊 Мониторинг производительности

### Просмотр логов бота
```bash
# Логи pm2
pm2 logs tg_system_bot

# Логи pm2 в реальном времени
pm2 logs tg_system_bot -f

# Логи pm2 с ограничением строк
pm2 logs tg_system_bot --lines 50

# Все логи pm2
pm2 logs

# Очистка логов
pm2 flush
```

### Метрики использования ресурсов
```bash
# CPU и память
htop

# Диски
df -h
iostat -x 1

# Сеть
iftop
nethogs

# Мониторинг pm2
pm2 monit
```

### Проверка здоровья системы
```bash
# Проверка сервисов
sudo systemctl list-units --failed

# Проверка Docker
docker system df
docker system prune

# Проверка логов
sudo journalctl --since "1 hour ago" | grep -i error

# Проверка pm2 процессов
pm2 status
pm2 show tg_system_bot
```

## 🔐 Безопасность

### Настройка firewall
```bash
# Разрешить только необходимые порты
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### Ограничение доступа к боту
```python
# В config.py - только ваш ID
ADMIN_ID = 123456789  # Замените на ваш ID

# Или в .env файле
# ADMIN_ID=123456789
```

### Регулярные обновления
```bash
# Обновление системы
sudo apt update && sudo apt upgrade

# Обновление Docker образов
docker system prune -a

# Обновление бота
git pull origin main
./install.sh

# Или просто перезапуск
pm2 reload tg_system_bot
```

## 📈 Оптимизация

### Настройка интервалов проверки
```python
# В config.py
NOTIFICATION_SETTINGS = {
    "check_interval": 30,  # Проверка каждые 30 секунд
}
```

### Кэширование данных
```python
# В config.py
METRICS_SETTINGS = {
    "enable_caching": True,
    "cache_ttl": 60,  # Время жизни кэша в секундах
}
```

### Ограничение ресурсов через pm2
```bash
# Запуск с ограничением памяти
pm2 start main.py --interpreter venv/bin/python3 --name tg_system_bot --max-memory-restart 300M

# Или через ecosystem.config.js
cat > ecosystem.config.js <<EOF
module.exports = {
  apps : [{
    name: "tg_system_bot",
    script: "./main.py",
    interpreter: "./venv/bin/python",
    max_memory_restart: "300M",
    node_args: "--max-old-space-size=300"
  }]
}
EOF
pm2 start ecosystem.config.js
```

## 🎯 Лучшие практики

1. **Регулярные бэкапы конфигурации**
   ```bash
   cp config.py config.py.backup
   cp .env .env.backup
   ```

2. **Мониторинг логов**
   ```bash
   pm2 logs tg_system_bot --lines 100
   ```

3. **Тестирование перед продакшеном**
   ```bash
   ./venv/bin/python main.py --test-config
   ```

4. **Документирование изменений**
   ```bash
   git add .
   git commit -m "Update bot configuration"
   ```

5. **Регулярные обновления**
   ```bash
   git pull origin main
   ./install.sh
   ```

6. **Мониторинг безопасности**
   ```bash
   pm2 status
   sudo journalctl --since "1 hour ago" | grep -i error
   ```

7. **Планирование аварийного восстановления**
   ```bash
   # Создание скрипта восстановления
   cat > restore.sh <<EOF
   #!/bin/bash
   git pull origin main
   ./install.sh
   pm2 reload tg_system_bot
   EOF
   chmod +x restore.sh
   ```

## 🔄 Миграция с systemd на pm2

Если у вас была предыдущая установка через systemd:

```bash
# Остановка старого сервиса
sudo systemctl stop telegram-bot
sudo systemctl disable telegram-bot

# Удаление старого сервиса
sudo rm /etc/systemd/system/telegram-bot.service
sudo systemctl daemon-reload

# Установка через pm2
./install.sh
``` 