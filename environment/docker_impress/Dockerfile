FROM accetto/ubuntu-vnc-xfce-g3:latest

LABEL org.opencontainers.image.title="lam-gui-impress" \
      org.opencontainers.image.description="LibreOffice Impress GUI environment"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice libreoffice-impress \
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

# Desktop shortcut for LibreOffice Impress (no heredoc; sh-safe)
RUN mkdir -p /home/headless/Desktop /home/headless/.local/share/applications && \
    printf '%s\n' \
'[Desktop Entry]' \
'Type=Application' \
'Version=1.0' \
'Name=LibreOffice Impress' \
'Comment=Presentation' \
'Exec=libreoffice --impress' \
'Icon=libreoffice-impress' \
'Terminal=false' \
'Categories=Office;Presentation;' \
'StartupNotify=true' \
> /home/headless/Desktop/libreoffice-impress.desktop && \
    chmod +x /home/headless/Desktop/libreoffice-impress.desktop
RUN chmod +x /home/headless/Desktop/libreoffice-impress.desktop

# venv + deps
RUN python3 -m venv /home/headless/venv
ENV PATH="/home/headless/venv/bin:${PATH}"

RUN pip install --no-cache-dir -U \
    pyautogui \
    pyscreeze \
    "Pillow>=9.2.0"

WORKDIR /home/headless/LAM_data_generator
COPY --chown=headless:headless LAM_data_generator/ /home/headless/LAM_data_generator/
COPY --chown=headless:headless sample_odp/ /home/headless/sample_odp/
RUN chmod +x /home/headless/LAM_data_generator/run_env_desktop.sh
