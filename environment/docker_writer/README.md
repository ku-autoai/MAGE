# LibreOffice Writer desktop

See [the client guide](../README.md) for configuration, server connection,
input files, and reset behavior. Run these commands from `environment/`
after creating `.env` from `.env.example` and setting `VNC_PW`:

```bash
docker compose --profile build build writer
docker compose --profile writer up -d writer_1
```
