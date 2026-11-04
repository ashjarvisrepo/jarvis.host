# Database migration notes

The bot applies additive SQLite schema changes automatically when it connects. Stop the bot and make a copy of `data/jarvis_shop.sqlite3` before upgrading.

## v0.6.0

- Adds `dm_preferences` for each Discord user's promotional opt-in state.
- Adds `dm_campaigns` for campaign content, approval, state, and summary counts.
- Adds `dm_campaign_deliveries`, uniquely keyed by campaign and recipient, for delivery results.
- Adds `embed_enabled` to an existing `dm_campaigns` table if upgrading from an earlier development build.
- Adds `dm_campaign_delay_seconds` to the existing `settings` table only when an owner changes the setting.
- Leaves existing users, products, carts, orders, order items, tickets, coupons, audit rows, and verification records in place.

No manual SQL migration is needed. On first startup, the bot creates the new tables and commits the additive changes. The current app still uses a shared single SQLite database and does not isolate shop data by guild/store. Use `$backup create` before upgrading; verify with `$backup verify FILENAME`.

For a manual restore, stop the bot and use `restore.bat FILENAME.sqlite3` from the extracted project folder. The script copies the current database into `backups/` before replacing it.
