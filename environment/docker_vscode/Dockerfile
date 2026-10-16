FROM accetto/ubuntu-vnc-xfce-g3:latest

LABEL org.opencontainers.image.title="lam-gui-vscode" \
      org.opencontainers.image.description="Visual Studio Code GUI environment"

USER root

# Install VS Code from Microsoft's official Debian/Ubuntu repository.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    gpg \
    apt-transport-https \
    xdg-utils \
    git \
    python3 python3-venv python3-pip \
    python3-tk python3-dev \
    gnome-screenshot \
    wmctrl \
    fonts-noto-cjk \
    vim \
 && wget -qO /tmp/microsoft.asc https://packages.microsoft.com/keys/microsoft.asc \
 && gpg --dearmor --output /usr/share/keyrings/microsoft.gpg /tmp/microsoft.asc \
 && printf '%s\n' \
    'Types: deb' \
    'URIs: https://packages.microsoft.com/repos/code' \
    'Suites: stable' \
    'Components: main' \
    'Architectures: amd64 arm64 armhf' \
    'Signed-By: /usr/share/keyrings/microsoft.gpg' \
    > /etc/apt/sources.list.d/vscode.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends code \
 && rm -f /tmp/microsoft.asc \
 && rm -rf /var/lib/apt/lists/*

# Electron's Chromium sandbox and GPU acceleration are commonly unavailable in
# a VNC container. Keep those container-specific flags out of user commands.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec /usr/bin/code --no-sandbox --disable-gpu "$@"' \
    > /usr/local/bin/code-container \
 && chmod +x /usr/local/bin/code-container

RUN mkdir -p /home/headless/Desktop \
             /home/headless/.local/share/applications \
             /home/headless/.config/Code \
             /home/headless/.config/autostart \
             /home/headless/.vscode \
             /home/headless/workspace \
 && chown -R headless:headless /home/headless

COPY --chown=root:root workspace/ /opt/vscode-workspace-seed/

USER headless
WORKDIR /home/headless

RUN printf '%s\n' \
    '[Desktop Entry]' \
    'Type=Application' \
    'Version=1.0' \
    'Name=Visual Studio Code' \
    'Comment=Code Editor' \
    'Exec=/usr/local/bin/code-container /home/headless/workspace' \
    'Icon=com.visualstudio.code' \
    'Terminal=false' \
    'Categories=Development;IDE;TextEditor;' \
    'StartupNotify=true' \
    > /home/headless/Desktop/visual-studio-code.desktop \
 && cp /home/headless/Desktop/visual-studio-code.desktop \
       /home/headless/.local/share/applications/visual-studio-code.desktop \
 && chmod +x /home/headless/Desktop/visual-studio-code.desktop \
             /home/headless/.local/share/applications/visual-studio-code.desktop

# Start the socket client after the XFCE/VNC session becomes available.
RUN printf '%s\n' \
    '[Desktop Entry]' \
    'Type=Application' \
    'Version=1.0' \
    'Name=VS Code Agent Client' \
    'Exec=/home/headless/LAM_data_generator/run_env_desktop.sh' \
    'Terminal=false' \
    'OnlyShowIn=XFCE;' \
    'X-GNOME-Autostart-enabled=true' \
    > /home/headless/.config/autostart/lam-vscode-agent.desktop

RUN python3 -m venv /home/headless/venv
ENV PATH="/home/headless/venv/bin:${PATH}"

RUN pip install --no-cache-dir -U \
    pyautogui \
    pyscreeze \
    "Pillow>=9.2.0"

COPY --chown=headless:headless workspace/ /home/headless/workspace/

WORKDIR /home/headless/LAM_data_generator
COPY --chown=headless:headless LAM_data_generator/ /home/headless/LAM_data_generator/
RUN chmod +x /home/headless/LAM_data_generator/run_env_desktop.sh
