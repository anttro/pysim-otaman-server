# pysim-otaman-server

HTTP REST server wrapping [pysim](https://osmocom.org/projects/pysim/wiki) for the [OTAMan](https://github.com/anttro/otaman) PWA.

Exposes a local HTTP API to execute pysim-shell commands against a SIM/USIM/UICC card reader, send OTA commands (SCP80), and browse the SIM Toolkit menu.

## Prerequisites

- **Python 3.8+** with `pip`
- **Git**
- **Smart card reader (PC/SC or serial/FTDI) ** — PC/SC is preferable, requires `pcsc-lite` + `ccid` on Linux
- **Windows only** — use **Python 3.10–3.13** (3.13 recommended): `pyscard` (the PC/SC driver wrapper) ships precompiled wheels for these versions. On Python 3.9 / 3.14 pip builds `pyscard` from source, which requires Microsoft C++ Build Tools ("Desktop development with C++").

## Quick start

Make sure you have Python 3.8+ and Git installed!

### Linux / macOS

```bash
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server
chmod +x setup.sh start.sh
./setup.sh          # creates .venv, installs pysim + server (run once)
./start.sh          # starts the server (auto-detects reader)
```

### Windows

```cmd
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server
setup.bat           # creates .venv, installs pysim + server (run once)
start.bat           # starts the server
```

## Scripts

| Script | What it does |
|--------|-------------|
| `setup.sh` / `setup.bat` | Creates `.venv/`, installs pysim and the server. Run once after cloning. |
| `start.sh` / `start.bat` | Starts the server from the venv (or falls back to global install). |

### Reader auto-detection

The `start.sh` script auto-detects the reader:

- **PC/SC** (Linux): if `pcscd` daemon is running → passes `-p 0`
- **Serial** (Linux): if `/dev/ttyUSB0` exists → passes `-d /dev/ttyUSB0`
- **PC/SC** (Windows): always uses `-p 0` (PC/SC is built into Windows)

If no reader is detected, the server starts without reader arguments and shows "Reader: none" in the status. The card can be initialized later via the **Equip** button in the OTAMan PWA.

## Manual installation

```bash
# Create and activate a venv
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install pysim
pip install git+https://github.com/osmocom/pysim.git

# Install pysim-otaman-server
pip install .

# Start the server
pysim-otaman-server --http-port 8080
```

## Usage

```bash
pysim-otaman-server --http-port 8080
```

Connect a PC/SC reader with a SIM card, then open [http://127.0.0.1:8080](http://127.0.0.1:8080) in your browser.

### CLI options

| Option | Description |
|--------|-------------|
| `--http-host` | Bind address (default: 127.0.0.1) |
| `--http-port` | TCP port (default: 8080) |
| `-p` / `--pcsc-device` | PC/SC reader slot number |
| `--pcsc-regex` | PC/SC reader name regex |
| `-d` / `--device` | Serial device path |
| `-b` / `--baud` | Serial baud rate |
| `--modem-device` | Modem device path |
| `--skip-card-init` | Skip card initialization (deprecated — use `--no-card-init`) |
| `--no-card-init` | Skip pysim card initialization to preserve CAT session; no file manager |
| `--apdu-trace` | Log APDU-level traces to stderr |
| `--log-requests` | Log request/response payloads to stderr |
| `--sms-oa` | TP-Originating-Address in SMS-DELIVER TPDU (default: `12345`) |
| `--sms-sm-sc` | SM-SC address for PoR-in-submit routing (default: `12345678912`) |
| `--terminal-profile` | TERMINAL PROFILE payload hex sent at startup (default: 10-byte GSM profile with SMS-PP download) |

### Reader selection

The server auto-detects the reader type in this order:

1. **PC/SC** — if `--pcsc-device` or `--pcsc-regex` is specified
2. **Serial (Phoenix/Smart Mouse)** — if `-d` / `--device` is specified
3. **Modem AT** — if `--modem-device` is specified
4. **Serial fallback** — default if nothing else matches (`/dev/ttyUSB0`)

The `start.sh` script adds auto-detection on top of this: it checks for a running `pcscd` daemon or a connected `ttyUSB0` device and passes the appropriate flags.

## Troubleshooting

### "Failed to establish context: Access denied" (PC/SC)

The `pcscd` daemon is not running or your user doesn't have permission:

```bash
# Linux
sudo systemctl enable --now pcscd
sudo usermod -a -G pcscd $USER   # then log out and back in
```

### "device file /dev/ttyUSB0 does not exist"

No serial reader connected and no PC/SC reader specified. Either:
- Connect a USB smart card reader and install `pcsc-lite` + `ccid`
- Or specify a serial reader explicitly: `-d /dev/ttyUSB0 -b 9600`
- The server will still start without a reader (use **Equip** in the PWA later)

### Server starts but shows "Reader: none" / "Card: none"

The server is running but no card reader was detected at startup. Click **Equip** in the OTAMan PWA's pySim tab to re-initialize the card, or restart the server with the correct reader flags.

### "Access denied" when installing packages

The setup script installs packages inside a virtual environment (`.venv/`) — no root permissions needed. If you're installing manually, make sure you're using a venv or add `--user` to pip:

```bash
pip install --user pysim-otaman-server
```

## SCP80 OTA

The server supports sending OTA commands to SIM/USIM/UICC cards using the
SCP80 protocol (ETSI TS 102 225, 3GPP TS 31.115) over an SMS-PP-DOWNLOAD
ENVELOPE delivered via a PC/SC card reader.

### Overview

1. **Generate a secured packet** in the OTAMan PWA's *Secured Packet* tab —
   provide KIc/KID keys, TAR, counter, SPI, and an APDU.
2. **Cross-verify** the packet against pySim's reference implementation
   with the `sp-verify` API or the PWA's *Verify vs pySim* button.
3. **Send** the packet via `/api/send-ota`. The server wraps it in an
   SMS-DELIVER TPDU with CPI (`70 00`) in the User Data Header and delivers
   it to the card via an `ENVELOPE(SMS-PP-DOWNLOAD)` APDU.
4. **Decode the PoR** — the proof-of-receipt is returned either in the
   ENVELOPE response data (delivery-report mode) or via a proactive
   FETCH of a SUBMIT‑SM (submit mode, SPI2 bit 0x20).

### Key material

| Parameter | ENVELOPE field | Notes |
|---|---|---|
| KIc / KID | Key and algorithm indicator | e.g. `15` = index 1, triple‑DES‑CBC2 |
| kicKey / kidKey | 16‑ or 24‑byte hex keys | must match the card's OTA key set |
| TAR | 3‑byte Toolkit Application Reference | e.g. `b00000` |
| SPI1 / SPI2 | Security Parameter Indicators | controls ciphering, CC, PoR mode |
| Counter | 5‑byte big‑endian counter | must be strictly higher than the card's |
| APDU | hex | the command the card executes (e.g. `00a40000023f00`) |

### PoR modes

- **Delivery report** (SPI2 bit 0x20 clear) — the PoR arrives in the
  ENVELOPE response data. The server issues `GET RESPONSE` (`61XX`).
- **Submit SM** (SPI2 bit 0x20 set) — the card sends the PoR as an
  SMS‑SUBMIT via a proactive command. The server fetches it with
  `FETCH` (`80 12`), sends `TERMINAL RESPONSE`, and decodes the PoR
  from the SMS TPDU. Proactive polling with `STATUS` (`80 F2`) is
  performed if the ENVELOPE itself does not signal a pending command.

### Example

```bash
# Generate a reference and cross-check
curl -s http://127.0.0.1:8080/api/sp-verify -X POST -d '{
  "spi1":"16","spi2":"01","kic":"15","kid":"15","tar":"b00000",
  "cntr":"0000000001","apdu":"00a40000023f00",
  "kicKey":"D6FCC0...","kidKey":"1B07E7..."
}'

# Send the OTA command
curl -s http://127.0.0.1:8080/api/send-ota -X POST -d '{
  "sp":"00201516011515...","spi1":"16","spi2":"01",
  "kic":"15","kid":"15","cntr":"0000000001",
  "kicKey":"D6FCC0...","kidKey":"1B07E7..."
}'
```

## Proactive UICC / CAT (Card Application Toolkit)

The server implements a full CAT session with TERMINAL PROFILE, proactive command
chain handling, STATUS polling, SIM Toolkit menu browsing, event download, and a
PROVIDE LOCAL INFORMATION data dictionary.

### Proactive command log

`GET /api/proactive-log` returns the last 50 encountered proactive commands in
the current session, each with its type hex code, human-readable name, seconds
elapsed since equip/reset, and byte count. Cleared on card equip and rescue.

### Event download

`POST /api/event-send` sends an `ENVELOPE(Event Download)` for a given event
type with optional event-specific data (location info, access technology, etc.).
The OTAMan PWA provides per-event forms with structured inputs and a full
Network Rejection form with 53-cause unified dropdown.

### PLI data dictionary

The server stores a PROVIDE LOCAL INFORMATION response data dictionary — hex
values for each of the 22 PLI qualifier codes defined by TS 102 223 and
TS 131 111. These values persist in memory until server restart (not cleared on
equip/reset). The OTAMan PWA provides per-qualifier decode/encode forms.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pli-qualifiers` | GET | List of qualifier codes with descriptions |
| `/api/pli-dict` | GET | Current dictionary (hex values per qualifier) |
| `/api/pli-dict` | POST | Update dictionary entries |

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events` | GET | Event list from SET UP EVENT LIST |
| `/api/event-send` | POST | Send ENVELOPE(Event Download) |
| `/api/proactive-log` | GET | Last 50 proactive commands |
| `/api/status-poll` | POST | Manual STATUS poll + FETCH if 91XX |
| `/api/rescue` | POST | Re-send TERMINAL PROFILE to recover CAT session |

## Version compatibility

| Server | PWA (OTAMan) | Status |
|--------|-------------|--------|
| 1.x.x | 1.x.x | ✅ Compatible |
| 0.x.x | 1.x.x | ❌ Outdated — update server |
| 2.x.x+ | 1.x.x | ⚠️ Server newer — update PWA |

The server reports its version via `GET /api/version`. The PWA checks this on connect and warns if versions are incompatible.

## API

### `GET /api/version`

Returns server version for compatibility checking.

**Example response:**
```json
{"version": "1.0.0"}
```

### `GET /api/status`

Card reader, card type, current selection, and card state.

### `GET /api/commands`

List all available shell commands for the current card profile.

### `POST /api/command`

Execute any pysim-shell command.

```json
{"cmd": "select MF"}
```

Returns:

```json
{"output": "..."}
```

### `POST /api/apdu`

Send a raw APDU to the card.

```json
{"apdu": "00A4040000..."}
```

Returns:

```json
{"response": "...", "sw": "9000"}
```

### `POST /api/help`

Get structured help for a shell command.

```json
{"cmd": "apdu"}
```

Returns:
```json
{"usage": "apdu [-h] [--expect-sw EXPECT_SW] [--raw] APDU", "description": "...", "args": [{"name": "APDU", "type": "positional", "help": "..."}]}
```

### `POST /api/send-ota`

Send an OTA command (SCP80) to the card via SMS-PP-DOWNLOAD ENVELOPE.
The secured packet is delivered in an SMS-DELIVER TPDU wrapped in an ENVELOPE command.

**Request body:**
```json
{
  "sp": "00201516011515b00000...",
  "spi1": "16",
  "spi2": "01",
  "kic": "15",
  "kid": "15",
  "tar": "b00000",
  "cntr": "0000000001",
  "kicKey": "D6FCC023...",
  "kidKey": "1B07E7E0..."
}
```

**Response (delivery PoR):**
```json
{"success": true, "sw": "9000", "response_data": "027100000e0a...",
 "por": {"response_status": "por_ok", "tar": "B00000", "pcntr": 0,
         "decoded": {"number_of_commands": 1, "last_status_word": "6e00",
                      "last_response_data": ""}}}
```

**Response (submit PoR):** PoR is extracted from the SMS-SUBMIT TPDU
fetched via a proactive command (FETCH). The response contains the
same `por` structure if decoding succeeds.

The SPI2 `por_in_submit` bit (0x20) selects submit-mode PoR.

### `POST /api/sp-verify`

Cross-check a secured packet against pySim's `OtaDialectSms.encode_cmd`
reference. Returns the JS-generated packet, pySim reference, a match flag,
and the decoded SPI fields.

```json
{"spi1": "16", "spi2": "01", "kic": "15", "kid": "15", "tar": "b00000",
 "cntr": "0000000001", "apdu": "00a40000023f00",
 "kicKey": "D6FCC023...", "kidKey": "1B07E7E0..."}
```

**Response:**
```json
{"js_sp": "...", "py_sp": "...", "match": true,
 "diffs": [], "spi": {"counter": "counter_must_be_higher", ...}}
```

### `GET /api/menu`

Returns the SIM Toolkit SETUP MENU captured from the card's TERMINAL PROFILE
response at startup. Empty `{"items": []}` if the card didn't send a menu.

**Response:**
```json
{"command_number": 1, "items": [{"id": 128, "text": "Настройки/Settings"}],
 "title": "Alfa Mobile", "active": false}
```

### `POST /api/menu-select`

Sends an `ENVELOPE(MENU SELECTION)` with the selected item ID, then handles
the card's proactive response (DISPLAY TEXT or SELECT ITEM).

```json
{"item_id": 128}
```

**Response:**
```json
{"type": "display_text", "text": "Hello", "sw": "9122"}
```
or
```json
{"type": "select_item", "items": [{"id": 1, "text": "Sub-menu"}], "sw": "9122"}
```

### `POST /api/menu-respond`

Sends `TERMINAL RESPONSE` to the current proactive command with the given result
code. Continues the proactive chain if the card responds with `91XX`.

```json
{"result": "ok", "item_id": 1}
```

| `result` | TERMINAL RESPONSE code | Meaning |
|---|---|---|
| `ok` | `0x00` | Command performed successfully |
| `back` | `0x12` | Backward move requested |
| `cancel` | `0x10` | Proactive session terminated |
| `timeout` | `0x11` | No response from user |

### `GET /api/stk-status`

Returns the current STK session state.
```json
{"active": true, "pending": true, "pending_type": "select_item"}
```

### `POST /api/read`

Read file content. Auto-detects transparent vs record files.

```json
{"name": "EF.ICCID", "fid": "2FE2", "parent_sel": "3F00", "mode": "raw"}
```

Returns:
```json
{"success": true, "sw": "9000", "file_type": "transparent", "data": "..."}
```

### `POST /api/write`

Write raw hex data to a file.

```json
{"name": "EF.ICCID", "fid": "2FE2", "data": "A0A1A2...", "parent_sel": "3F00"}
```

For record files:
```json
{"name": "EF.ADN", "fid": "6F3A", "data": "A0A1...", "record_nr": 1, "parent_sel": "7F10"}
```

Returns:
```json
{"success": true, "sw": "9000"}
```

### `POST /api/select`

Select a file by name or FID, with optional parent selection.

```json
{"name": "EF.ICCID", "fid": "2FE2", "parent_sel": "3F00"}
```

Returns:
```json
{"name": "EF.ICCID", "fid": "2FE2", "file_type": "transparent", "exists": true}
```

### `POST /api/tree`

Get directory listing with typed children.

```json
{"name": "MF", "fid": "3F00"}
```

Returns:
```json
{"exists": true, "name": "MF", "fid": "3F00", "file_type": "df", "children": [{"name": "EF.ICCID", "fid": "2fe2", "isDir": false}]}
