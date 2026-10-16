# Docker GUI Clients

Docker desktops for Calc, Impress, Writer, Slack, GIMP, and Visual Studio Code.
Each client connects to an agent socket server using `HOST`, `PORT`, and
`CLIENT_ID`, and supports screenshots, GUI actions, and episode resets.

## Configure and build

Run from the repository root:

```bash
cd environment
cp -n .env.example .env
# Edit .env: choose your own VNC_PW and set the server address and ports.
docker compose --profile build build
```

Build one application with `docker compose --profile build build calc`
(replace `calc` with `impress`, `writer`, `slack`, `gimp`, or `vscode`).
The VS Code client lives in `docker_vscode/`; its service is named `vscode`.

`GUI_AGENT_SERVER_HOST` is the server address reachable from the container.
For a server on the Docker host, use `host.docker.internal`; Compose includes
Linux host-gateway mapping. The server must listen on an interface reachable
from the container. For a remote server, set its address in your local `.env`.
Existing shell environment variables take precedence over `.env` values.

## Start a desktop

Start the matching agent server first, with the same port as `<DOMAIN>_SERVER_PORT`
in `.env`. For example, from the repository root:

```bash
cd components/Episode_generator
MOD=train BASE_DIR=./test/writer_train/repro START_TASK_IDX=0 END_TASK_IDX=10 \
  PORT=9999 bash run_writer.sh
```

Then, from `environment/`, start the corresponding client:

```bash
docker compose --profile writer up -d writer_1
docker compose logs -f writer_1
```

| Application | Profile | Client service | VNC port | Browser desktop port | Default server port |
| --- | --- | --- | --- | --- | --- |
| Calc | `calc` | `calc_1` | 5906 | 6085 | 7777 |
| Impress | `impress` | `impress_1` | 5907 | 6086 | 8888 |
| Writer | `writer` | `writer_1` | 5908 | 6087 | 9999 |
| Slack | `slack` | `slack_1` | 5909 | 6088 | 1111 |
| GIMP | `gimp` | `gimp_1` | 5910 | 6089 | 5555 |
| VS Code | `vscode` | `vscode_1` | 5911 | 6090 | 4444 |

For example, open `http://localhost:6087` for Writer and authenticate with
`VNC_PW`. Desktop ports bind to loopback on the Docker host. On a remote host,
forward the browser port over SSH, for example
`ssh -L 6087:localhost:6087 user@your-server`, then use the local URL.
Use the HTTPS URL instead if TLS is enabled in your base image configuration.

GIMP and VS Code require a server that implements the same socket protocol;
adding these clients does not add training tasks or server launch scripts.
The clients retry their connection while waiting for the server.

Stop one desktop with `docker compose stop writer_1`. Run
`docker compose --profile '*' down` to stop and remove all project containers.
Named volumes remain unless you explicitly remove them with `down -v`.

## Input files and persistent state

- Calc: `docker_calc/sample_ods/` contains example spreadsheets with document
  metadata removed. Cell values and formatting are preserved.
- Impress and Writer: place reviewed task files in `docker_impress/sample_odp/`
  and `docker_writer/sample_odt/` before building. These directories are initially
  empty; they do not include benchmark datasets.
- Office clients use `sample_<index>.<extension>` names, such as `sample_00.ods`.
  Check the selected task's required file before running its setup.
- GIMP: mount your reviewed images at `/home/headless/sample_images` and set
  `SETUP_FILE_EXTENSION` if they are not PNG files. No image dataset is bundled.
- Slack: set `SLACK_WEB_URL` locally. Sign into your own test workspace through
  the desktop. Browser and native Slack login state are stored in Docker named
  volumes, not in the source tree. `EX` and `SETUP_<idx>` close user applications and start the
  native Slack app; the desktop shortcut opens Slack Web.
- VS Code: reviewed files placed in `docker_vscode/workspace/` are copied into
  the image as the reset seed. The directory starts empty. Settings, extensions,
  and the running workspace use separate named volumes.

VS Code starts its socket client through XFCE autostart. The other services
start it through the Compose command after waiting for the display.
`EX`/`SETUP`/`RESET` reset VS Code state and reopen the editor; `END` resets
without reopening. The three `VSCODE_RESET_*_ON_EX` variables control the reset
scopes for all these requests. Set a scope to `false` to preserve it.
Do not mount irreplaceable files into a workspace configured to reset.

## Protocol and isolation

The protocol supports `PLATFORM`, `ENVDES`, `NOTE`, `SCREENSHOT`, `EXEC`,
`SETUP_<idx>`, `END_<idx>`, `EX`, `RESET`, and `EXIT`.
`EX` performs a reset without a response; other reset/setup requests return
status strings. Office/Slack/GIMP retain their upstream episode behavior:
reset is driven by explicit reset/setup/end requests, not automatically by
`DONE`/`FAIL`.

`EXEC` runs Python supplied by the server. Use a trusted server and disposable
containers; do not share host PID namespaces or mount sensitive host folders.
Desktop images use container-specific browser/editor sandbox flags. Slack and
VS Code retain `seccomp=unconfined` from the reference runtime configuration.

## Publishing

Only example configuration is included. `.env`, login profiles, private key
files, logs, and runtime exports are ignored by Git. Each image has a
`.dockerignore` that limits its build context to client code and intended input
files, with credential/cache exclusions. Review any files you add to sample or
seed directories before publishing or building; ignore rules do not remove
secrets from previously committed files or Git history.

## Local checks

The desktop-free tests require Python 3.10 or newer. From the repository root:

```bash
python3.10 -m unittest discover -s environment/tests
docker compose -f environment/docker-compose.yml \
  --env-file environment/.env.example --profile '*' config --quiet
```

These checks do not build images or exercise a live desktop/server connection.
