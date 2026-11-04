# DM Manager (prefix-only)

## Commands

- Owner: `$dm @user message` sends one support DM.
- Owner: `$dmorder ORDER-ID message` contacts that order's customer.
- Owner: `$dmtest @user` sends a delivery test.
- Owner: `$dmhistory @user` checks delivery metadata; message bodies are not logged.
- Owner: `$dmsettings` shows opt-ins and delay. `$dmsettings delay SECONDS` sets a 5–30 second campaign delay.
- Any member: `$dmoptin on` or `$dmoptin off` controls promotional eligibility.
- Owner campaign commands: `$dmcampaign_create [embed] MESSAGE`, `$dmcampaign_approve ID`, `$dmcampaign_run ID`, `$dmcampaign_status ID`, `$dmcampaigns`, and `$dmcampaign_cancel ID`.

Campaign drafts require approval by a different owner. The campaign worker targets opted-in previous buyers who are members of that server, checks consent again before delivery, waits at least five seconds between attempts, and records one attempt per person/campaign. Restarting marks a running campaign interrupted. The bot does not blindly retry uncertain Discord outcomes.

Supported placeholders: `{user}`, `{username}`, `{user_mention}`, `{server}`, and `{shop_name}`. Unknown placeholders become empty strings. Mention notifications are suppressed.

## Limitations

Bulk role, VIP, product-specific, and inactive-customer targeting are not implemented. The current database is single-store, so purchase history is not isolated by server. Saved DM templates, automatic transactional notification templates, campaign pause/resume, and retry recovery are not included. The shared embed builder styles campaign/settings/history messages; it is not a visual embed editor.

One-to-one owner messages are support messages, separate from promotional campaigns and do not require promotional opt-in. Discord can reject DMs when recipients have closed DMs or blocked the bot; failed delivery is reported honestly.
