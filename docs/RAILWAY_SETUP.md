# Railway deployment

## Deploy

1. Push this project to a private GitHub repository. Keep `.env`, `.venv`, `data/`, `logs/`, and `backups/` out of GitHub; `.gitignore` already excludes them.
2. In Railway, create a project from that GitHub repository. Railway reads `railway.json` and runs `python main.py`.
3. Add a Railway Volume to the service mounted at `/data`.
4. Add the variables below in the service's Variables tab, then deploy.
5. Generate a Railway public domain for the service. Set `JARVIS_PUBLIC_BASE_URL` to that origin (no trailing slash), and `JARVIS_REDIRECT_URI` to the same origin plus `/oauth/callback`.
6. Add the exact `JARVIS_REDIRECT_URI` under OAuth2 Redirects in the Discord Developer Portal. Enable the `identify` and `guilds.join` OAuth scopes in the bot's consent flow as already used by the app.

Railway injects `PORT`; JARVIS listens on `0.0.0.0:$PORT`. The verification site, health check, and SellAuth webhook share this single public listener. Configure SellAuth's webhook URL as `<Railway domain>/sellauth/notifications`.

## Required variables

| Variable | Value |
|---|---|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `DISCORD_OAUTH_CLIENT_ID` | OAuth application client ID |
| `DISCORD_OAUTH_CLIENT_SECRET` | OAuth application client secret |
| `JARVIS_PUBLIC_BASE_URL` | Railway HTTPS domain, no trailing slash |
| `JARVIS_REDIRECT_URI` | Railway HTTPS domain plus `/oauth/callback` |
| `JARVIS_DATABASE_PATH` | `/data/jarvis_shop.sqlite3` |
| `JARVIS_RECOVERY_KEY` | Existing recovery key, if already configured; keep it unchanged to decrypt saved member tokens |
| `JARVIS_PULL_API_KEY` | Strong random secret if using the pull API/dashboard |
| `SELLAUTH_WEBHOOK_SECRET` | SellAuth webhook signing secret, when using SellAuth notifications |

Do not change `JARVIS_RECOVERY_KEY` after collecting recovery-consented members: existing encrypted records depend on that key. The Railway Volume is required because the container's ordinary filesystem is temporary and may be replaced during deployment.

For existing local installs, leave `JARVIS_DATABASE_PATH` unset so the bot continues using `data/jarvis_shop.sqlite3` in the project folder.
