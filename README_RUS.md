# pysim-otaman-server

HTTP REST сервер, оборачивающий [pysim](https://osmocom.org/projects/pysim/wiki) для PWA [OTAMan](https://github.com/anttro/otaman).

Предоставляет локальный HTTP API для выполнения команд pysim-shell с SIM/USIM/UICC считывателем.

## Требования

- **Python 3.8+** с `pip`
- **Git**
- **Считыватель смарт-карт (PC/SC или serial/FTDI)** — PC/SC предпочтительнее, требует `pcsc-lite` + `ccid` на Linux

## Быстрый старт

Убедитесь, что Python 3.8+ и Git установлены!

### Linux / macOS

```bash
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server
chmod +x setup.sh start.sh
./setup.sh          # создаёт .venv, устанавливает pysim + сервер (один раз)
./start.sh          # запускает сервер (автоопределение считывателя)
```

### Windows

```cmd
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server
setup.bat           # создаёт .venv, устанавливает pysim + сервер (один раз)
start.bat           # запускает сервер
```

## Скрипты

| Скрипт | Назначение |
|--------|-----------|
| `setup.sh` / `setup.bat` | Создаёт `.venv/`, устанавливает pysim и сервер. Запустить один раз после клонирования. |
| `start.sh` / `start.bat` | Запускает сервер из venv (или глобальной установки). |

### Автоопределение считывателя

Скрипт `start.sh` автоматически определяет считыватель:

- **PC/SC** (Linux): если запущен `pcscd` → передаётся `-p 0`
- **Serial** (Linux): если существует `/dev/ttyUSB0` → передаётся `-d /dev/ttyUSB0`
- **PC/SC** (Windows): всегда использует `-p 0` (PC/SC встроен в Windows)

Если считыватель не обнаружен, сервер запускается без аргументов. Карту можно инициализировать позже кнопкой **Equip** в OTAMan.

## Ручная установка

```bash
# Создать и активировать venv
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Установить pysim
pip install git+https://gitea.osmocom.org/sim-card/pysim.git

# Установить pysim-otaman-server
pip install .

# Запустить сервер
pysim-otaman-server --http-port 8080
```

## Использование

```bash
pysim-otaman-server --http-port 8080
```

Подключите PC/SC считыватель с SIM-картой, затем откройте [http://127.0.0.1:8080](http://127.0.0.1:8080) в браузере.

### Параметры CLI

| Параметр | Описание |
|----------|----------|
| `--http-host` | Адрес привязки (по умолчанию: 127.0.0.1) |
| `--http-port` | TCP порт (по умолчанию: 8080) |
| `-p` / `--pcsc-device` | Номер слота PC/SC считывателя |
| `--pcsc-regex` | Регулярное выражение для имени считывателя |
| `-d` / `--device` | Путь к serial-устройству |
| `-b` / `--baud` | Скорость serial-порта |
| `--modem-device` | Путь к модему |
| `--skip-card-init` | Пропустить инициализацию карты |
| `--apdu-trace` | Логировать APDU-трассировку |
| `--log-requests` | Логировать запросы и ответы |

### Выбор считывателя

Сервер определяет тип считывателя в следующем порядке:

1. **PC/SC** — если указан `--pcsc-device` или `--pcsc-regex`
2. **Serial (Phoenix/Smart Mouse)** — если указан `-d / --device`
3. **Modem AT** — если указан `--modem-device`
4. **Serial fallback** — по умолчанию (`/dev/ttyUSB0`)

## Устранение неполадок

### "Failed to establish context: Access denied" (PC/SC)

Демон `pcscd` не запущен или нет прав:

```bash
# Linux
sudo systemctl enable --now pcscd
sudo usermod -a -G pcscd $USER   # затем выйти и зайти заново
```

### "device file /dev/ttyUSB0 does not exist"

Нет подключённого serial-считывателя и не указан PC/SC. Подключите USB-считыватель или используйте `-d /dev/ttyUSB0 -b 9600`.

### Сервер запущен, но показывает "Reader: none" / "Card: none"

Считыватель не обнаружен при запуске. Нажмите **Equip** в OTAMan для повторной инициализации.

### "Access denied" при установке пакетов

Скрипт установки использует виртуальное окружение (`.venv/`) — права root не требуются.

## Совместимость версий

| Сервер | PWA (OTAMan) | Статус |
|--------|--------------|--------|
| 1.x.x | 1.x.x | ✅ Совместимы |
| 0.x.x | 1.x.x | ❌ Устарел — обновите сервер |
| 2.x.x+ | 1.x.x | ⚠️ Сервер новее — обновите PWA |

Сервер сообщает версию через `GET /api/version`. PWA проверяет версию при подключении.

## API

### `GET /api/version`

Возвращает версию сервера для проверки совместимости.

**Пример ответа:**
```json
{"version": "1.0.0"}
```

### `GET /api/status`

Считыватель, карта, текущий выбор и состояние.

### `GET /api/commands`

Список всех доступных команд shell для текущего профиля карты.

### `POST /api/command`

Выполнить любую команду pysim-shell.

```json
{"cmd": "select MF"}
```

Возвращает:
```json
{"output": "..."}
```

### `POST /api/apdu`

Отправить APDU на карту.

```json
{"apdu": "00A4040000..."}
```

Возвращает:
```json
{"response": "...", "sw": "9000"}
```