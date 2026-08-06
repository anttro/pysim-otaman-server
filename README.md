# pysim-otaman-server

HTTP REST server wrapping [pysim](https://osmocom.org/projects/pysim/wiki) for the [OTAMan](https://github.com/anttro/otaman) PWA.

Exposes a local HTTP API to execute pysim-shell commands against a SIM/USIM/UICC card reader.

## Prerequisites

- **Python 3.8+** with `pip`
- **Git**
- **PC/SC smart card reader** (optional, for PC/SC transport) — requires `pcsc-lite` + `ccid` on Linux
- **Serial/FTDI reader** (optional, for serial transport)

## Quick start

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
pip install git+https://gitea.osmocom.org/sim-card/pysim.git

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
| `--skip-card-init` | Skip card initialization |
| `--apdu-trace` | Log APDU-level traces to stderr |
| `--log-requests` | Log request/response payloads to stderr |

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

## API

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