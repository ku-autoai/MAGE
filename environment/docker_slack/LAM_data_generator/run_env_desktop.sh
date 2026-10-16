#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:1
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

for _ in $(seq 1 30); do
    if xrandr --query >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

xrandr --query
if xrandr --query | grep -q '^VNC-0 connected'; then
    xrandr --output VNC-0 --mode 1920x1080
fi

exec python /home/headless/LAM_data_generator/env_desktop.py "$@"
