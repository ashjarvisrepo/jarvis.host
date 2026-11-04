# JARVIS SHOP EXTREME

Version 0.6.12 — continuation of the v0.4.0 DOLLAR project. A free-first, self-hosted Discord shop bot foundation for digital products and services. Python + discord.py + SQLite. Optional local AI uses Ollama; core shopping workflows do not require AI or paid APIs.

**Prefix-only build:** slash commands are disabled. On the next successful bot startup, JARVIS clears its global and server-specific slash commands from Discord. All 58 previously registered application-command features now have prefix commands or aliases. Use `$` for every command; `$help` only shows command groups available to the person who ran it. The Discord server owner and configured bot owners see all groups; staff see member and eligible staff commands; admins see member and staff/admin commands; members see member commands. There are no help dropdowns or buttons.

## Included working modules

- Four-level authorization: owner, admin, staff, member.
- Product catalog and owner-only product creation/deactivation.
- Per-user cart and transactional checkout with stock deduction.
- Order tracking and manual payment-reference submission.
- Staff payment verification and delivery status.
- Private support tickets and staff closure.
- Percentage coupons applied atomically during checkout, with use limits and expiry checks.
- Product text search, category filter, price/name sorting, and tracked stock adjustments.
- Additive SQLite schema migrations and an owner-only store health report.
- Basic sales analytics, staff report, audit log.
- Optional local Ollama question assistant.
- SQLite database initialization and tests.
- JARVIS VERIFY OAuth2 portal with explicit-consent server joining, custom Verified role assignment, and tracked growth invite campaigns.
- OAuth verification link and opt-in community updates commands are available as prefix commands.
- The owner can post the verification panel with `$verifypanel [destination]` in the target text channel.
- Legacy slash-only features now work through prefix equivalents such as `$product_edit`, `$store_health`, and `$server_setup`; see the appropriate role's help list for full syntax.
- The single `$` prefix is configured in `config/settings.yaml`; role IDs, not the prefix, decide who can use protected commands.
- `$help` shows Member, Staff/Admin, and Owner command lists and syntax together in one response, without dropdowns or buttons.
- Owner one-to-one DMs (`$dm`), test DMs, delivery metadata history, campaign controls, and settings summary.
- Customer promotional opt-in/out and approved campaigns for opted-in previous buyers who are current members of the campaign server. Campaigns support plain text or branded embeds, basic placeholders, delivery progress, status, cancellation, and per-recipient duplicate protection.
- Shared branded embed builder currently integrated with DM campaign and audit views.
- Persistent ticket panel buttons, staff claim, archive, and reopen.
- Product edit/duplicate/details, wishlist, cart removal/clear, and unpaid-order cancellation with finite stock returned.
- Owner database backup creation, listing, integrity verification, and manual restore script that preserves the current DB first.
- SellAuth hosted checkout panel with a signed, replay-safe payment-processed webhook and Discord order-log notifications. SellAuth handles the configured digital delivery after payment clears.

## Important scope and safety notes

This is a runnable first release foundation with incremental commerce improvements, not a claim that every feature in the full wishlist is already implemented. Gateway payment capture/refunds and local key/file delivery are not implemented for the bot's local catalog. The optional SellAuth panel uses SellAuth hosted checkout and its configured delivery. Subscriptions, multi-store isolation, auctions, advanced marketing, forecasts, plugin discovery/management, and a visual dashboard are still unimplemented. Shared embed styling is not yet applied to every existing command. Manual payment verification is a staff action. See `docs/FEATURE_CHECKLIST.md` for the implementation boundary. SellAuth setup is in `docs/SELLAUTH_SETUP.md`.

Digital delivery data should be added only through a secure, access-controlled inventory module. Do not put passwords, account credentials, API keys, or license pools in product descriptions, YAML, or logs.

## Requirements

- Windows 10/11
- Python 3.11 or newer
- A Discord application/bot and token
- Optional: Ollama for local AI

## Setup (Windows CMD)

To do each step yourself, open **Command Prompt** inside the extracted project folder and follow these commands. You do not need to run any `.bat` file:

```bat
py -3 --version
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
notepad .env
notepad config\settings.yaml
python main.py
```

Enter your Discord bot token in `.env`, configure your owner ID and staff/admin role IDs in `config\settings.yaml`, save the files, then run `python main.py`. Keep that Command Prompt window open. Startup messages will tell you when it connects or show the error to fix. The individual steps are also described below.

1. Extract the ZIP.
2. Open CMD in the extracted `JARVIS-SHOP-EXTREME-v0.6.7` project folder.
3. Create a virtual environment:

   ```bat
   py -3 -m venv .venv
   .venv\\Scripts\\activate
   ```

4. Install packages:

   ```bat
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and paste your bot token:

   ```bat
   copy .env.example .env
   notepad .env
   ```

   Keep `.env` in the project folder and replace the example value with the token from your Discord Developer Portal. Do not share or upload this file.

6. Edit `config\\settings.yaml`:
   - Put your Discord numeric user ID in `owner_ids`.
   - Put admin role IDs in `admin_role_ids`; these grant access to admin commands.
   - Put staff role IDs in `staff_role_ids`.
   - Set `guild_id` to your server ID for faster guild command sync.
   - Configure shop channels and payment instructions.

7. In Discord Developer Portal, enable **Server Members Intent** and **Message Content Intent**. Invite the bot with the `bot` scope and permissions for the features you will use.

9. Start:

   ```bat
   python main.py
   ```

   Or double-click `start.bat`. The window is the bot's running console; leave it open. It now prints startup progress and the bot account name after Discord connects. See `docs/TROUBLESHOOTING.md` if it stops with an error.

## First shop setup

- Owner: `$addproduct Name | price_in_paise | stock | description`.
- Members: `$shop`, `$addcart PRODUCT-ID [QTY]`, `$cart`, `$checkout [COUPON]`, `$payment ORDER-ID REFERENCE`, and `$order ORDER-ID`.
- Staff: `$orderspending`, `$paymentverify ORDER-ID`, and `$deliver ORDER-ID [NOTE]`.
- Admins: `$ticketpanel` posts the styled ticket embed; `$autobuypanel` posts the SellAuth checkout and support panel after you configure the storefront URL.

## Optional local AI (Ollama)

Install Ollama separately, then in a terminal:

```bat
ollama pull qwen2.5:3b
ollama serve
```

Keep `ai.enabled: true` in config. If Ollama is offline, ordinary shop functions continue working. The AI helper cannot access live customer records or approve transactions.

## Tests

```bat
pip install pytest pytest-asyncio
python -m pytest -q
```

## Backups

Stop the bot before copying `data\\jarvis_shop.sqlite3` to `backups\\`. For production, use scheduled backups and test restores. Never upload `.env` or database backups containing customer data to public repositories.

## Discord permissions

- Owner: the Discord server owner and any IDs explicitly listed in `owner_ids`.
- Admin: roles listed in `admin_role_ids`; grants admin commands using the shared `$` prefix, but not owner-only product, DM, or verification controls.
- Staff: roles listed in `staff_role_ids`; grants staff commands with the shared `$` prefix. Admins inherit staff access; owner IDs inherit admin and staff access.
- Member: everyone else.

Discord server permissions are separate from bot-level permissions. Give the bot only the server permissions it needs.

## Added catalog and operations commands

- `$search <words>` searches product names and descriptions.
- `$stock PRODUCT-ID CHANGE` adjusts finite stock; positive numbers restock and negative numbers reduce stock. Unlimited stock products cannot be adjusted.
- `$say <text>` lets an admin echo supplied text without an embed or extra content and suppresses notification pings. `$announce` remains a separate admin embed command.

See `docs/INTEGRATIONS.md`, `docs/PLUGINS.md`, and `docs/TROUBLESHOOTING.md` for capability boundaries and operating guidance.
See `docs/SELLAUTH_SETUP.md` for hosted checkout, digital delivery, and payment notification setup.
For DM command permissions, the campaign workflow, and its targeting limits, see `docs/DM_MANAGER.md`.
SQLite upgrade details are in `docs/MIGRATIONS.md`; the validation report is in `docs/TEST_RESULTS.md`.


## JARVIS VERIFY — owner-managed OAuth2 verification and community growth

Build 0.2.0 adds an optional web verification portal. It is disabled by default. It uses Discord's official OAuth2 authorization-code flow with only `identify` and `guilds.join`; it never asks for Discord passwords, session tokens, or MFA codes. A member sees the destination server and must explicitly authorize the join on Discord. The application adds only the server selected by that verification link.

### What it includes

- Branded verification page explaining why server access requires verification, with a lightweight math challenge, honeypot field, one-time OAuth state, and basic in-memory rate limiting. JARVIS does not log or save IP addresses; earlier stored IP hashes are cleared on database startup.
- Optional Discord account-age minimum.
- OAuth2 profile identification and explicit `guilds.join` consent.
- Adds the consenting member to the configured destination server (the bot must already be in that server and have **Create Invite** permission).
- Grants the configured Verified role only after a member completes JARVIS OAuth verification. If Discord Membership Screening is enabled, the grant stays queued until that member completes screening; ordinary joins never receive the role automatically.
- `$verify [destination]`, `$verify_stats`, `$verify_config`, and `$growth_invite CAMPAIGN` are owner-only verification management commands. Members use the posted verification panel.
- Verification outcomes and campaign attributions are stored in SQLite. Raw IP addresses and OAuth access tokens are not stored. OAuth refresh tokens are stored only when a member separately opts into recovery, and are encrypted with the local AES-256 key.

### Required Discord setup

1. Open the Discord Developer Portal and select the same application used by this bot.
2. Under **OAuth2**, add the exact callback URL you will use, for example `https://verify.example.com/oauth/callback`.
3. Put the application's Client ID and Client Secret in `.env` as `DISCORD_OAUTH_CLIENT_ID` and `DISCORD_OAUTH_CLIENT_SECRET`. Never post or share the secret.
4. In **Bot** settings, enable **Server Members Intent**. The bot must be in every target server. Give it **Create Invite** permission there. To assign a Verified role, give it **Manage Roles** and move the bot's highest role above the Verified role.
5. Edit `config/settings.yaml` under `verify:`. Set `enabled: true`, `public_base_url`, and the exact `redirect_uri`. For each target, set a unique `key`, `name`, target `guild_id`, `role_id`, and optional `invite_url`. Example IDs are placeholders; replace them with your real server and role IDs.
6. Host the portal at the configured public URL over HTTPS. The bot listens on `host:port` (default `127.0.0.1:8787`); put a secure HTTPS reverse proxy or tunnel in front of it and forward `/verify/*`, `/oauth/callback`, `/api/pulls/*`, and `/health` to that local listener. A localhost URL alone will not work for people on other devices.
7. Restart JARVIS, then run `$verify_config` as owner. Members use the verification panel posted in the server.

### Discord API and safety notes

Discord's Add Guild Member endpoint requires a user OAuth2 access token with `guilds.join`, the bot to be in the destination server, and the bot to have `Create Invite` permission. The OAuth2 callback URL must match the Developer Portal exactly. See the official [OAuth2 documentation](https://discord.com/developers/docs/topics/oauth2) and [Add Guild Member API](https://discord.com/developers/docs/resources/guild#add-guild-member).

JARVIS cannot grant Discord's official platform-issued Verified Server status or a verified-bot badge. The in-server role is a custom role named by the server owner. Do not disguise this as an official Discord badge. Joining is always opt-in; never use this flow to silently add users or misrepresent which server they are joining. Multi-server campaigns should use a separate clearly labelled link for each destination. Invite attribution is best-effort: simultaneous joins can occasionally make invite-code attribution ambiguous.

### Testing status

The updated Python files pass syntax compilation; automated tests were not run. OAuth refresh, encrypted recovery storage, member pulls, API authentication, Discord server joins, HTTPS hosting, and role hierarchy have **not** been live-tested against a real Discord application or server. Configure and test in a private test server before public use.


## JARVIS VERIFY 0.3.0 — server builder, cloner, and member announcements

### One-command server setup

Run `$server_setup` as the owner in the server you want to configure. JARVIS creates or reuses `Verified Member` and `JARVIS Updates` roles, a public `START HERE` category with `#verify-here`, and a private `COMMUNITY` category with `#general`, `#introductions`, `#announcements`, and `voice-lounge`. The `@everyone` role is denied visibility of the community category; the Verified Member role is allowed in. The verification channel remains visible so new members can complete onboarding. The OAuth target's role ID is updated in the local YAML configuration when a matching target exists.

The bot needs **Manage Roles** and **Manage Channels**. Put the bot's highest role above the Verified Member and JARVIS Updates roles. Existing channels with the same names may be reused and their category/permission settings updated. Review the resulting permissions after setup, especially if your server has custom roles or private staff channels.

### Verification panel

`$verifypanel [destination]` posts a branded panel with a Discord authorization button in the current text channel. The default destination is `main`; verification target and public URL must be configured first. Members use the panel's button to verify.

### Server structure clone

`$server_clone SOURCE_SERVER_ID DESTINATION_SERVER_ID` copies role definitions and basic category, text-channel, and voice-channel structure into a destination server that already exists. The bot must be installed in both servers, and the command user must have Discord Administrator permission in both. It does **not** create a new Discord guild (bots cannot create guilds), copy members, messages, user-specific overwrites, integrations, webhooks, or invite links. Existing destination roles/channels with matching names are reused. Review permissions after cloning.

### Server structure snapshots and member recovery

`$serversnapshot create <name>` saves a JSON snapshot for the current server; `$serversnapshot list` shows saved snapshots for the current server; `$serversnapshot restore <name> [source_server_id]` adds missing roles and category/text/voice channels in the current server. Omit the source ID to restore a snapshot from this server; provide it to migrate structure from another server. For cross-server restore, the bot must be in both servers and you need Discord Administrator in both. The bot also needs Manage Roles and Manage Channels in the destination. It does not delete existing items. Snapshots omit messages, member lists, tokens, webhooks, integrations, invite links, and personal member overwrites. Snapshot files are stored locally under `backups/server_snapshots/` and are excluded from source control. Review role permissions before and after restoring.

`$recoverypanel #channel [destination]` posts the verification panel. During OAuth verification, members can optionally check a separate recovery-consent box. With that opt-in, JARVIS encrypts and stores their Discord OAuth refresh token so the owner can pull them into another server where this bot is installed. This feature stores an encrypted OAuth refresh token, never a password or session token. Members can revoke the JARVIS app from Discord **User Settings → Authorized Apps**; revoked/invalid grants are removed when encountered. People verified before this option existed must verify again and opt in before they can be restored.

### Pull verified members to a replacement server

Add a second `verify.targets` entry with a new `key`, destination server `guild_id`, and destination verified `role_id`. Install the same bot in the destination and grant it **Create Invite** (required for Discord's Add Guild Member API) and **Manage Roles** if it should apply the destination verified role. Back up both the SQLite database and the recovery key; the DB contains encrypted refresh grants, and losing the key makes them unusable.

Generate a 32-byte encryption key for `.env` with:

`python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`

Set that output as `JARVIS_RECOVERY_KEY`. Set `JARVIS_PULL_API_KEY` to a long random API key if you need programmatic pull controls. Keep both private and back them up securely.

Owner commands in the destination server:

- `$pull plan <source_server_id> <destination_key> [member_id]` previews consented members; `$pull one <source_server_id> <destination_key> <member_id>` pulls one opted-in member.
- `$pull start <source_server_id> <destination_key>` queues up to the per-pull limit. Defaults: 2–4 seconds between members and 100 members per pull.
- `$pull settings` shows settings; `$pull settings delay <min_seconds> <max_seconds>` changes pacing; `$pull settings limit <members>` changes the batch limit (1–1000).
- `$pull status`, `$pull pause`, `$pull resume`, and `$pull stop` monitor and control the active pull. `$pull share` displays non-sensitive counters.

Optional HTTPS API using the same verification host and a Bearer API key: `POST /api/pulls/plan` with `{source_server_id,destination_key,member_id?}`, `POST /api/pulls/start` with the same body, `GET /api/pulls/status`, and `POST /api/pulls/control` with `{job_id,action}` where action is `pause`, `resume`, or `stop`. Configure `JARVIS_PULL_API_KEY`; the API rejects requests without it. Expose these endpoints only behind HTTPS and keep the key server-side.

Only people with encrypted, valid recovery consent are eligible. Discord requires this app's bot to be in the destination server with **Create Invite** permission. Each pull is paced; revoked grants are discarded. Membership Screening may leave restored users pending until they accept the destination server's rules. Discord may reject individual accounts or rate-limit a pull. Pulls add members and apply the configured destination Verified role; they do not copy messages, profiles, unrelated roles, or server-specific member data.
### Announcements instead of unsolicited DM blasts

JARVIS does not mass-DM every member of a role. Unsolicited bulk DMs are disruptive and can trigger Discord anti-spam enforcement. Instead, members can voluntarily opt in with `$updates join` and leave with `$updates leave`. Admins can use `$announce_updates MESSAGE [CHANNEL]` to post a role-targeted announcement, pinging only members who opted in.

### Important limits

This is not truly zero-configuration: OAuth2 verification still needs a Discord application Client ID/Secret and a publicly reachable HTTPS callback URL. `$server_setup` automates the Discord server layout, but it cannot create the Discord application, provision public hosting, or bypass OAuth consent.


## Simple command shortcuts and local dashboard (v0.6.10)

The one `$` prefix and all existing command names still work. Short aliases are added for commonly used features; examples include `$h` (help), `$s` (shop), `$add` (add to cart), `$buy` (checkout), `$track` (order status), `$v` (verification link), `$padd` (add product), `$tpanel` (ticket panel), `$snap` (server snapshot), and `$pull` (member recovery). `$help` lists each command's aliases and syntax.

For a quick member restore, run `$pull start <new_server_id> <role_id>` in the destination server. JARVIS uses the configured `main` target as the old/source server, then adds opted-in members to the provided destination and queues that destination role for them. The bot must already be in the new server. Control with `$pull status`, `$pull pause`, `$pull resume`, and `$pull stop`. Advanced source/destination-key syntax remains available.

The member-pull dashboard runs locally on the same computer as the bot, bound only to `127.0.0.1`. Run `$dashboard` (or `$dash`) and the bot DMs the private dashboard link. It includes source/destination selection, preview, single-member or batch pulls, saved pacing/limit settings, counters, and pause/resume/stop controls. The dashboard is not exposed to the public internet. If the bot runs on a remote host, this local page is on that host rather than your personal computer.

The single prefix is configured as `discord.command_prefix` (default `$`). Enable Message Content Intent in the Discord Developer Portal for prefix commands.
