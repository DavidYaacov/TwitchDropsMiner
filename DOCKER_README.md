# Twitch Drops Miner — Docker deployment

The Docker image runs the current miner with an English-only browser interface.
It exposes mining progress, channel switching, campaign/drop inventory, Twitch
device login, activity, and Docker-relevant settings at
`http://localhost:8080`.

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

`docker compose down` keeps the named volume. Add `--volumes` only when you
also want to delete saved cookies, settings, and logs.

## Manage settings in the web GUI

Priority games, excluded games, priority mode, proxy, and advanced mining
options are managed only from the Settings page. They are saved in the named
Docker volume and survive container updates and restarts.

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
