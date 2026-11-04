"""Loopback-only dashboard for planning and controlling member pulls."""
import hmac
import json
import logging
import secrets

from aiohttp import web

log = logging.getLogger("jarvis.dashboard")

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS · Member Pull</title><style>
:root{color-scheme:dark;--bg:#0b0d12;--panel:#151922;--line:#292f3b;--text:#eff2f8;--muted:#9ba5b5;--accent:#8a7cff;--green:#60d394;--red:#f06d78}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20% -10%,#292347 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,sans-serif}main{max-width:1060px;margin:42px auto;padding:0 22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.brand{font-size:13px;letter-spacing:.16em;color:#b6adff;font-weight:800}.top h1{font-size:30px;margin:6px 0}.sub{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{background:linear-gradient(150deg,#171b25,#12151c);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 14px 40px #0003}.wide{grid-column:1/-1}h2{font-size:17px;margin:0 0 14px}label{display:block;color:var(--muted);font-size:13px;margin:12px 0 5px}select,input{width:100%;border:1px solid #343c4b;background:#0d1118;color:var(--text);border-radius:9px;padding:11px;font:inherit}button{border:0;border-radius:9px;background:var(--accent);color:white;padding:10px 14px;font:600 14px system-ui;cursor:pointer;margin:12px 7px 0 0}button.secondary{background:#303746}button.stop{background:#a43d4e}button:disabled{opacity:.45;cursor:not-allowed}.row{display:flex;gap:12px}.row>*{flex:1}.note{color:var(--muted);font-size:13px}.status{font-size:18px;font-weight:700}.counts{color:var(--muted);margin-top:5px}.badge{display:inline-block;border-radius:999px;background:#262b39;color:#c9c3ff;padding:4px 10px;font-size:12px}.message{min-height:22px;color:var(--green);margin-top:9px}.error{color:var(--red)}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:15px}.stat{background:#0e1219;border:1px solid #242a35;border-radius:11px;padding:13px}.stat b{display:block;font-size:22px}.stat span{font-size:12px;color:var(--muted)}footer{color:#788393;font-size:12px;margin:18px 2px}@media(max-width:700px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.stats{grid-template-columns:repeat(2,1fr)}main{margin-top:24px}.top{align-items:flex-start;gap:10px;flex-direction:column}}
</style></head><body><main>
<div class="top"><div><div class="brand">JARVIS · LOCAL CONTROL</div><h1>Pull Members</h1><div class="sub">Restore members who opted into encrypted recovery.</div></div><span class="badge">This computer only</span></div>
<div class="grid">
<section class="card"><h2>Plan a pull</h2><label for="source">Source server</label><select id="source"></select><label for="destination">Destination server</label><select id="destination"></select><div class="row"><div><label for="member">One member ID (optional)</label><input id="member" inputmode="numeric" placeholder="Leave blank for batch"></div><div><label for="limit">Batch limit</label><input id="limit" type="number" min="1" max="1000" value="100"></div></div><button class="secondary" id="plan">Preview</button><button id="start">Start pull</button><div id="planmsg" class="message"></div><div class="note">Only users who checked the recovery consent box are eligible.</div></section>
<section class="card"><h2>Pull status</h2><div id="state" class="status">Loading…</div><div id="detail" class="counts">Connecting to the local bot.</div><div class="stats"><div class="stat"><b id="processed">0</b><span>Processed</span></div><div class="stat"><b id="joined">0</b><span>Joined</span></div><div class="stat"><b id="existing">0</b><span>Already there</span></div><div class="stat"><b id="failed">0</b><span>Needs review</span></div></div><button class="secondary" data-action="pause">Pause</button><button class="secondary" data-action="resume">Resume</button><button class="stop" data-action="stop">Stop</button><button class="secondary" id="refresh">Refresh</button><div id="controlmsg" class="message"></div></section>
<section class="card wide"><h2>Pull settings</h2><div class="row"><div><label for="minDelay">Minimum delay (seconds)</label><input id="minDelay" type="number" min="1" max="60" value="2"></div><div><label for="maxDelay">Maximum delay (seconds)</label><input id="maxDelay" type="number" min="1" max="60" value="4"></div><div><label for="maxMembers">Maximum members per pull</label><input id="maxMembers" type="number" min="1" max="1000" value="100"></div></div><button id="saveSettings" class="secondary">Save settings</button><span id="settingsmsg" class="message"></span><div class="note">Pacing is applied between accounts. Discord can still rate-limit or reject individual accounts.</div></section>
</div><footer>Private local dashboard. Do not publish or forward its access link. Existing verification records without recovery opt-in cannot be pulled.</footer></main>
<script>
const $=id=>document.getElementById(id);let busy=false;
async function api(path,body){const opt={credentials:'same-origin',headers:{'Content-Type':'application/json'}};if(body){opt.method='POST';opt.body=JSON.stringify(body)}const r=await fetch('/api/'+path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||d.message||'Request failed ('+r.status+')');return d}
function fill(id,items,valueKey,label){const el=$(id),old=el.value;el.innerHTML='';for(const x of items){const o=document.createElement('option');o.value=x[valueKey];o.textContent=label(x);el.appendChild(o)}if([...el.options].some(x=>x.value===old))el.value=old}
async function refresh(){try{const d=await api('info');fill('source',d.sources,'id',x=>x.name+' · '+x.eligible+' eligible');fill('destination',d.destinations,'key',x=>x.name+' · '+x.key);$('limit').value=d.settings.limit;$('minDelay').value=d.settings.delay_min;$('maxDelay').value=d.settings.delay_max;const s=d.status||{};$('state').textContent=(s.state||'idle').toUpperCase()+(s.job_id?' · '+s.job_id:'');$('detail').textContent=s.detail||'No pull has run.';const m=(s.detail||'').match(/(\d+)\/(\d+) processed · (\d+) joined · (\d+) already present · (\d+) revoked\/invalid · (\d+) failed/);if(m){$('processed').textContent=m[1]+'/'+m[2];$('joined').textContent=m[3];$('existing').textContent=m[4];$('failed').textContent=Number(m[5])+Number(m[6])}busy=['running','paused','stopping','queued'].includes(s.state);document.querySelectorAll('[data-action]').forEach(b=>b.disabled=!busy)}catch(e){$('state').textContent='Dashboard error';$('detail').textContent=e.message;$('detail').className='counts error'}}
async function runPlan(start){const msg=$('planmsg');msg.className='message';try{const source=Number($('source').value),destination_key=$('destination').value,member_id=$('member').value?Number($('member').value):null;if(!source||!destination_key)throw Error('Choose a source and destination.');if(start){const d=await api('start',{source_server_id:source,destination_key,member_id});msg.textContent='Pull '+d.job_id+' started.'}else{const d=await api('plan',{source_server_id:source,destination_key,member_id});msg.textContent=d.eligible+' eligible · '+d.planned+' planned for this pull · '+d.destination}await refresh()}catch(e){msg.className='message error';msg.textContent=e.message}}
$('plan').onclick=()=>runPlan(false);$('start').onclick=()=>runPlan(true);$('refresh').onclick=refresh;
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{try{const info=await api('info');await api('control',{job_id:info.status.job_id,action:b.dataset.action});$('controlmsg').textContent='Sent '+b.dataset.action+' request.';await refresh()}catch(e){$('controlmsg').className='message error';$('controlmsg').textContent=e.message}});
$('saveSettings').onclick=async()=>{try{await api('settings',{delay_min:Number($('minDelay').value),delay_max:Number($('maxDelay').value),limit:Number($('maxMembers').value)});$('settingsmsg').className='message';$('settingsmsg').textContent='Saved.';await refresh()}catch(e){$('settingsmsg').className='message error';$('settingsmsg').textContent=e.message}};
refresh();setInterval(refresh,2500);
</script></body></html>"""


class PullDashboard:
    def __init__(self, bot, cfg):
        self.bot, self.cfg = bot, cfg
        self.dcfg = cfg.get("local_dashboard", {})
        self.host = "127.0.0.1"
        self.port = int(self.dcfg.get("port", 8790))
        self.token = secrets.token_urlsafe(32)
        self.runner = None
        self.site = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/dashboard/{self.token}"

    def _is_local(self, request, require_cookie=False):
        if request.host != f"127.0.0.1:{self.port}":
            return False
        origin = request.headers.get("Origin")
        if origin and origin != f"http://127.0.0.1:{self.port}":
            return False
        if require_cookie and not hmac.compare_digest(request.cookies.get("jarvis_local_dashboard", ""), self.token):
            return False
        return True

    async def start(self):
        if not self.dcfg.get("enabled", True) or self.runner:
            return
        app = web.Application(client_max_size=16 * 1024)
        app.router.add_get("/", self.root)
        app.router.add_get("/dashboard/{token}", self.page)
        app.router.add_get("/api/info", self.info)
        app.router.add_post("/api/plan", self.plan)
        app.router.add_post("/api/start", self.start_pull)
        app.router.add_post("/api/control", self.control)
        app.router.add_post("/api/settings", self.settings)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        try:
            await self.site.start()
        except Exception:
            await self.runner.cleanup()
            self.runner = self.site = None
            raise
        log.info("Local Pull dashboard: %s", self.url)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = self.site = None

    async def root(self, request):
        if not self._is_local(request):
            raise web.HTTPForbidden()
        return web.Response(text="JARVIS Pull dashboard is local. Run $dashboard in Discord and open the private link sent to the bot owner's DMs.", content_type="text/plain")

    async def page(self, request):
        if not self._is_local(request) or not hmac.compare_digest(request.match_info["token"], self.token):
            raise web.HTTPForbidden(text="Use the private dashboard link printed in the bot log.")
        response = web.Response(text=PAGE, content_type="text/html")
        response.set_cookie("jarvis_local_dashboard", self.token, httponly=True, samesite="Strict", max_age=43200, path="/")
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _authorize(self, request):
        if not self._is_local(request, require_cookie=True):
            raise web.HTTPForbidden(text="Local dashboard authorization required.")

    async def info(self, request):
        self._authorize(request)
        cur = await self.bot.db.conn.execute("SELECT source_guild_id,COUNT(DISTINCT user_id) AS eligible FROM verify_recovery_grants GROUP BY source_guild_id ORDER BY source_guild_id")
        rows = await cur.fetchall()
        target_names = {int(x["guild_id"]): x.get("name", str(x["guild_id"])) for x in self.bot.verify_portal.targets().values()}
        sources = [{"id": row["source_guild_id"], "eligible": row["eligible"],
                    "name": getattr(self.bot.get_guild(row["source_guild_id"]), "name", None) or target_names.get(row["source_guild_id"], f"Source {row['source_guild_id']}")}
                   for row in rows]
        destinations = [{"key": key, "guild_id": int(t["guild_id"]), "name": self.bot.get_guild(int(t["guild_id"])).name}
                        for key, t in self.bot.verify_portal.targets().items() if self.bot.get_guild(int(t["guild_id"]))]
        async def setting(key, default):
            cur = await self.bot.db.conn.execute("SELECT value FROM settings WHERE key=?", (key,)); row = await cur.fetchone()
            return int(row["value"]) if row else default
        return web.json_response({"sources": sources, "destinations": destinations,
            "settings": {"delay_min": await setting("member_pull_delay_min", 2), "delay_max": await setting("member_pull_delay_max", 4), "limit": await setting("member_pull_limit", 100)},
            "status": dict(self.bot.member_restore_status)})

    async def _body(self, request):
        self._authorize(request)
        try:
            return await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Send a JSON request body.")

    async def plan(self, request):
        data = await self._body(request)
        try:
            source_id = int(data["source_server_id"]); destination_key = str(data["destination_key"])
            member_id = int(data["member_id"]) if data.get("member_id") else None
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Choose a source, destination, and optional numeric member ID.")
        target = self.bot.verify_portal.targets().get(destination_key)
        if not target or not self.bot.get_guild(int(target["guild_id"])):
            raise web.HTTPBadRequest(text="Unknown destination or the bot is not in that server.")
        sql = "SELECT COUNT(DISTINCT user_id) AS n FROM verify_recovery_grants WHERE source_guild_id=?" + (" AND user_id=?" if member_id is not None else "")
        cur = await self.bot.db.conn.execute(sql, (source_id, member_id) if member_id is not None else (source_id,)); eligible = (await cur.fetchone())["n"]
        cur = await self.bot.db.conn.execute("SELECT value FROM settings WHERE key='member_pull_limit'"); row = await cur.fetchone()
        limit = 1 if member_id is not None else int(row["value"]) if row else 100
        return web.json_response({"eligible": eligible, "planned": min(eligible, limit), "destination": target.get("name", destination_key)})

    async def start_pull(self, request):
        data = await self._body(request)
        try:
            source_id = int(data["source_server_id"]); destination_key = str(data["destination_key"])
            member_id = int(data["member_id"]) if data.get("member_id") else None
            job = await self.bot.start_member_pull(source_id, destination_key, member_id=member_id, actor_id=0)
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc) or "Invalid pull request.")
        except RuntimeError as exc:
            raise web.HTTPConflict(text=str(exc))
        return web.json_response(job, status=202)

    async def control(self, request):
        data = await self._body(request)
        control = self.bot.member_restore_control; status = self.bot.member_restore_status
        if not control or data.get("job_id") != status.get("job_id") or not self.bot.member_restore_task or self.bot.member_restore_task.done():
            raise web.HTTPConflict(text="No matching active pull.")
        action = data.get("action")
        if action == "pause": control["pause_event"].clear()
        elif action == "resume": control["pause_event"].set()
        elif action == "stop": control["stop"] = True; control["pause_event"].set()
        else: raise web.HTTPBadRequest(text="Choose pause, resume, or stop.")
        status["state"] = {"pause": "paused", "resume": "running", "stop": "stopping"}[action]
        return web.json_response({"job_id": status["job_id"], "state": status["state"]})

    async def settings(self, request):
        data = await self._body(request)
        try:
            low, high, limit = int(data["delay_min"]), int(data["delay_max"]), int(data["limit"])
            if low < 1 or high < low or high > 60 or not 1 <= limit <= 1000: raise ValueError
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Delay must be 1–60 seconds, maximum delay must be at least minimum, and limit must be 1–1000.")
        for key, value in (("member_pull_delay_min", low), ("member_pull_delay_max", high), ("member_pull_limit", limit)):
            await self.bot.db.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        await self.bot.db.conn.commit()
        return web.json_response({"saved": True})
