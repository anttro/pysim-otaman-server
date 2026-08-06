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
# Clone the repo
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server

# Run the setup script
chmod +x setup.sh
./setup.sh
```

### Windows

```cmd
git clone https://github.com/anttro/pysim-otaman-server.git
cd pysim-otaman-server
setup.bat
```

## Manual installation

### 1. Install pysim

```bash
pip install pysim
```

If pysim is not available on PyPI, install from the Osmocom repository:

```bash
pip install git+https://gitea.osmocom.org/sim-card/pysim.git
```

### 2. Install pysim-otaman-server

```bash
pip install .
```

### 3. Start the server

```bash
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

### Reader selection

The server auto-detects the reader type in this order:

1. **PC/SC** — if `--pcsc-device` or `--pcsc-regex` is specified
2. **Serial (Phoenix/Smart Mouse)** — if `-d` / `--device` is specified
3. **Modem AT** — if `--modem-device` is specified
4. **Serial fallback** — default if nothing else matches (`/dev/ttyUSB0`)

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