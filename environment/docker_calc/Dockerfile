FROM accetto/ubuntu-vnc-xfce-g3:latest

LABEL org.opencontainers.image.title="lam-gui-calc" \
      org.opencontainers.image.description="LibreOffice Calc GUI environment"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice libreoffice-calc \
    python3 python3-venv python3-pip \
    python3-tk python3-dev \
    gnome-screenshot \
    wmctrl \
    vim \
 && rm -rf /var/lib/apt/lists/*

# (root) ensure home exists and is writable by headless
RUN mkdir -p /home/headless && chown -R headless:headless /home/headless

USER headless
WORKDIR /home/headless

# Desktop shortcut for LibreOffice Calc (no heredoc; sh-safe)
RUN mkdir -p /home/headless/Desktop /home/headless/.local/share/applications && \
    printf '%s\n' \
'[Desktop Entry]' \
'Type=Application' \
'Version=1.0' \
'Name=LibreOffice Calc' \
'Comment=Spreadsheet' \
'Exec=libreoffice --calc' \
'Icon=libreoffice-calc' \
'Terminal=false' \
'Categories=Office;Spreadsheet;' \
'StartupNotify=true' \
> /home/headless/Desktop/libreoffice-calc.desktop && \
    chmod +x /home/headless/Desktop/libreoffice-calc.desktop
RUN chmod +x /home/headless/Desktop/libreoffice-calc.desktop

# venv + deps
RUN python3 -m venv /home/headless/venv
ENV PATH="/home/headless/venv/bin:${PATH}"

RUN pip install --no-cache-dir -U \
    pyautogui \
    pyscreeze \
    "Pillow>=9.2.0"

WORKDIR /home/headless/LAM_data_generator
COPY --chown=headless:headless LAM_data_generator/ /home/headless/LAM_data_generator/
COPY --chown=headless:headless sample_ods/ /home/headless/sample_ods/
RUN chmod +x /home/headless/LAM_data_generator/run_env_desktop.sh
