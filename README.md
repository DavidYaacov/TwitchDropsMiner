# Twitch Drops Miner

Twitch Drops Miner advances timed Twitch Drops without downloading stream video
or audio. It automatically discovers eligible campaigns and channels, switches
when needed, claims rewards, and exposes status and settings in a browser.

## Docker Compose

Start the latest published miner image:

```bash
docker compose up -d
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
docker pull ghcr.io/davidyaacov/twitchdropsminer:latest
docker run -d --name twitchdropsminer \
  -p 127.0.0.1:8080:8080 \
  -v twitchdropsminer-data:/app/data \
  --restart unless-stopped \
  ghcr.io/davidyaacov/twitchdropsminer:latest
```

## Build locally

Build the image from this checkout, then run it with the same command using the
local tag:

```bash
docker build -t twitchdropsminer:local .
docker run -d --name twitchdropsminer \
  -p 127.0.0.1:8080:8080 \
  -v twitchdropsminer-data:/app/data \
  --restart unless-stopped \
  twitchdropsminer:local
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

Before mining a campaign, link your Twitch account to the game account on the
[Twitch Drops campaigns page](https://www.twitch.tv/drops/campaigns). Use the
Settings page to select priority games or choose a priority mode for everything
else.

> [!WARNING]
> Do not watch other Twitch streams with the same account while the miner is
> active. Twitch can report misleading progress and the miner can get stuck.

> [!CAUTION]
> Keep the saved `cookies.jar` private: it contains an active account session.

> [!IMPORTANT]
> Twitch may send a “New Login” email after device login. This is expected;
> make sure the notification identifies your own IP address.

> [!NOTE]
> The seconds countdown is an estimate. Twitch can update progress late or for a
> different drop, so the displayed timer may pause and restart. Check the
> dashboard periodically: Twitch changes or connection failures can stop mining,
> so this is not a guaranteed unattended service.

Twitch Drops Miner was originally created by
[DevilXD](https://github.com/DevilXD/TwitchDropsMiner).
