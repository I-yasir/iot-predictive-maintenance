# ESP32 synthetic telemetry streamer (Mode 2)

This firmware turns an ESP32 into a stand-in for an engine's sensor gateway. It reads **no physical
sensors**. Each second it generates one operating cycle of C-MAPSS-like data from a profile exported from the
dataset, and sends it over Wi-Fi to the same MQTT broker and contract (`TelemetryPayload v1`) that the
replay simulator and the backend use.

| Mode | What it streams |
|---|---|
| `PDM_MODE_TRAJECTORY` (default) | FD001 **test** unit 34 (never seen in training): 203 cycles plus small Gaussian noise. True RUL at the end is 7, so the dashboard should reach Critical. |
| `PDM_MODE_DISTRIBUTION` | A new engine every life: lifetime drawn from the training-life distribution, each sensor = healthy mean + average degradation drift for the remaining cycles + measurement noise. |

Every message carries `meta.true_rul`, so predicted and true RUL can be compared live.

## What you need

- An ESP32 dev board (ESP32-DevKitC / "ESP32 DEVKIT V1" / NodeMCU-32S, any with 4 MB flash) and a USB **data** cable.
- A 2.4 GHz Wi-Fi network that the board and your PC are both on (ESP32 has no 5 GHz radio).
- The PC running the broker: `docker compose up -d mosquitto` from the repo root.

## 1. Create the device's broker user

The broker ACL only lets a device publish to `pdm/v1/<site>/<its own username>/telemetry`, so the MQTT
username **must equal the asset id**.

```bash
cp .env.example .env                    # once; then edit every password
# set ESP32_ASSET_ID=FD001-E001 and MQTT_DEVICE_PASSWORD in .env
sh config/mosquitto/make_passwd.sh      # rewrites config/mosquitto/passwd from .env
docker compose restart mosquitto
```

## 2. Configure the firmware

```bash
cp iot/esp32/include/config.example.h iot/esp32/include/config.h   # config.h is gitignored
```

Edit `config.h`: `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_HOST` (your PC's LAN IP, e.g. from `ip addr` or
`ipconfig`, not `localhost`), `MQTT_PASSWORD`, `ASSET_ID` (same as `ESP32_ASSET_ID`). Leave `GEN_SEED 0`
to derive the seed from the chip's MAC address.

## 3a. Flash with PlatformIO (recommended)

```bash
pip install platformio==6.1.18
cd iot/esp32
pio run                 # build (downloads the ESP32 toolchain on first run, about 5 minutes)
pio run -t upload       # flash; hold BOOT if it sits at "Connecting...."
pio device monitor      # 115200 baud
```

## 3b. Flash with the Arduino IDE

1. Boards Manager: install **esp32 by Espressif** 2.0.x (PlatformIO's espressif32 6.10.0 uses Arduino core 2.0.17).
2. Library Manager: install **PubSubClient 2.8** and **ArduinoJson 7.4.1**.
3. Create a sketch folder `pdm_esp32/`, copy `src/main.cpp` in as `pdm_esp32.ino`, and copy every file in
   `include/` (including your `config.h`) next to it.
4. Board: *ESP32 Dev Module*. Upload, then open the Serial Monitor at 115200.

## 4. Check it end to end

On the board's serial log you should see the state machine reach `STREAMING`, then a line every 10 messages:

```
[    4211] state BROKER_CONNECTING -> STREAMING
[   14230] seq 10 cycle 10 true_rul 200 | sent 10 acks 0 buffered 0 dropped 0 | STREAMING
```

On the PC, the harness checks schema, rate, sequence gaps and latency against the real device:

```bash
set -a; . ./.env; set +a
pdm-harness --listen 120 --asset FD001-E001 --rate 1     # writes reports/mode2_<time>.md
```

`acks` stays at 0 until the backend (Phase 3) is running, or until the harness's echo-ack stub is on.

## Behaviour

| State | LED | Meaning |
|---|---|---|
| `WIFI_CONNECTING` | slow blink | joining Wi-Fi, exponential backoff 1 s to 30 s |
| `NTP_SYNC` | | getting the time for `ts` (if it fails, `ts` is omitted and the server stamps it) |
| `BROKER_CONNECTING` | fast blink | MQTT connect with a retained LWT `{"online":false}` on `.../status` |
| `STREAMING` | solid | one message per `PUBLISH_INTERVAL_MS` |
| `BUFFERING` | double blink | link down: messages go to a 64-message ring buffer, flushed in order on reconnect; the oldest is overwritten if it fills, and the harness reports the seq gap |
| `HTTP_FALLBACK` | double blink | after 5 failed broker connects, POST to `HTTP_INGEST_URL`; MQTT is retried every 60 s |
| `END_OF_LIFE_IDLE` | off | life finished and `LOOP_LIFE 0` |

MQTT publishes are QoS 0 because PubSubClient cannot publish QoS 1. Delivery gaps are visible through `seq`.

## Same numbers everywhere

`include/pdm_generator.h` is plain C++ shared by the firmware and a host test; `pdm_iot/simulator/virtual_esp32.py`
mirrors it line for line. For the same seed all three give identical values (checked in
`iot/tests/test_virtual_esp32.py`). So any Mode 2 test can run in CI with the virtual device and give the
same stream a board would.

Regenerate the profile after the dataset or exporter changes:

```bash
pdm-export-esp32-profile --profile FD001     # writes include/profile_fd001.h and profile_fd001.json
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Stuck in `WIFI_CONNECTING` | 2.4 GHz network? SSID/password case? Some guest networks block device-to-device traffic. |
| `MQTT connect failed, rc=5` | Not authorised: username must equal `ASSET_ID`, password must match `.env`, rerun `make_passwd.sh` and restart mosquitto. |
| `rc=-2` | Can't reach the broker: wrong `MQTT_HOST`, or the PC firewall blocks port 1883. |
| Connected but nothing arrives at the harness | `SITE_ID` differs from the harness `--site`, or the ACL username/asset mismatch silently drops publishes. |
| Upload sits at `Connecting....` | Hold BOOT while it connects; try another (data) USB cable; install the CP210x or CH340 driver. |
| Garbage on serial | Monitor speed must be 115200. |
