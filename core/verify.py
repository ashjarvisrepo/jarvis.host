"""JARVIS VERIFY: explicit-consent Discord OAuth2 onboarding and member recovery.

The portal never asks for Discord passwords. It uses the official authorization-code
flow with identify + guilds.join, validates one-time state, and persists refresh tokens
only for members who separately opt in, encrypted with an operator-managed AES key.
"""
import asyncio
import base64
import html
import hmac
import logging
import os
import random
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlencode

import aiohttp
import discord
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from aiohttp import web

log = logging.getLogger("jarvis.verify")
DISCORD_API = "https://discord.com/api/v10"


def _page(title, body):
    return f"""<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)}</title><style>
:root{{--bg:#090d18;--panel:#111a2c;--line:#263653;--text:#edf3ff;--muted:#a9b8d0;--accent:#8b7cff;}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 20% 0%,#20264b 0,#090d18 48%);font:16px/1.55 system-ui;color:var(--text)}}
main{{width:min(100%,540px);background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:30px;box-shadow:0 22px 70px #0008}}.logo{{font-size:12px;letter-spacing:.22em;color:#b5aaff;font-weight:800}}h1{{font-size:28px;margin:12px 0}}p{{color:var(--muted)}}.server{{padding:14px;border:1px solid var(--line);border-radius:14px;margin:18px 0;background:#0c1424}}label{{display:block;margin:14px 0 6px;font-weight:650}}input{{width:100%;padding:13px;border-radius:10px;border:1px solid #344866;background:#0a1220;color:white;font:inherit}}button,.cta{{display:block;width:100%;margin-top:18px;text-align:center;padding:14px;border:0;border-radius:11px;background:linear-gradient(110deg,#7769ed,#4d9cff);color:white;font-weight:800;font-size:16px;text-decoration:none;cursor:pointer}}small{{color:#8294b2}}.ok{{color:#8ce5b0}}.warn{{color:#ffd28a}}
</style><main><div class='logo'>JARVIS • VERIFY</div>{body}<p><small>Official Discord authorization. JARVIS never asks for your Discord password or security code.</small></p></main></html>"""


class VerifyPortal:
    def __init__(self, bot, cfg, db):
        self.bot, self.cfg, self.db = bot, cfg, db
        self.vcfg = cfg.get("verify", {})
        self.recovery_cipher = None
        encoded_key = str(self.vcfg.get("recovery_key", "")).strip()
        if encoded_key:
            try:
                key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
                if len(key) != 32:
                    raise ValueError("JARVIS_RECOVERY_KEY must decode to 32 bytes")
                self.recovery_cipher = AESGCM(key)
            except Exception as exc:
                log.error("Member recovery is disabled because JARVIS_RECOVERY_KEY is invalid: %s", exc)
        self.states = {}
        self.ip_hits = defaultdict(deque)
        self.runner = None
        self.site = None
        self.pull_controls = {}

    def targets(self):
        return {str(t.get("key")): t for t in self.vcfg.get("targets", []) if t.get("key") and t.get("guild_id")}

    def public_url(self):
        return self.vcfg.get("public_base_url", "").rstrip("/")

    async def start(self):
        if not self.vcfg.get("enabled", False):
            log.info("JARVIS VERIFY is disabled")
        elif not self.vcfg.get("client_id") or not self.vcfg.get("client_secret"):
            log.warning("JARVIS VERIFY enabled but OAuth client_id/client_secret are missing")
        elif not self.public_url() or not self.vcfg.get("redirect_uri"):
            log.warning("JARVIS VERIFY requires public_base_url and redirect_uri (HTTPS in production)")
        app = web.Application(client_max_size=16 * 1024)
        app.router.add_get("/verify/{key}", self.landing)
        app.router.add_post("/verify/{key}/start", self.begin)
        app.router.add_get("/oauth/callback", self.callback)
        app.router.add_post("/api/pulls/plan", self.api_pull_plan)
        app.router.add_post("/api/pulls/start", self.api_pull_start)
        app.router.add_get("/api/pulls/status", self.api_pull_status)
        app.router.add_post("/api/pulls/control", self.api_pull_control)
        app.router.add_get("/health", lambda _: web.json_response({"service": "JARVIS VERIFY", "status": "online"}))
        # Railway exposes one HTTP port per service. Serve the SellAuth callback
        # on that same listener instead of opening an unreachable second port.
        railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT"))
        notifications = getattr(self.bot, "sellauth_notifications", None)
        if railway and notifications and notifications.scfg.get("enabled", False):
            webhook_path = str(notifications.scfg.get("webhook_path", "/sellauth/notifications"))
            if webhook_path.startswith("/") and len(webhook_path) <= 120:
                app.router.add_post(webhook_path, notifications.receive)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        host = self.vcfg.get("host", "127.0.0.1")
        port = int(self.vcfg.get("port", 8787))
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        log.info("JARVIS web service listening on %s:%s", host, port)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    def _rate_limited(self, ip):
        now = time.time(); q = self.ip_hits[ip]
        while q and now - q[0] > 300: q.popleft()
        if len(q) >= int(self.vcfg.get("max_attempts_per_5m", 12)): return True
        q.append(now); return False

    def _pull_api_authorized(self, request):
        key = str(self.vcfg.get("pull_api_key", ""))
        supplied = request.headers.get("Authorization", "")
        return bool(key and supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:], key))

    async def _pull_api_check(self, request):
        if not self.vcfg.get("pull_api_key"):
            raise web.HTTPServiceUnavailable(text="Pull API key is not configured.")
        if not self._pull_api_authorized(request):
            raise web.HTTPUnauthorized(text="A valid Bearer API key is required.", headers={"WWW-Authenticate": "Bearer"})

    async def api_pull_plan(self, request):
        await self._pull_api_check(request)
        try:
            data = await request.json()
            source_id = int(data["source_server_id"])
            destination_key = str(data["destination_key"])
            member_id = int(data["member_id"]) if data.get("member_id") else None
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Expected source_server_id, destination_key, and optional member_id.")
        target = self.targets().get(destination_key)
        if not target or not self.bot.get_guild(int(target["guild_id"])):
            raise web.HTTPBadRequest(text="Unknown destination key or the bot is not in its configured server.")
        query = "SELECT COUNT(DISTINCT user_id) AS n FROM verify_recovery_grants WHERE source_guild_id=?"
        params = [source_id]
        if member_id is not None:
            query += " AND user_id=?"; params.append(member_id)
        cur = await self.db.conn.execute(query, tuple(params))
        eligible = (await cur.fetchone())["n"]
        cur = await self.db.conn.execute("SELECT value FROM settings WHERE key='member_pull_limit'")
        row = await cur.fetchone(); limit = int(row["value"]) if row else 100
        return web.json_response({"eligible": eligible, "planned": min(eligible, 1 if member_id else limit),
                                  "destination": target.get("name", destination_key), "member_only": member_id is not None,
                                  "consent_required": True})

    async def api_pull_start(self, request):
        await self._pull_api_check(request)
        try:
            data = await request.json()
            source_id = int(data["source_server_id"])
            destination_key = str(data["destination_key"])
            member_id = int(data["member_id"]) if data.get("member_id") else None
            job = await self.bot.start_member_pull(source_id, destination_key, member_id=member_id, actor_id=0)
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc) or "Invalid pull request.")
        except RuntimeError as exc:
            raise web.HTTPConflict(text=str(exc))
        return web.json_response({"job_id": job["job_id"], **job}, status=202)

    async def api_pull_status(self, request):
        await self._pull_api_check(request)
        return web.json_response(dict(self.bot.member_restore_status))

    async def api_pull_control(self, request):
        await self._pull_api_check(request)
        try:
            data = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Expected JSON with job_id and action.")
        control = self.bot.member_restore_control
        status = self.bot.member_restore_status
        if not control or data.get("job_id") != status.get("job_id") or not self.bot.member_restore_task or self.bot.member_restore_task.done():
            raise web.HTTPConflict(text="No matching active pull.")
        action = data.get("action")
        if action == "pause":
            control["pause_event"].clear()
        elif action == "resume":
            control["pause_event"].set()
        elif action == "stop":
            control["stop"] = True; control["pause_event"].set()
        else:
            raise web.HTTPBadRequest(text="action must be pause, resume, or stop.")
        status["state"] = {"pause": "paused", "resume": "running", "stop": "stopping"}[action]
        return web.json_response({"job_id": status["job_id"], "state": status["state"]})

    async def landing(self, request):
        key = request.match_info["key"]
        target = self.targets().get(key)
        if not target: raise web.HTTPNotFound(text="Unknown verification destination.")
        if self._rate_limited(request.remote or "unknown"):
            return web.Response(text=_page("Slow down", "<h1>Please wait a moment</h1><p>Too many attempts from this network. Try again shortly.</p>"), content_type="text/html", status=429)
        a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
        state = secrets.token_urlsafe(32)
        self.states[state] = {"key": key, "created": time.time(), "answer": str(a+b)}
        name = html.escape(target.get("name", "Discord community"))
        recovery_option = "<label style='display:flex;gap:10px;align-items:flex-start'><input type='checkbox' name='recovery' value='yes' style='width:auto;margin-top:5px'><span>Optional: save encrypted recovery access so JARVIS can restore you if this server is lost. Revoke access in Discord Authorized Apps.</span></label>" if self.recovery_cipher else "<p class='warn'>Member recovery is unavailable.</p>"
        body = f"<h1>Verify to join {name}</h1><p>Verification helps keep bots out and protects this community.</p><div class='server'><b>{name}</b><br><small>You'll join this server after approving on Discord.</small></div><p><b>Privacy:</b> We don't log or save your IP. JARVIS never asks for your password or MFA code.</p><form method='post' action='/verify/{html.escape(key)}/start'><input type='hidden' name='state' value='{state}'><label for='captcha'>Quick check: {a} + {b} = ?</label><input id='captcha' name='captcha' inputmode='numeric' autocomplete='off' required>{recovery_option}<div style='position:absolute;left:-9999px' aria-hidden='true'><label>Leave this blank<input name='website' tabindex='-1' autocomplete='off'></label></div><button type='submit'>Verify</button></form>"
        return web.Response(text=_page("JARVIS Verify", body), content_type="text/html")

    async def begin(self, request):
        key = request.match_info["key"]
        target = self.targets().get(key)
        if not target: raise web.HTTPNotFound()
        data = await request.post()
        state = str(data.get("state", "")); entry = self.states.get(state)
        if data.get("website") or not entry or entry["key"] != key or time.time()-entry["created"] > 600 or not secrets.compare_digest(str(data.get("captcha", "" )).strip(), entry["answer"]):
            return web.Response(text=_page("Try again", "<h1>Verification could not continue</h1><p>Your check expired or was incorrect. Please reopen the verification link.</p>"), content_type="text/html", status=400)
        entry["recovery_opt_in"] = bool(self.recovery_cipher and data.get("recovery") == "yes")
        params = {"client_id": str(self.vcfg["client_id"]), "response_type": "code", "redirect_uri": self.vcfg["redirect_uri"], "scope": "identify guilds.join", "state": state, "prompt": "consent"}
        return web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode(params))

    async def callback(self, request):
        state = request.query.get("state", "")
        entry = self.states.pop(state, None)
        if not entry or time.time()-entry["created"] > 900:
            return web.Response(text=_page("Link expired", "<h1>This verification link expired</h1><p>Return to the server and request a fresh link.</p>"), content_type="text/html", status=400)
        if request.query.get("error"):
            return web.Response(text=_page("Cancelled", "<h1>Authorization cancelled</h1><p>No changes were made to your Discord account.</p>"), content_type="text/html")
        code = request.query.get("code")
        if not code: raise web.HTTPBadRequest(text="Missing authorization code")
        target = self.targets().get(entry["key"])
        if not target: raise web.HTTPBadRequest(text="Target server is no longer configured")
        client_id = str(self.vcfg["client_id"]); secret = self.vcfg["client_secret"]
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            form = {"client_id": client_id, "client_secret": secret, "grant_type": "authorization_code", "code": code, "redirect_uri": self.vcfg["redirect_uri"]}
            async with session.post(f"{DISCORD_API}/oauth2/token", data=form, headers={"Content-Type":"application/x-www-form-urlencoded"}) as resp:
                token_data = await resp.json(content_type=None)
                if resp.status != 200:
                    log.warning("OAuth token exchange failed: %s", resp.status)
                    return web.Response(text=_page("Authorization failed", "<h1>Discord authorization failed</h1><p>Please retry from the server's official verification link.</p>"), content_type="text/html", status=400)
            access_token = token_data.get("access_token")
            if not access_token: raise web.HTTPBadRequest(text="No access token returned")
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                user = await resp.json(content_type=None)
                if resp.status != 200: raise web.HTTPBadRequest(text="Could not read authorized Discord profile")
            uid = str(user["id"])
            created = discord_created_at(uid)
            min_days = int(self.vcfg.get("min_account_age_days", 0))
            age_days = (time.time() - created) / 86400
            if min_days and age_days < min_days:
                await self._log(uid, target, "rejected_young_account")
                return web.Response(text=_page("Account too new", f"<h1>Account is too new</h1><p>This community requires a Discord account at least {min_days} days old. No server was joined.</p>"), content_type="text/html", status=403)
            guild_id = str(target["guild_id"])
            bot_token = self.cfg["discord"]["token"]
            join_headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
            async with session.put(f"{DISCORD_API}/guilds/{guild_id}/members/{uid}", json={"access_token": access_token}, headers=join_headers) as resp:
                if resp.status not in (201, 204):
                    detail = await resp.text()
                    log.warning("Guild join failed for target %s: %s %s", entry["key"], resp.status, detail[:300])
                    return web.Response(text=_page("Could not join", "<h1>Could not complete server join</h1><p>The bot may need to be added to this server with Create Invite permission. Please contact the server owner.</p>"), content_type="text/html", status=502)
        recovery_saved = False
        refresh_token = token_data.get("refresh_token")
        if entry.get("recovery_opt_in") and refresh_token and self.recovery_cipher:
            encrypted = self._encrypt_recovery_token(uid, guild_id, entry["key"], refresh_token)
            await self.db.conn.execute("""INSERT INTO verify_recovery_grants(user_id,source_guild_id,target_key,token_ciphertext,granted_at,updated_at)
              VALUES(?,?,?,?,datetime('now'),datetime('now')) ON CONFLICT(user_id,source_guild_id,target_key)
              DO UPDATE SET token_ciphertext=excluded.token_ciphertext,updated_at=datetime('now')""",
              (int(uid), int(guild_id), str(entry["key"]), encrypted))
            await self.db.conn.commit()
            recovery_saved = True
        elif not entry.get("recovery_opt_in"):
            await self.db.conn.execute("DELETE FROM verify_recovery_grants WHERE user_id=? AND source_guild_id=? AND target_key=?", (int(uid), int(guild_id), str(entry["key"])))
            await self.db.conn.commit()
        # Queue a role only after explicit OAuth consent succeeded. The gateway
        # listener later releases it after Discord Membership Screening ends.
        role_id = int(target.get("role_id", 0) or 0)
        if role_id:
            await self.db.conn.execute(
                "INSERT OR IGNORE INTO verify_pending_roles(user_id,guild_id,target_key,role_id,created_at) VALUES(?,?,?, ?,datetime('now'))",
                (int(uid), int(target["guild_id"]), str(target.get("key")), role_id),
            )
            await self.db.conn.commit()
            guild = self.bot.get_guild(int(target["guild_id"]))
            if guild:
                try:
                    member = await guild.fetch_member(int(uid))
                    await self.bot.assign_explicitly_verified_role(member)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    log.info("Explicit verification role remains queued until the member is available")
        await self._log(uid, target, "joined")
        invite = target.get("invite_url", "")
        name = html.escape(target.get("name", "your community"))
        extra = f"<a class='cta' href='{html.escape(invite, quote=True)}'>Open {name} in Discord</a>" if invite else "<p class='ok'>You have been added to the community. Open Discord to continue.</p>"
        recovery_note = "Your encrypted recovery grant was saved; an owner may use it to rejoin you to a replacement server if needed. Revoke it in Discord Authorized Apps." if recovery_saved else "No future recovery grant was saved."
        return web.Response(text=_page("Verified", f"<h1 class='ok'>You're verified!</h1><p>Your Discord account was authorized and the server join was processed.</p>{extra}<p><small>If Discord has Membership Screening enabled, complete its rules screen to unlock the verified role. The role is granted only for this explicit verification.</small></p><p><small>{recovery_note}</small></p>"), content_type="text/html")

    def _encrypt_recovery_token(self, user_id, guild_id, target_key, token):
        nonce = secrets.token_bytes(12)
        aad = f"{user_id}:{guild_id}:{target_key}".encode()
        value = self.recovery_cipher.encrypt(nonce, token.encode(), aad)
        return base64.urlsafe_b64encode(nonce + value).decode("ascii")

    def _decrypt_recovery_token(self, user_id, guild_id, target_key, encrypted):
        packed = base64.urlsafe_b64decode(encrypted.encode("ascii"))
        aad = f"{user_id}:{guild_id}:{target_key}".encode()
        return self.recovery_cipher.decrypt(packed[:12], packed[12:], aad).decode("utf-8")

    async def restore_members(self, source_guild_id, destination_key, member_id=None, control=None,
                              delay_range=(2.0, 4.0), progress_callback=None, max_members=100):
        """Rejoin only people who explicitly opted in during OAuth verification."""
        if not self.recovery_cipher:
            raise RuntimeError("Encrypted recovery is not configured. Set JARVIS_RECOVERY_KEY and restart.")
        target = self.targets().get(destination_key)
        if not target:
            raise ValueError("Destination verification key is not configured.")
        destination_guild = self.bot.get_guild(int(target["guild_id"]))
        if not destination_guild:
            raise ValueError("The bot must be in the destination server.")
        query = "SELECT * FROM verify_recovery_grants WHERE source_guild_id=?"
        params = [int(source_guild_id)]
        if member_id is not None:
            query += " AND user_id=?"
            params.append(int(member_id))
        query += " ORDER BY updated_at DESC"
        cur = await self.db.conn.execute(query, tuple(params))
        rows = await cur.fetchall()
        grants = []
        seen_users = set()
        for row in rows:
            if row["user_id"] in seen_users:
                continue
            seen_users.add(row["user_id"])
            grants.append(row)
        grants = grants[:max(1, int(max_members))]
        counts = {"eligible": len(grants), "processed": 0, "joined": 0, "already_or_queued": 0, "revoked_or_invalid": 0, "failed": 0, "stopped": False}
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for grant in grants:
                if control:
                    if control.get("stop"):
                        counts["stopped"] = True
                        break
                    pause_event = control.get("pause_event")
                    if pause_event:
                        await pause_event.wait()
                    if control.get("stop"):
                        counts["stopped"] = True
                        break
                uid = int(grant["user_id"])
                try:
                    refresh_token = self._decrypt_recovery_token(uid, grant["source_guild_id"], grant["target_key"], grant["token_ciphertext"])
                    async with session.post(f"{DISCORD_API}/oauth2/token", data={
                        "client_id": str(self.vcfg["client_id"]), "client_secret": self.vcfg["client_secret"],
                        "grant_type": "refresh_token", "refresh_token": refresh_token,
                    }, headers={"Content-Type": "application/x-www-form-urlencoded"}) as resp:
                        token_data = await resp.json(content_type=None)
                        if resp.status == 429:
                            await asyncio.sleep(min(float(token_data.get("retry_after", 1)), 30))
                            async with session.post(f"{DISCORD_API}/oauth2/token", data={
                                "client_id": str(self.vcfg["client_id"]), "client_secret": self.vcfg["client_secret"],
                                "grant_type": "refresh_token", "refresh_token": refresh_token,
                            }, headers={"Content-Type": "application/x-www-form-urlencoded"}) as retry_resp:
                                token_data = await retry_resp.json(content_type=None)
                                if retry_resp.status != 200:
                                    counts["failed"] += 1
                                    counts["processed"] += 1
                                    if progress_callback: await progress_callback(dict(counts))
                                    await asyncio.sleep(random.uniform(float(delay_range[0]), float(delay_range[1])))
                                    continue
                            resp_status = 200
                        else:
                            resp_status = resp.status
                        if resp_status != 200:
                            if resp_status in (400, 401):
                                await self.db.conn.execute("DELETE FROM verify_recovery_grants WHERE user_id=? AND source_guild_id=? AND target_key=?", (uid, grant["source_guild_id"], grant["target_key"]))
                                counts["revoked_or_invalid"] += 1
                            else:
                                counts["failed"] += 1
                            counts["processed"] += 1
                            if progress_callback: await progress_callback(dict(counts))
                            await asyncio.sleep(random.uniform(float(delay_range[0]), float(delay_range[1])))
                            continue
                    fresh_refresh = token_data.get("refresh_token", refresh_token)
                    encrypted = self._encrypt_recovery_token(uid, grant["source_guild_id"], grant["target_key"], fresh_refresh)
                    await self.db.conn.execute("UPDATE verify_recovery_grants SET token_ciphertext=?,updated_at=datetime('now') WHERE user_id=? AND source_guild_id=? AND target_key=?", (encrypted, uid, grant["source_guild_id"], grant["target_key"]))
                    headers = {"Authorization": f"Bot {self.cfg['discord']['token']}", "Content-Type": "application/json"}
                    async with session.put(f"{DISCORD_API}/guilds/{destination_guild.id}/members/{uid}", json={"access_token": token_data["access_token"]}, headers=headers) as resp:
                        if resp.status in (201, 204):
                            if resp.status == 201: counts["joined"] += 1
                            else: counts["already_or_queued"] += 1
                            role_id = int(target.get("role_id", 0) or 0)
                            if role_id:
                                await self.db.conn.execute("INSERT OR IGNORE INTO verify_pending_roles(user_id,guild_id,target_key,role_id,created_at) VALUES(?,?,?,?,datetime('now'))", (uid, destination_guild.id, destination_key, role_id))
                                try:
                                    member = destination_guild.get_member(uid) or await destination_guild.fetch_member(uid)
                                    await self.bot.assign_explicitly_verified_role(member)
                                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                                    pass
                        elif resp.status == 429:
                            detail = await resp.json(content_type=None)
                            await asyncio.sleep(min(float(detail.get("retry_after", 1)), 30))
                            retry_headers = {"Authorization": f"Bot {self.cfg['discord']['token']}", "Content-Type": "application/json"}
                            async with session.put(f"{DISCORD_API}/guilds/{destination_guild.id}/members/{uid}", json={"access_token": token_data["access_token"]}, headers=retry_headers) as retry_resp:
                                if retry_resp.status in (201, 204):
                                    if retry_resp.status == 201: counts["joined"] += 1
                                    else: counts["already_or_queued"] += 1
                                    role_id = int(target.get("role_id", 0) or 0)
                                    if role_id:
                                        await self.db.conn.execute("INSERT OR IGNORE INTO verify_pending_roles(user_id,guild_id,target_key,role_id,created_at) VALUES(?,?,?,?,datetime('now'))", (uid, destination_guild.id, destination_key, role_id))
                                        try:
                                            member = destination_guild.get_member(uid) or await destination_guild.fetch_member(uid)
                                            await self.bot.assign_explicitly_verified_role(member)
                                        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                                            pass
                                else:
                                    counts["failed"] += 1
                        else:
                            counts["failed"] += 1
                    await self.db.conn.commit()
                except Exception:
                    log.exception("Member recovery failed for a single opted-in account")
                    counts["failed"] += 1
                counts["processed"] += 1
                if progress_callback:
                    await progress_callback(dict(counts))
                await asyncio.sleep(random.uniform(float(delay_range[0]), float(delay_range[1])))
        await self.db.conn.commit()
        return counts

    async def _log(self, uid, target, result):
        await self.db.conn.execute("INSERT INTO verify_events(user_id,guild_id,target_key,result,ip_hash,created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (int(uid), int(target["guild_id"]), str(target.get("key")), result, None))
        await self.db.conn.commit()


def discord_created_at(user_id):
    # Discord snowflake epoch: 2015-01-01 UTC, milliseconds in upper bits.
    return ((int(user_id) >> 22) + 1420070400000) / 1000
