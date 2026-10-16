# Slack desktop

See [the client guide](../README.md) for configuration, server connection,
input files, and reset behavior. Run these commands from `environment/`
after creating `.env` from `.env.example` and setting `VNC_PW`:

```bash
docker compose --profile build build slack
docker compose --profile slack up -d slack_1
```
