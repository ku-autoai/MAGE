# Visual Studio Code desktop

See [the client guide](../README.md) for configuration, server connection,
input files, and reset behavior. Run these commands from `environment/`
after creating `.env` from `.env.example` and setting `VNC_PW`:

```bash
docker compose --profile build build vscode
docker compose --profile vscode up -d vscode_1
```

The client starts automatically with XFCE. Use the three
`VSCODE_RESET_*_ON_EX` variables in `.env` to choose whether settings,
extensions, and workspace data are cleared during resets. Seed files belong
in `workspace/`; review them before building or publishing.
