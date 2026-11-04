"""Signed SellAuth order notifications for the Discord shop bot."""
import hashlib
import hmac
import json
import logging
import os
import time

from aiohttp import web
import discord

log = logging.getLogger("jarvis.sellauth")


class SellAuthNotifications:
    def __init__(self, bot, cfg, db):
        self.bot, self.cfg, self.db = bot, cfg, db
        self.scfg = cfg.get("sellauth", {})
        self.runner = None
        self.site = None

    async def start(self):
        if not self.scfg.get("enabled", False):
            return
        # Railway routes one public HTTP port. Its webhook is registered on
        # VerifyPortal's shared PORT listener instead of a second socket.
        if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT"):
            log.info("SellAuth webhook will use the shared Railway web listener")
            return
        if not self.scfg.get("webhook_secret") or not int(self.scfg.get("shop_id", 0) or 0):
            log.warning("SellAuth notifications need a shop_id and webhook secret; webhook listener not started")
            return
        path = str(self.scfg.get("webhook_path", "/sellauth/notifications"))
        if not path.startswith("/") or len(path) > 120:
            log.error("SellAuth webhook_path must begin with / and be at most 120 characters")
            return
        app = web.Application(client_max_size=32 * 1024)
        app.router.add_post(path, self.receive)
        self.runner = web.AppRunner(app, access_log=None)
        host = self.scfg.get("webhook_host", "0.0.0.0")
        port = int(self.scfg.get("webhook_port", 8788))
        try:
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, host, port)
            await self.site.start()
        except OSError:
            log.exception("Could not start SellAuth webhook listener on %s:%s", host, port)
            await self.runner.cleanup()
            self.runner = self.site = None
            return
        log.info("SellAuth webhook listening on %s:%s%s", host, port, path)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def receive(self, request):
        raw = await request.read()
        supplied = request.headers.get("X-Signature", "").strip().lower()
        secret = str(self.scfg.get("webhook_secret", ""))
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not supplied or not hmac.compare_digest(supplied, expected):
            return web.json_response({"error": "invalid signature"}, status=401)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"error": "invalid JSON"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid notification"}, status=400)

        try:
            if int(payload.get("shop_id", 0)) != int(self.scfg.get("shop_id", 0)):
                return web.json_response({"error": "wrong shop"}, status=403)
        except (TypeError, ValueError):
            return web.json_response({"error": "invalid shop"}, status=400)

        event = str(payload.get("event", ""))[:120]
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        invoice_id = str(data.get("invoice_id", ""))[:80]
        if not event or not invoice_id:
            return web.json_response({"error": "missing event data"}, status=400)

        event_key = request.headers.get("Idempotency-Key", "").strip()
        if not event_key:
            event_key = hashlib.sha256(event.encode() + b":" + invoice_id.encode() + b":" + raw).hexdigest()
        event_key = event_key[:180]
        payload_hash = hashlib.sha256(raw).hexdigest()
        try:
            cur = await self.db.conn.execute(
                "INSERT OR IGNORE INTO sellauth_events(event_key,event,invoice_id,payload_hash,received_at,status) VALUES(?,?,?,?,?,'pending')",
                (event_key, event, invoice_id, payload_hash, str(int(time.time()))),
            )
            await self.db.conn.commit()
            cur = await self.db.conn.execute("SELECT event_key,status FROM sellauth_events WHERE payload_hash=?", (payload_hash,))
            event_row = await cur.fetchone()
        except Exception:
            log.exception("Could not record SellAuth notification")
            return web.json_response({"error": "temporary storage error"}, status=503)
        if event_row and event_row["status"] == "processed":
            return web.json_response({"ok": True, "duplicate": True})
        if event_row:
            event_key = event_row["event_key"]

        if event == "NOTIFICATION.SHOP_INVOICE_PROCESSED":
            channel_id = int(self.cfg.get("shop", {}).get("order_log_channel_id", 0) or 0)
            channel = self.bot.get_channel(channel_id) if channel_id else None
            if channel is None and channel_id:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    log.exception("Could not fetch the configured order log channel for SellAuth event")
                    return web.json_response({"error": "order log channel unavailable"}, status=503)
            if channel:
                embed = discord.Embed(
                    title="SellAuth payment confirmed",
                    description=f"Invoice `{invoice_id}` was processed. SellAuth has completed the configured delivery.",
                    colour=0xB32936,
                )
                embed.set_footer(text="SellAuth webhook · signature verified")
                try:
                    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    log.exception("Could not post SellAuth invoice notification")
                    return web.json_response({"error": "could not post order notification"}, status=503)
        else:
            log.info("Received SellAuth notification %s for invoice %s", event, invoice_id)
        await self.db.conn.execute("UPDATE sellauth_events SET status='processed' WHERE event_key=?", (event_key,))
        await self.db.conn.commit()
        return web.json_response({"ok": True})
