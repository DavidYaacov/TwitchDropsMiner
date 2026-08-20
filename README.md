# Twitch Drops Miner

Twitch Drops Miner advances timed Twitch Drops without downloading stream video
or audio. It automatically discovers eligible campaigns and channels, switches
when needed, claims rewards, and exposes status and settings in a browser.

## Docker Compose

Start the miner from this repository:

```bash
docker compose up --build -d
```

Open `http://localhost:8080`. On the first run, use the Dashboard’s Twitch
activation link and device code to connect your account.

View logs or stop the miner with:

```bash
docker compose logs -f
docker compose down
```

The named Docker volume keeps cookies, settings, and logs when the container
stops. Use `docker compose down --volumes` only when you want to remove them.

Set `WEB_PORT` to publish another local port:

```bash
WEB_PORT=9090 docker compose up -d
```

## Development

```bash
python -m pip install -r requirements-dev.txt
ruff check .
ruff format .
```

## Docker CLI

```bash
docker build -t twitchdropsminer .
docker run -d --name twitchdropsminer \
  -p 127.0.0.1:8080:8080 \
  -v twitchdropsminer-data:/app/data \
  --restart unless-stopped \
  twitchdropsminer
```

## Features

- Stream-less drop mining.
- Shared-channel campaign support.
- Automatic claims and channel switching.
- Game priority and exclusion settings.
- Browser dashboard for mining status, inventory, login, and settings.
- Optional ntfy notifications after confirmed claims.

## Security

The Compose setup binds the dashboard to `127.0.0.1`, so it is accessible only
from the Docker host. Do not expose it publicly; use an authenticated HTTPS
reverse proxy or private VPN if remote access is required.

Keep the saved `cookies.jar` private because it contains the account session.

## Notes

Do not watch other Twitch streams with the same account while the miner is
active; Twitch can report misleading drop progress in that situation.
