# SellAuth checkout and auto-buy panel

The optional auto-buy panel links customers to your SellAuth storefront. SellAuth hosts checkout, confirms payment through your configured payment methods, and delivers the digital items configured on each product after payment clears. The bot does not handle or expose product keys in Discord. See SellAuth's [checkout guide](https://docs.sellauth.com/guides/checkout) and [digital delivery guide](https://docs.sellauth.com/guides/delivery).

## Configure the shop

1. Create the products in SellAuth and configure their digital delivery there (for example, serials/keys or files). Keep product stock current in SellAuth.
2. Copy `.env.example` to `.env` if needed. Set `SELLAUTH_STORE_URL` to the full HTTPS storefront URL.
3. In `config/settings.yaml`, set `sellauth.enabled: true`, your numeric `sellauth.shop_id`, and `shop.order_log_channel_id` to the Discord channel where payment notices should appear.
4. In SellAuth's developer settings, create or copy the shop webhook secret and put it in `.env` as `SELLAUTH_WEBHOOK_SECRET`. Do not paste the secret into Discord or commit `.env`.
5. Make the bot's webhook listener reachable through an HTTPS reverse proxy or secure tunnel. The listener defaults to port `8788` and path `/sellauth/notifications`; configure SellAuth's HTTP notification URL as `https://YOUR-DOMAIN/sellauth/notifications` and subscribe to processed invoice notifications. Route that HTTPS path to the bot's configured local host and port.
6. Start the bot, then run `$autobuypanel` in the channel where you want the panel.

The panel's **Browse & Buy** button opens the SellAuth storefront. Its **Support Ticket** button creates a private JARVIS support ticket. The bot verifies each notification's HMAC signature against the raw request body, checks the configured shop ID, and deduplicates repeated payloads before posting the invoice number to the order log channel. SellAuth's HTTP notifications contain minimal data; the bot intentionally logs only the invoice ID, not buyer payment details or digital deliverables. See the [SellAuth HTTP notifications documentation](https://docs.sellauth.com/developers/http-notifications).

The webhook reports that SellAuth processed an invoice; it does not mark orders in the bot's separate local SQLite catalog as paid. The local `$paymentverify` workflow remains separate. The SellAuth confirmation appears in Discord only if the order log channel is configured and the public HTTPS webhook is reachable.
