# Asian Breakout: Полная Русская Документация

Этот файл можно и нужно хранить прямо в проекте. Это нормальная практика.

Файл нужен как единая инструкция для:

- локальной работы на Windows
- запуска бота
- запуска dashboard
- деплоя на Ubuntu-сервер
- обновлений на сервере
- работы с Docker
- работы с Cloudflare Tunnel
- базовой работы с git

## 1. Что это за проект

Проект состоит из трех главных частей:

- `bot` — live-бот, который торгует по стратегии Asian Breakout
- `bridge` — процесс, который собирает live-данные и пишет JSON для dashboard
- `dashboard` — сайт на Next.js, который показывает состояние бота, персонажей, статистику и live dashboard

На сервере все это работает в Docker.

## 2. Текущая инфраструктура

Текущая рабочая схема:

- сервер: `root@178.160.194.52`
- SSH порт: `23019`
- путь проекта на сервере: `/opt/asian-breakout`
- публичный сайт: `https://app.dead-market.com`
- dashboard внутри сервера: `http://127.0.0.1:3000`
- публичный порт dashboard без домена: `http://178.160.194.52:3000`

Если сервер или порт потом изменятся, просто обнови команды в этом файле.

## 3. Как работает бот

Бот берет настройки из `.env`, подключается к Capital.com DEMO и работает по стратегии Asian Breakout.

Основная логика:

- формирует азиатский диапазон
- ждет breakout по закрытой H1 свече
- фильтрует сигнал по relative volume
- использует ATR для расчета `SL` и `TP`
- может блокировать входы через regime guard
- пишет состояние в `state.json`
- пишет аудит и журнал в runtime-файлы
- bridge читает state и брокерские данные и формирует live JSON для dashboard

## 4. Где что находится

Главные файлы и папки:

- `main.py` — главный CLI вход в проект
- `live_bot.py` — live-цикл торговли
- `strategy.py` — правила стратегии
- `config.py` — загрузка `.env` и параметров
- `state.py` — локальное состояние бота
- `dashboard_live_bridge.py` — генерация live dashboard JSON
- `docker-compose.yml` — серверный запуск контейнеров
- `Dockerfile` — Python-образ для `bot` и `bridge`
- `dashboard/Dockerfile` — образ dashboard
- `.env` — твои реальные настройки
- `.env.example` — пример конфигурации
- `runtime/` — живые данные и сохраняемое состояние
- `cloudflare/` — конфиги tunnel
- `scripts/` — полезные серверные и локальные скрипты

### Папка `runtime/`

Это очень важная папка. Она сохраняется между перезапусками контейнеров.

В ней живут:

- `runtime/state.json`
- `runtime/runtime_state.json`
- `runtime/order_audit.jsonl`
- `runtime/performance_journal.json`
- `runtime/performance_journal.csv`
- `runtime/dashboard/live_dashboard.json`
- `runtime/dashboard/manual_withdrawals.json`
- `runtime/backtests/`

Это значит:

- `docker compose up -d --build` не должен стирать твое runtime-состояние
- при переносе на другой сервер важно переносить `.env` и `runtime/`

## 5. Какие команды есть у бота

Основные команды CLI:

```bash
python main.py --help
```

Доступные команды:

- `python main.py --env-file .env live`
- `python main.py --env-file .env sync-history`
- `python main.py --env-file .env stats`
- `python main.py --env-file .env export-journal`
- `python main.py --env-file .env enable`
- `python main.py --env-file .env disable`
- `python main.py --env-file .env status`
- `python main.py --env-file .env backtest`

## 6. Самые важные настройки в `.env`

Пример лежит в:

- `.env.example`

Главные поля:

- `CAPITAL_API_KEY`
- `CAPITAL_IDENTIFIER`
- `CAPITAL_PASSWORD`
- `CAPITAL_BASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `AB_SYMBOLS`
- `AB_ATR_PERIOD`
- `AB_ATR_FILTER_PCT`
- `AB_TP_MULTIPLIER`
- `AB_PORTFOLIO_MARGIN_FRACTION`
- `AB_SESSION_START_HOUR_UTC`
- `AB_ASIAN_SESSION_END_HOUR_UTC`
- `AB_ENTRY_START_HOUR_UTC`
- `AB_ENTRY_END_HOUR_UTC`
- `AB_ENTRY_CHECK_START_MINUTE_UTC`
- `AB_ENTRY_CHECK_END_MINUTE_UTC`
- `AB_FORCE_CLOSE_HOUR_UTC`
- `AB_FORCE_CLOSE_MINUTE_UTC`
- `AB_LOOP_INTERVAL_SECONDS`
- `AB_HISTORY_CANDLES`
- `AB_SIGNAL_RELATIVE_VOLUME_THRESHOLD`
- `AB_BACKTEST_CANDLES`
- `AB_REGIME_GUARD_ENABLED`
- `AB_DASHBOARD_INITIAL_DEPOSIT_USD`
- `AB_DASHBOARD_RESET_AT_UTC`
- `AB_TELEGRAM_MINI_APP_URL`

Важный смысл некоторых параметров:

- `AB_ATR_FILTER_PCT=0` отключает минимальный ATR-фильтр на вход
- `AB_SIGNAL_RELATIVE_VOLUME_THRESHOLD=1.5` включает твой текущий relative volume filter
- ATR все равно используется для `SL` и `TP` даже если фильтр ATR = 0

После изменения `.env` live-процесс или контейнеры надо перезапускать.

## 7. Локальная работа на Windows

### Быстрый запуск полного локального стека

```powershell
.\scripts\start_dead_market_stack.ps1
```

Или двойной клик:

- `Start Dead Market.cmd`

Это запускает:

- dashboard на `127.0.0.1:3000`
- bridge
- live bot
- Cloudflare Tunnel

### Остановка локального стека

```powershell
.\scripts\stop_dead_market_stack.ps1
```

Или двойной клик:

- `Stop Dead Market.cmd`

### Если менялся frontend

```powershell
.\scripts\start_dead_market_stack.ps1 -RebuildDashboard
```

### Как проверить, что локальный бот не работает

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'main.py --env-file .env live|dashboard_live_bridge.py --env-file .env') } | Select-Object ProcessId, Name, CommandLine
```

Если команда ничего не вернула, значит локально бот не запущен.

### Локальные логи

Логи лежат в:

- `runtime/logs/bot.out.log`
- `runtime/logs/bot.err.log`
- `runtime/logs/bridge.out.log`
- `runtime/logs/bridge.err.log`
- `runtime/logs/dashboard.out.log`
- `runtime/logs/dashboard.err.log`
- `runtime/logs/cloudflared.out.log`
- `runtime/logs/cloudflared.err.log`

## 8. Серверный запуск через Docker

На сервере у тебя работают три контейнера:

- `bot`
- `bridge`
- `dashboard`

Главный файл:

- `docker-compose.yml`

### Проверить состояние контейнеров

```bash
cd /opt/asian-breakout
docker compose ps
```

### Посмотреть логи

```bash
docker compose logs --tail=50 bot
docker compose logs --tail=50 bridge
docker compose logs --tail=50 dashboard
```

Live-режим логов:

```bash
docker compose logs -f bot
docker compose logs -f bridge
docker compose logs -f dashboard
```

Выйти из live-логов:

```text
Ctrl + C
```

### Перезапуск контейнеров

```bash
cd /opt/asian-breakout
docker compose restart
```

### Остановить контейнеры

```bash
cd /opt/asian-breakout
docker compose stop
```

### Запустить снова

```bash
cd /opt/asian-breakout
docker compose start
```

### Полная пересборка

```bash
cd /opt/asian-breakout
docker compose up -d --build
```

## 9. Домен и Cloudflare Tunnel

Текущий домен:

- `https://app.dead-market.com`

Tunnel теперь работает как Linux systemd service на сервере.

Полезные команды:

```bash
systemctl status cloudflared --no-pager
journalctl -u cloudflared -n 50 --no-pager
journalctl -u cloudflared -f
systemctl restart cloudflared
```

Конфиги:

- `cloudflare/dead-market-tunnel.yml` — старый Windows-конфиг
- `cloudflare/dead-market-tunnel.linux.yml` — Linux-шаблон
- `/root/.cloudflared/config.yml` — реальный серверный конфиг
- `/root/.cloudflared/2e986217-27c7-443c-8b25-e5fcbdde9a86.json` — credentials файла tunnel

Если домен дает `502`, сначала проверь:

```bash
curl -I http://127.0.0.1:3000
systemctl status cloudflared --no-pager
journalctl -u cloudflared -n 50 --no-pager
```

## 10. Как вносить изменения и отправлять их на сервер

У тебя сейчас рабочий deploy flow через zip-бандл.

### Шаг 1. Собрать архив на Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_upload_bundle.ps1
```

Если нужно перенести и текущее runtime-состояние:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_upload_bundle.ps1 -IncludeRuntimeState
```

Скрипт создает:

- `dist/asian-breakout-upload/`
- `dist/asian-breakout-upload.zip`

### Шаг 2. Загрузить архив на сервер

```powershell
scp -P 23019 .\dist\asian-breakout-upload.zip root@178.160.194.52:/opt/asian-breakout/
```

### Шаг 3. Обновить файлы на сервере

```bash
ssh -p 23019 root@178.160.194.52
cd /opt/asian-breakout
unzip -o asian-breakout-upload.zip
docker compose up -d --build
docker compose ps
```

### Шаг 4. Проверить после деплоя

```bash
docker compose logs --tail=50 bot
docker compose logs --tail=50 dashboard
systemctl status cloudflared --no-pager
```

## 11. Что не надо грузить на сервер руками

Обычно не нужно загружать:

- `.git`
- `dashboard/node_modules`
- `dashboard/.next`
- `backtests`
- `__pycache__`
- локальные логи

Скрипт `build_upload_bundle.ps1` как раз это уже учитывает.

## 12. Как сделать backup

На сервере:

```bash
cd /opt/asian-breakout
tar czf asian-breakout-backup.tar.gz .env runtime
```

Это основной backup, который нужен для переноса.

## 13. Как сделать git commit

### Посмотреть изменения

```bash
git status
```

Короткий вид:

```bash
git status --short
```

### Посмотреть diff

```bash
git diff
```

Для конкретного файла:

```bash
git diff README_RU.md
```

### Добавить файлы в commit

Все изменения:

```bash
git add .
```

Только конкретные файлы:

```bash
git add README_RU.md README.md
```

### Сделать commit

```bash
git commit -m "Add Russian project runbook"
```

### Отправить в удаленный репозиторий

```bash
git push
```

Если это новая ветка:

```bash
git push -u origin <branch-name>
```

### Обновить локальный проект из git

```bash
git pull
```

## 14. Что нельзя коммитить в git

Никогда не коммить:

- `.env`
- реальные API ключи и пароли
- файлы из `/root/.cloudflared/`
- `cert.pem` от Cloudflare Tunnel
- runtime-логи
- `dashboard/node_modules`
- `dashboard/.next`

С осторожностью коммить:

- `state.json`
- `order_audit.jsonl`
- `performance_journal.json`
- `performance_journal.csv`

Почему с осторожностью:

- это живое состояние и история
- они могут меняться во время работы
- легко случайно перепутать рабочее состояние и тестовое

Обычно правильно:

- хранить код в git
- хранить `.env` отдельно
- хранить runtime отдельно

## 15. Как обновлять сервер, если ты используешь git

Если когда-нибудь на сервере появится реальный git checkout, тогда update flow будет таким:

```bash
cd /opt/asian-breakout
git pull
docker compose up -d --build
```

Но прямо сейчас твой основной способ обновления — это zip-бандл через `build_upload_bundle.ps1`.

## 16. Что менять и где

Если хочешь поменять стратегию:

- смотри `strategy.py`
- смотри `live_bot.py`
- смотри `config.py`
- смотри `.env`

Если хочешь поменять dashboard:

- `dashboard/app/ui/dashboard.tsx`
- `dashboard/app/lib/dashboard-data.ts`
- `dashboard/app/api/live-dashboard/route.ts`

Если хочешь поменять серверный deploy:

- `docker-compose.yml`
- `Dockerfile`
- `dashboard/Dockerfile`
- `scripts/server_install_docker_ubuntu.sh`
- `scripts/server_up.sh`

Если хочешь поменять домен или tunnel:

- `/root/.cloudflared/config.yml` на сервере
- `cloudflare/dead-market-tunnel.linux.yml` в проекте

## 17. Самые частые сценарии

### Изменил только Python-код

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_upload_bundle.ps1
scp -P 23019 .\dist\asian-breakout-upload.zip root@178.160.194.52:/opt/asian-breakout/
```

```bash
cd /opt/asian-breakout
unzip -o asian-breakout-upload.zip
docker compose up -d --build
docker compose logs --tail=50 bot
```

### Изменил dashboard

Делай тот же самый процесс. Docker сам пересоберет frontend.

### Изменил `.env`

На сервере обнови `.env`, потом:

```bash
cd /opt/asian-breakout
docker compose up -d --build
```

### Хочешь убедиться, что бот работает только на сервере

На Windows:

```powershell
.\scripts\stop_dead_market_stack.ps1
```

Потом проверка:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'main.py --env-file .env live|dashboard_live_bridge.py --env-file .env') } | Select-Object ProcessId, Name, CommandLine
```

На сервере:

```bash
cd /opt/asian-breakout
docker compose ps
```

## 18. Полезные файлы

- `README.md`
- `README_RU.md`
- `DOCKER_DEPLOY.md`
- `LIVE_LOCAL_SETUP.md`
- `scripts/build_upload_bundle.ps1`
- `scripts/server_install_docker_ubuntu.sh`
- `scripts/server_up.sh`
- `scripts/server_install_cloudflared_ubuntu.sh`
- `scripts/server_setup_cloudflared.sh`

## 19. Можно ли хранить такой файл в проекте

Да, не просто можно, а желательно.

Это полезно потому что:

- все важные команды лежат рядом с кодом
- при переезде на другой компьютер ничего не теряется
- можно быстро вспомнить команды без переписки
- проще передать проект другому человеку
- это нормальная инженерная практика

Если хочешь, следующий хороший шаг — завести еще и короткий файл типа `QUICK_COMMANDS_RU.md` только с самыми частыми командами в 20 строк.
