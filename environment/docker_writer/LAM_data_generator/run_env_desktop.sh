#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:1
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

xrandr --query
xrandr --output VNC-0 --mode 1920x1080

python /home/headless/LAM_data_generator/env_desktop.py "$@"
