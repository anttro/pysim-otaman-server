# pysim-otaman-server

HTTP REST сервер, оборачивающий [pysim](https://osmocom.org/projects/pysim/wiki) для PWA [OTAMan](https://github.com/anttro/otaman).

Предоставляет локальный HTTP API для выполнения команд pysim-shell с SIM/USIM/UICC считывателем, отправки OTA-команд (SCP80) и навигации по SIM Toolkit меню.

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
| `--skip-card-init` | Пропустить инициализацию карты (устарело — используйте `--no-card-init`) |
| `--no-card-init` | Пропустить инициализацию pysim для сохранения CAT-сессии; без файлового менеджера |
| `--apdu-trace` | Логировать APDU-трассировку |
| `--log-requests` | Логировать запросы и ответы |
| `--sms-oa` | TP-Originating-Address в SMS-DELIVER TPDU (по умолчанию: `12345`) |
| `--sms-sm-sc` | SM-SC адрес для PoR-in-submit маршрутизации (по умолчанию: `12345678912`) |
| `--terminal-profile` | TERMINAL PROFILE в hex, отправляемый при старте (по умолчанию: все FF, 32 байта) |

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

## SCP80 OTA

Сервер поддерживает отправку OTA-команд на SIM/USIM/UICC карты по протоколу
SCP80 (ETSI TS 102 225, 3GPP TS 31.115) через SMS-PP-DOWNLOAD ENVELOPE
с использованием PC/SC считывателя.

### Обзор

1. **Сгенерировать защищённый пакет** во вкладке *Secured Packet* PWA OTAMan —
   указать ключи KIc/KID, TAR, счётчик, SPI и APDU.
2. **Сверить** пакет с эталоном pySim через API `sp-verify` или кнопку
   *Verify vs pySim* в PWA.
3. **Отправить** через `/api/send-ota`. Сервер упаковывает пакет в
   SMS-DELIVER TPDU с CPI (`70 00`) в User Data Header и отправляет
   карте командой `ENVELOPE(SMS-PP-DOWNLOAD)`.
4. **Декодировать PoR** — подтверждение приёма возвращается либо в ответе
   ENVELOPE (режим delivery-report), либо через проактивную команду FETCH
   с SUBMIT-SM (режим submit, бит SPI2 0x20).

### Ключевой материал

| Параметр | Поле ENVELOPE | Описание |
|---|---|---|
| KIc / KID | индикатор ключа и алгоритма | напр. `15` = индекс 1, triple-DES-CBC2 |
| kicKey / kidKey | 16- или 24-байтные ключи в hex | должны совпадать с OTA-ключами карты |
| TAR | 3-байтный Toolkit Application Reference | напр. `b00000` |
| SPI1 / SPI2 | Security Parameter Indicators | шифрование, CC, режим PoR |
| Счётчик | 5-байтный big-endian счётчик | должен быть строго больше, чем на карте |
| APDU | hex | команда, выполняемая картой (напр. `00a40000023f00`) |

### Режимы PoR

- **Delivery report** (бит SPI2 0x20 сброшен) — PoR приходит в ответе
  ENVELOPE. Сервер выполняет `GET RESPONSE` (`61XX`).
- **Submit SM** (бит SPI2 0x20 установлен) — карта отправляет PoR в
  SMS-SUBMIT через проактивную команду. Сервер извлекает её командой
  `FETCH` (`80 12`), отправляет `TERMINAL RESPONSE` и декодирует PoR
  из SMS TPDU. Если ENVELOPE не сигнализирует о pending-команде,
  выполняется проактивный опрос через `STATUS` (`80 F2`).

### Пример

```bash
# Генерация эталона и сверка
curl -s http://127.0.0.1:8080/api/sp-verify -X POST -d '{
  "spi1":"16","spi2":"01","kic":"15","kid":"15","tar":"b00000",
  "cntr":"0000000001","apdu":"00a40000023f00",
  "kicKey":"D6FCC0...","kidKey":"1B07E7..."
}'

# Отправка OTA-команды
curl -s http://127.0.0.1:8080/api/send-ota -X POST -d '{
  "sp":"00201516011515...","spi1":"16","spi2":"01",
  "kic":"15","kid":"15","cntr":"0000000001",
  "kicKey":"D6FCC0...","kidKey":"1B07E7..."
}'
```

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

### `POST /api/help`

Структурированная справка по команде shell.

```json
{"cmd": "apdu"}
```

Возвращает:
```json
{"usage": "apdu [-h] [--expect-sw EXPECT_SW] [--raw] APDU", "description": "...", "args": [{"name": "APDU", "type": "positional", "help": "..."}]}
```

### `POST /api/send-ota`

Отправка OTA-команды (SCP80) на карту через SMS-PP-DOWNLOAD ENVELOPE.
Защищённый пакет помещается в SMS-DELIVER TPDU с CPI (`70 00`) в UDH
и доставляется командой `ENVELOPE(SMS-PP-DOWNLOAD)`.

**Тело запроса:**
```json
{
  "sp": "00201516011515b00000...",
  "spi1": "16", "spi2": "01",
  "kic": "15", "kid": "15",
  "tar": "b00000", "cntr": "0000000001",
  "kicKey": "D6FCC0...", "kidKey": "1B07E7..."
}
```

**Ответ (PoR в delivery report):**
```json
{"success": true, "sw": "9000", "response_data": "027100000e0a...",
 "por": {"response_status": "por_ok", "tar": "B00000",
         "decoded": {"last_status_word": "6e00", ...}}}
```

**Ответ (PoR в submit SM):** PoR извлекается из SMS-SUBMIT TPDU,
полученного через проактивную команду FETCH. Структура `por` такая же.

Бит SPI2 `por_in_submit` (0x20) выбирает режим submit.

### `POST /api/sp-verify`

Сверка защищённого пакета с эталоном pySim (`OtaDialectSms.encode_cmd`).

```json
{"spi1": "16", "spi2": "01", "kic": "15", "kid": "15",
 "tar": "b00000", "cntr": "0000000001", "apdu": "00a40000023f00",
 "kicKey": "D6FCC0...", "kidKey": "1B07E7..."}
```

**Ответ:**
```json
{"js_sp": "...", "py_sp": "...", "match": true,
 "diffs": [], "spi": {"counter": "counter_must_be_higher", ...}}
```

### `GET /api/menu`

Возвращает SETUP MENU SIM Toolkit, полученный от карты в ответ на TERMINAL PROFILE.
Пустой `{"items": []}` — карта не отправила меню.

**Ответ:**
```json
{"command_number": 1, "items": [{"id": 128, "text": "Настройки/Settings"}],
 "title": "Alfa Mobile", "active": false}
```

### `POST /api/menu-select`

Отправляет `ENVELOPE(MENU SELECTION)` с выбранным ID элемента меню,
затем обрабатывает проактивный ответ карты (DISPLAY TEXT или SELECT ITEM).

```json
{"item_id": 128}
```

**Ответ:**
```json
{"type": "display_text", "text": "Здравствуйте", "sw": "9122"}
```
или
```json
{"type": "select_item", "items": [{"id": 1, "text": "Подменю"}], "sw": "9122"}
```

### `POST /api/menu-respond`

Отправляет `TERMINAL RESPONSE` на текущую проактивную команду с указанным
кодом результата. Продолжает цепочку проактивных команд при ответе `91XX`.

```json
{"result": "ok", "item_id": 1}
```

| `result` | Код TERMINAL RESPONSE | Значение |
|---|---|---|
| `ok` | `0x00` | Команда выполнена успешно |
| `back` | `0x12` | Назад |
| `cancel` | `0x10` | Проактивная сессия завершена |
| `timeout` | `0x11` | Нет ответа от пользователя |

### `GET /api/stk-status`

Возвращает текущее состояние STK-сессии.
```json
{"active": true, "pending": true, "pending_type": "select_item"}
```

### `POST /api/read`

Чтение содержимого файла. Автоопределение transparent/record.

```json
{"name": "EF.ICCID", "fid": "2FE2", "parent_sel": "3F00", "mode": "raw"}
```

Возвращает:
```json
{"success": true, "sw": "9000", "file_type": "transparent", "data": "..."}
```

### `POST /api/write`

Запись hex-данных в файл.

```json
{"name": "EF.ICCID", "fid": "2FE2", "data": "A0A1A2...", "parent_sel": "3F00"}
```

Для record-файлов:
```json
{"name": "EF.ADN", "fid": "6F3A", "data": "A0A1...", "record_nr": 1, "parent_sel": "7F10"}
```

Возвращает:
```json
{"success": true, "sw": "9000"}
```

### `POST /api/select`

Выбор файла по имени или FID, с опциональным выбором родителя.

```json
{"name": "EF.ICCID", "fid": "2FE2", "parent_sel": "3F00"}
```

Возвращает:
```json
{"name": "EF.ICCID", "fid": "2FE2", "file_type": "transparent", "exists": true}
```

### `POST /api/tree`

Получение списка файлов в директории.

```json
{"name": "MF", "fid": "3F00"}
```

Возвращает:
```json
{"exists": true, "name": "MF", "fid": "3F00", "file_type": "df", "children": [{"name": "EF.ICCID", "fid": "2fe2", "isDir": false}]}