FROM accetto/ubuntu-vnc-xfce-g3:latest

LABEL org.opencontainers.image.title="lam-gui-gimp" \
      org.opencontainers.image.description="GIMP GUI environment"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    gimp \
    python3 python3-venv python3-pip \
    python3-tk python3-dev \
    gnome-screenshot \
    wmctrl \
    vim \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /home/headless && chown -R headless:headless /home/headless

USER headless
WORKDIR /home/headless

RUN mkdir -p /home/headless/Desktop /home/headless/.local/share/applications && \
    printf '%s\n' \
'[Desktop Entry]' \
'Type=Application' \
'Version=1.0' \
'Name=GIMP' \
'Comment=Image Editor' \
'Exec=gimp' \
'Icon=gimp' \
'Terminal=false' \
'Categories=Graphics;2DGraphics;RasterGraphics;' \
'StartupNotify=true' \
> /home/headless/Desktop/gimp.desktop && \
    cp /home/headless/Desktop/gimp.desktop /home/headless/.local/share/applications/gimp.desktop && \
    chmod +x /home/headless/Desktop/gimp.desktop /home/headless/.local/share/applications/gimp.desktop

RUN python3 -m venv /home/headless/venv
ENV PATH="/home/headless/venv/bin:${PATH}"

RUN pip install --no-cache-dir -U \
    pyautogui \
    pyscreeze \
    "Pillow>=9.2.0"

RUN mkdir -p /home/headless/sample_images

WORKDIR /home/headless/LAM_data_generator
COPY --chown=headless:headless LAM_data_generator/ /home/headless/LAM_data_generator/
RUN chmod +x /home/headless/LAM_data_generator/run_env_desktop.sh
