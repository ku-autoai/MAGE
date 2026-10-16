#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

for _ in $(seq 1 120); do
    if [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ] && xrandr --query >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! xrandr --query; then
    echo "Display ${DISPLAY} did not become ready." >&2
    if [ -f /dockerstartup/vnc.log ]; then
        tail -n 80 /dockerstartup/vnc.log >&2
    fi
    exit 1
fi
if xrandr --query | grep -q '^VNC-0 connected'; then
    xrandr --output VNC-0 --mode 1920x1080
fi

python /home/headless/LAM_data_generator/env_desktop.py "$@"
