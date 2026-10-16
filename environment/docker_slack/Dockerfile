FROM accetto/ubuntu-vnc-xfce-g3:latest

LABEL org.opencontainers.image.title="lam-gui-slack" \
      org.opencontainers.image.description="Slack Web GUI environment"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xdg-utils \
    python3 python3-venv python3-pip \
    python3-tk python3-dev \
    gnome-screenshot \
    fonts-noto-cjk \
    vim \
 && wget -O /tmp/slack.deb https://downloads.slack-edge.com/desktop-releases/linux/x64/4.50.143/slack-desktop-4.50.143-amd64.deb \
 && wget -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get install -y /tmp/chrome.deb /tmp/slack.deb \
 && rm -f /tmp/chrome.deb /tmp/slack.deb \
 && rm -rf /var/lib/apt/lists/*

# (root) ensure home exists and is writable by headless
RUN mkdir -p /home/headless && chown -R headless:headless /home/headless
RUN touch /dockerstartup/vnc.log /dockerstartup/novnc.log && \
    chown headless:headless /dockerstartup/vnc.log /dockerstartup/novnc.log
RUN printf '%s\n' \
'#!/bin/sh' \
'profile_dir="${CHROME_USER_DATA_DIR:-$HOME/.config/google-chrome}"' \
'chrome_lang="${CHROME_LANG:-en-US}"' \
'chrome_accept_lang="${CHROME_ACCEPT_LANG:-en-US,en}"' \
'lock_target="$(readlink "$profile_dir/SingletonLock" 2>/dev/null || true)"' \
'current_host="$(hostname)"' \
'case "$lock_target" in' \
'  ""|"$current_host"-*) ;;' \
'  *) rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonCookie" "$profile_dir/SingletonSocket" ;;' \
'esac' \
'if [ -e "$profile_dir/SingletonLock" ] && ! pgrep -u "$(id -u)" -f "/opt/google/chrome/chrome " >/dev/null 2>&1; then' \
'  rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonCookie" "$profile_dir/SingletonSocket"' \
'fi' \
'exec /usr/bin/google-chrome-stable --no-sandbox --lang="$chrome_lang" --accept-lang="$chrome_accept_lang" --user-data-dir="$profile_dir" "$@"' \
> /usr/local/bin/google-chrome-no-sandbox && \
    chmod +x /usr/local/bin/google-chrome-no-sandbox && \
    ln -sf /usr/local/bin/google-chrome-no-sandbox /usr/local/bin/x-www-browser
RUN printf '%s\n' \
'#!/bin/sh' \
'exec /usr/local/bin/google-chrome-no-sandbox "${SLACK_WEB_URL:-https://slack.com/signin}"' \
> /usr/local/bin/open-slack-web && \
    chmod +x /usr/local/bin/open-slack-web

USER headless
WORKDIR /home/headless

RUN mkdir -p /home/headless/.config/xfce4 /home/headless/.config/google-chrome \
             /home/headless/.local/share/applications /home/headless/.local/share/xfce4/helpers && \
    printf '%s\n' \
'[Desktop Entry]' \
'Version=1.0' \
'Type=X-XFCE-Helper' \
'Name=Google Chrome (no sandbox)' \
'StartupNotify=true' \
'X-XFCE-Binaries=google-chrome-no-sandbox;' \
'X-XFCE-Category=WebBrowser' \
'X-XFCE-Commands=/usr/local/bin/google-chrome-no-sandbox;' \
'X-XFCE-CommandsWithParameter=/usr/local/bin/google-chrome-no-sandbox "%s";' \
> /home/headless/.local/share/xfce4/helpers/custom-WebBrowser.desktop && \
    printf '%s\n' \
'[Desktop Entry]' \
'Type=Application' \
'Name=Google Chrome' \
'Exec=/usr/local/bin/google-chrome-no-sandbox %U' \
'Icon=google-chrome' \
'Terminal=false' \
'Categories=Network;WebBrowser;' \
'MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;' \
> /home/headless/.local/share/applications/google-chrome-no-sandbox.desktop && \
    cp /home/headless/.local/share/applications/google-chrome-no-sandbox.desktop \
       /home/headless/.local/share/applications/google-chrome.desktop && \
    cp /home/headless/.local/share/applications/google-chrome-no-sandbox.desktop \
       /home/headless/.local/share/applications/com.google.Chrome.desktop && \
    printf '%s\n' \
'WebBrowser=custom-WebBrowser' \
> /home/headless/.config/xfce4/helpers.rc && \
    printf '%s\n' \
'[Default Applications]' \
'x-scheme-handler/http=google-chrome-no-sandbox.desktop' \
'x-scheme-handler/https=google-chrome-no-sandbox.desktop' \
'text/html=google-chrome-no-sandbox.desktop' \
> /home/headless/.local/share/applications/mimeapps.list

# Desktop shortcut for Slack Web (no heredoc; sh-safe)
RUN mkdir -p /home/headless/Desktop /home/headless/.local/share/applications && \
    printf '%s\n' \
'[Desktop Entry]' \
'Type=Application' \
'Version=1.0' \
'Name=Slack Web' \
'Comment=Open Slack in Chrome' \
'Exec=/usr/local/bin/open-slack-web' \
'Icon=google-chrome' \
'Terminal=false' \
'Categories=Network;InstantMessaging;' \
'StartupNotify=true' \
> /home/headless/Desktop/slack.desktop && \
    chmod +x /home/headless/Desktop/slack.desktop
RUN chmod +x /home/headless/Desktop/slack.desktop

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
