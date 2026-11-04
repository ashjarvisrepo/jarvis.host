# Feature implementation checklist

This checklist records the v0.6.12 prefix-only command and permission setup. A listed feature is not considered complete unless it exists in code and its relevant checks pass.

## Implemented in this package

- [x] Prefix-only operation: one `$` prefix for all roles. Role checks determine access. `$help` shows only groups available to the viewer; server and configured bot owners see all groups. Staff see member and eligible staff commands; admins see member and staff/admin commands. All 58 prior application-command features are exposed through prefix commands or aliases; the local slash tree is empty and prior published commands are cleared at next startup.
- [x] Existing catalog, carts, atomic stock deduction at checkout, order tracking, staff payment-reference review, manual delivery status, tickets, community verification, and server updates retained where prefix commands exist.
- [x] Product search across names/descriptions, exact category filtering, and newest/price/name sorting.
- [x] Owner-only stock adjustment with validation and audit logging.
- [x] Percentage coupon application at checkout, expiry validation, and limited-use decrement inside the order transaction.
- [x] Additive SQLite migration for coupon/discount order fields and a schema migration marker; legacy rows remain intact.
- [x] `$say <text>` lets admins send exact text without an embed or appended text; mentions do not notify users.
- [x] Owner store health view checks database integrity, low stock, unresolved orders, delivery failure records, and presence of database backups.
- [x] Existing tests retained; regression cases added for the new database behaviors.
- [x] CMD setup, start, and test scripts retained.
- [x] Owner `$dm` and `$dmorder` one-to-one customer support DMs with length checks, throttling, Discord rejection handling, and audit records that never store message bodies.
- [x] Owner DM test, history, and campaign controls; owner DM settings summary.
- [x] `$dmoptin on|off` preferences persist in SQLite. Campaign targeting requires opted-in previous buyers in the campaign server and rechecks consent just before each delivery.
- [x] Prefix-only campaign create, separate approval, run, status/history, and cancel commands.
- [x] Plain text or branded embed campaign delivery with `{user}`, `{username}`, `{user_mention}`, `{server}`, and `{shop_name}` placeholders.
- [x] Shared embed builder used by campaign, settings, and DM history views.
- [x] One-response `$help` lists all role groups with complete syntax and access labels; no category argument, dropdowns, pagination, or buttons.
- [x] Owner-only product add/remove/edit/duplicate/stock and coupon management; public product details, wishlist, cart remove/clear, and unpaid order cancellation with finite stock returned.
- [x] Persistent support panel buttons, staff claim, ticket archive and reopen.
- [x] Owner-only SQLite backup creation, listing and integrity verification; manual Windows restore preserves the existing database first.
- [x] Optional SellAuth hosted checkout panel, signature-verified and deduplicated invoice processing notifications, and Discord order-log messages. SellAuth manages paid digital delivery on its storefront.
- [x] Refreshed ticket embed with purchase/support sections and clear ticket rules.

## Existing capabilities retained (not broadened by this upgrade)

- [x] Owner/admin/staff/member role checks.
- [x] Product creation/deactivation, cart, checkout, order status, manual payment reference submission, manual staff verification, delivery status, refund request recording, ticket open/close, audit log, basic analytics.
- [x] Optional Ollama Q&A, OAuth2 opt-in community verification, tracked invites, and opt-in updates.
- [x] Server structure setup/cloning, owner/admin analytics, verification administration, product maintenance, coupons, and the remaining previously slash-only features have prefix equivalents.
- [x] OAuth-consent-only verified-role queue; membership screening completion grants the role only to users who completed the OAuth flow.
- [x] Owner `$serversnapshot create|list|restore` stores role/channel structure locally and restores additively, including authorized cross-server migration, without deleting destination content.
- [x] OAuth consent includes a separate recovery opt-in; only opted-in refresh tokens are stored, encrypted with AES-256-GCM.
- [x] Owner `$pull` plans, queues, paces, and monitors member restores, supports one-member pulls and pause/resume/stop, and only processes opted-in records.
- [x] Pull settings persist in SQLite; optional HTTPS Pull API plan/start/status/control routes require a configured Bearer API key.
- [x] Local pull dashboard binds to loopback only, uses a private short-lived link, and supports planning, single/batch pulls, settings, counters, and pause/resume/stop controls.
- [x] Short aliases added across common member, staff, admin, owner, shop, ticket, verification, backup, product, and campaign commands; original command names remain available.
- [x] Quick `$pull start <new_server_id> <role_id>` uses configured `main` as source and queues the supplied verified role in the destination server.
- [x] Verification panel and OAuth page explain why verification is required, state that IP addresses are not logged/saved, and provide a clear `Verify` button. Old stored IP hashes are nulled during DB startup.
- [x] Verification page and panel text shortened while keeping the reason, privacy note, and Verify action.

## Not implemented

- [ ] Independent stores/guild-scoped catalog, customer, cart, order, and analytics data.
- [ ] Product variants, image galleries, wishlist alerts, reservation expiry, supplier inventory, digital inventory pools, key delivery, and delivery retries.
- [ ] Native payment gateway capture and refunds for the bot's local catalog, PayPal/UPI automation, and LTC provider integration. SellAuth uses its own hosted checkout and native digital delivery; the bot's signed processed-invoice webhook only reports SellAuth orders.
- [ ] Customer CRM, loyalty/VIP/referrals, gift cards, memberships, subscription billing, and reviews. DM promotional consent exists but general CRM consent does not.
- [ ] Ticket transcripts, configurable panel editor, and staff analytics. The existing panel has fixed support choices.
- [ ] Visual embed designer, image renderer/text-on-image, reusable DM templates, and notification template editor.
- [ ] Revenue forecasting, net-profit calculation, supplier analytics, advanced campaign audiences, campaign pause/resume, and export reporting. Current campaigns target opted-in previous buyers who are current members of the same server.
- [ ] Plugin discovery/enablement/settings. The supplied source has no plugin package or plugin registration interface; this upgrade did not invent a conflicting one.
- [ ] Visual automation builder, approval inbox, two-person approval, and advanced Watchtower controls.
- [ ] Automatic backup scheduling and retention policy. SQLite database restore remains manual via `restore.bat` while the bot is stopped. Discord structure snapshots are separate and restored additively with `$serversnapshot restore`.
- [ ] Live Discord, OAuth, payment-provider, and integration testing.

## Verification status

- Python bytecode compilation: pending v0.6.11 source check.
- Built-in SQLite syntax and DM schema insert checks: passed.
- Runtime dependency import and bot-construction check: passed in the configured Python 3.14 virtual environment; 77 prefix commands and aliases are registered, role-filtered help visibility was checked for member/staff/admin/server-owner accounts, and the local slash command tree is empty.
- Pytest suite: not run; `pytest` is unavailable in this environment.
- Remote deletion of previously published Discord slash commands and all live Discord behavior: not tested; the bot must connect once using the updated build to clear Discord's global and server-specific registrations.
- SellAuth live credentials and public HTTPS webhook delivery: not tested; configure them locally using `docs/SELLAUTH_SETUP.md`.
- ZIP integrity: pending v0.6.8 archive build.
