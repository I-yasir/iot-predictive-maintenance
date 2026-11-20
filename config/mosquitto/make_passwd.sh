#!/usr/bin/env sh
# Create/refresh config/mosquitto/passwd from .env (never commit the result).
# Usage: sh config/mosquitto/make_passwd.sh [extra_device_user:password ...]
set -eu
cd "$(dirname "$0")/../.."
[ -f .env ] || { echo "copy .env.example to .env first"; exit 1; }
set -a; . ./.env; set +a
: > config/mosquitto/passwd
add() { docker run --rm -v "$PWD/config/mosquitto:/m" eclipse-mosquitto:2.0.21 mosquitto_passwd -b /m/passwd "$1" "$2" 2>/dev/null; }
add pdm-backend "$MQTT_BACKEND_PASSWORD"
add pdm-replay "$MQTT_REPLAY_PASSWORD"
add pdm-harness "$MQTT_HARNESS_PASSWORD"
add "$ESP32_ASSET_ID" "$MQTT_DEVICE_PASSWORD"
for pair in "$@"; do add "${pair%%:*}" "${pair#*:}"; done
# the broker runs as uid 1883 and requires a private password file
docker run --rm -v "$PWD/config/mosquitto:/m" eclipse-mosquitto:2.0.21 sh -c 'chown 1883:1883 /m/passwd && chmod 0700 /m/passwd'
echo "wrote config/mosquitto/passwd"
