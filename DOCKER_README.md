# TwitchDropsMiner Docker Setup

This Docker setup runs TwitchDropsMiner in headless mode, supporting environment variable configuration for proxy, exclude lists, priority settings, and periodic drop inventory checks.

## Environment Variables

- `CRON_SCHEDULE`: Interval in minutes for periodic inventory checks (default: 30)
- `EXCLUDE`: Comma-separated list of games to exclude (e.g., "Game1,Game2")
- `PROXY`: Proxy URL (e.g., "http://proxy.example.com:8080")
- `PRIORITY`: Comma-separated list of priority games
- `PRIORITY_MODE`: Priority mode, one of "PRIORITY_ONLY", "BLACKLIST", "OFF" (default: "PRIORITY_ONLY")

## Building and Running

### Using Docker Compose (Recommended)

1. Build and run:
   ```bash
   docker-compose up --build
   ```

2. On first run, the container will output an activation code. Visit the provided URL and enter the code to activate your device.

3. The container will continue running, performing initial inventory check and periodic checks based on `CRON_SCHEDULE`.

### Using Docker Directly

1. Build the image:
   ```bash
   docker build -t twitchdropsminer-light .
   ```

2. Run the container:
   ```bash
   docker run -e CRON_SCHEDULE=30 -e EXCLUDE="Game1,Game2" -v ./data:/app twitchdropsminer-light
   ```

## Data Persistence

Mount a volume to `/app` to persist cookies, settings, and logs between container restarts.

## Logs

View container logs:
```bash
docker-compose logs -f
```

## Lightweight Build

This Docker image excludes GUI components and uses a stripped-down entry point (`headless_main.py`) for minimal size and dependencies. No tkinter or GUI libraries are included.

## Notes

- The application runs in headless mode with console output.
- Device activation is required on first run.
- Inventory checks occur on startup and at the specified cron interval.