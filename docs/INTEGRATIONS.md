# Integration status

## Available now

- Discord Gateway and application commands through `discord.py`.
- Optional local Ollama text generation through `httpx`; disabled/unavailable AI does not block shop commands.
- Optional Discord OAuth2 verification through the official authorization-code flow in `core/verify.py`. It requires an application Client ID/secret, callback URL, HTTPS hosting, and explicit user consent. See the README setup guide.
- UPI/manual payment-reference workflow: customers submit a reference and staff review it. The bot does not verify a bank transaction.
- SQLite persistence.

## Not connected

SellAuth, PayPal, LTC providers, Google Sheets, email, Telegram, Discord webhook delivery, payment webhooks, and gateway refunds are not implemented. No endpoint, credential format, or successful transaction behavior is implied for these services.

## Credential handling

Keep Discord and OAuth secrets in `.env`, which is excluded by `.gitignore`. Do not put credentials, payment account data, or digital keys in YAML, product descriptions, or logs. The current implementation does not encrypt `.env` or provide a secrets vault; protect the host and filesystem accordingly.
