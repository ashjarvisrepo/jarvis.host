# Troubleshooting

## `Missing Discord token`

Copy `.env.example` to `.env`, set `DISCORD_TOKEN`, and restart. Never paste the token into chat or commit `.env`.

## Prefix commands are ignored

Enable **Message Content Intent** in the Discord Developer Portal, then restart the bot.

## Slash commands

Slash commands are disabled by design in this build. The next successful bot startup clears previously published global and server-specific slash commands. Use `$help` for all command groups and syntax.

## Ticket or server setup fails

Check bot-level role configuration and Discord permissions. Private ticket creation needs channel management and message permissions. Server layout setup is owner-only with `$server_setup`; it requires Manage Roles and Manage Channels permissions.

## Verification portal does not start

It is disabled by default. Configure OAuth Client ID and secret in `.env`, configure `verify.public_base_url` and an exact registered `redirect_uri`, set a target guild, and host the callback over HTTPS. Review the detailed OAuth notes in README.

## Tests cannot install dependencies

Run `setup.bat` on a Windows host with Python 3.11+ and network access to the configured package index. Then run `run_tests.bat`. In restricted environments, a failed package download means tests were not run; it is not a test pass.

## Database backup

Stop the bot before copying `data\jarvis_shop.sqlite3`. Keep backups private because they contain customer and order data. Restore by stopping the bot, replacing the database file with a known-good copy, and starting the bot. A restore drill is not automated by this release.
# Windows startup quick checks

- **Black console with no text:** run `python main.py` from Command Prompt in the project folder. Keep the window open; startup progress and the connected account name are printed there.
- **Missing `.venv`:** create it manually with `py -3 -m venv .venv`, then activate using `call .venv\Scripts\activate.bat` in Command Prompt.
- **Missing Discord token:** if `.env` does not exist, run `copy .env.example .env`; open `.env`, replace the example value with your bot token, save, then run `python main.py` again.
- **Invalid token or login failure:** create/reset the token in Discord Developer Portal, update `.env`, and restart. Never paste the token into chat.
- **Bot starts but prefix commands do nothing:** enable Message Content Intent in the Developer Portal and check `command_prefix` in `config/settings.yaml` (default `$`).
- **Slash commands appear in Discord:** restart with the updated bot online so it can clear global and server-specific command registrations.
- **Package installation fails:** run `python -m pip install -r requirements.txt` from the activated environment and read the displayed error. Internet access is needed for packages not already installed.

