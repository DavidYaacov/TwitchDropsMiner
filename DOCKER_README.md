# Twitch Drops Miner — Docker deployment

The Docker image runs the current miner with an English-only browser interface.
It exposes mining progress, channel switching, campaign/drop inventory and
claiming, Twitch device login and account switching, activity, and
Docker-relevant settings at
`http://localhost:8080`.

## Local web development

You can run the same web GUI without Docker. Install the Python dependencies
once with `python -m pip install -r requirements.txt`, then run
`run_web_dev.bat` on Windows or `sh run_web_dev.sh` on Linux/macOS. Open
`http://127.0.0.1:8080`; set `WEB_PORT` before launching to use another port.

## Docker Compose

The repository includes [`docker-compose.yml`](docker-compose.yml). This is a
complete example:

```yaml
services:
  twitchdropsminer:
    build: .
    ports:
      - "127.0.0.1:${WEB_PORT:-8080}:8080"
    volumes:
      - twitchdropsminer-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/state', timeout=3)"]
      interval: 30s
      timeout: 5s
      start_period: 20s
      retries: 3

volumes:
  twitchdropsminer-data:
```

Start it from the repository directory:

```bash
docker compose up --build -d
```

Then open `http://localhost:8080`. On the first run, follow the Twitch
activation link and enter the device code shown on the Dashboard.

View logs or stop the deployment with:

```bash
docker compose logs -f
docker compose down
```

The container writes normal startup, Twitch login, WebSocket, channel, claim,
restart, and error events directly to `docker compose logs` without requiring
file logging or extra Compose environment variables.

`docker compose down` keeps the named volume. Add `--volumes` only when you
also want to delete saved cookies, settings, and logs.

## Manage settings in the web GUI

Priority games, excluded games, priority mode, proxy, advanced mining options,
and ntfy notifications are managed only from the Settings page. They are saved
in the named Docker volume and survive container updates and restarts.

For ntfy, enter the server URL (such as `https://ntfy.sh`), the subscribed
topic, and an optional access token, then turn on the Enabled switch. Use the
test button in the panel header to verify the entered values before saving.
The miner sends the same notification as the desktop GUI after Twitch confirms
that a drop was successfully claimed. This includes automatic claims and
claims started from the Inventory page.

`WEB_PORT` is optional Compose port substitution, not a miner setting. For
example, `WEB_PORT=9090 docker compose up -d` publishes the same web GUI at
`http://localhost:9090` without passing configuration into the container.

## Docker CLI alternative

```bash
docker build -t twitchdropsminer .
docker run -d --name twitchdropsminer \
  -p 127.0.0.1:8080:8080 \
  -v twitchdropsminer-data:/app/data \
  --restart unless-stopped \
  twitchdropsminer
```

## Network safety

The example binds the web GUI to `127.0.0.1`, so it is reachable only from the
Docker host. The web GUI does not provide its own password prompt. If remote
access is required, place it behind an authenticated HTTPS reverse proxy or a
private VPN instead of publishing port `8080` directly to the internet.
