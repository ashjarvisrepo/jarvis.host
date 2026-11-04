"""Private web dashboard for planning and controlling opted-in member pulls."""
import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import time
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web
from core.server_snapshots import capture as capture_server_structure, restore as restore_server_structure

log = logging.getLogger("jarvis.dashboard")

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS · Server Dashboard</title><style>
:root{color-scheme:dark;--bg:#0b0d12;--panel:#151922;--line:#292f3b;--text:#eff2f8;--muted:#9ba5b5;--accent:#8a7cff;--green:#60d394;--red:#f06d78}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20% -10%,#292347 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,sans-serif}main{max-width:1060px;margin:42px auto;padding:0 22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.brand{font-size:13px;letter-spacing:.16em;color:#b6adff;font-weight:800}.top h1{font-size:30px;margin:6px 0}.sub{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{background:linear-gradient(150deg,#171b25,#12151c);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 14px 40px #0003;animation:rise .45s ease both;transition:transform .2s,border-color .2s}.card:hover{transform:translateY(-2px);border-color:#4a4567}.wide{grid-column:1/-1}h2{font-size:17px;margin:0 0 14px}label{display:block;color:var(--muted);font-size:13px;margin:12px 0 5px}select,input{width:100%;border:1px solid #343c4b;background:#0d1118;color:var(--text);border-radius:9px;padding:11px;font:inherit}button{border:0;border-radius:9px;background:var(--accent);color:white;padding:10px 14px;font:600 14px system-ui;cursor:pointer;margin:12px 7px 0 0;transition:transform .16s,filter .16s}button:hover{transform:translateY(-1px);filter:brightness(1.12)}button.secondary{background:#303746}button.stop{background:#a43d4e}button:disabled{opacity:.45;cursor:not-allowed}.row{display:flex;gap:12px}.row>*{flex:1}.note{color:var(--muted);font-size:13px}.status{font-size:18px;font-weight:700}.counts{color:var(--muted);margin-top:5px}.badge{display:inline-block;border-radius:999px;background:#262b39;color:#c9c3ff;padding:4px 10px;font-size:12px}.message{min-height:22px;color:var(--green);margin-top:9px}.error{color:var(--red)}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:15px}.stat{background:#0e1219;border:1px solid #242a35;border-radius:11px;padding:13px}.stat b{display:block;font-size:22px}.stat span{font-size:12px;color:var(--muted)}footer{color:#788393;font-size:12px;margin:18px 2px}@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}@media(max-width:700px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.stats{grid-template-columns:repeat(2,1fr)}main{margin-top:24px}.top{align-items:flex-start;gap:10px;flex-direction:column}}
.server-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}.server-card{background:#100f10;border:1px solid #292526;border-radius:14px;padding:16px}.server-head{display:flex;align-items:center;gap:12px}.server-icon{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#242126;font-weight:750}.server-head strong{flex:1}.server-card p{color:var(--muted);font-size:13px;margin:10px 0}.server-card button{background:#147a45}.brand-preview{--preview-accent:#6c63ff;border:1px solid #343c4b;border-radius:10px;padding:10px;display:flex;align-items:center;justify-content:space-between;gap:8px}.brand-preview button{background:var(--preview-accent);margin:0}.checks{display:flex;gap:22px;flex-wrap:wrap}.checks label{display:flex;align-items:center;gap:8px}.checks input{width:auto}.team-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}.team-row button{margin:0}.dash-nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px;padding:8px;background:#11141b;border:1px solid var(--line);border-radius:13px;position:sticky;top:8px;z-index:5;backdrop-filter:blur(12px)}.dash-nav a{color:var(--muted);text-decoration:none;padding:8px 12px;border-radius:8px;font-size:13px;font-weight:650}.dash-nav a:hover,.dash-nav a.active{color:var(--text);background:#27243b}.section-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.13em;color:#a89fff;margin-bottom:5px}.card{scroll-margin-top:82px}.empty-destination{padding:14px;border:1px dashed #42495a;border-radius:10px;color:var(--muted);margin-top:8px}@media(max-width:700px){.server-list{grid-template-columns:1fr}.row{flex-direction:column}.dash-nav{position:static}}
</style></head><body><main>
<div class="top"><div><div class="brand">JARVIS · PRIVATE SERVER DASHBOARD</div><h1>Server workspace</h1><div class="sub">Manage member recovery and copy server structure from one server to another.</div></div><span class="badge">Private Discord sign-in</span></div>
<nav class="dash-nav" aria-label="Dashboard sections"><a href="#servers" class="active">Servers</a><a href="#pullControls">Pull members</a><a href="#cloneSettings" id="navClone" hidden>Clone server</a><a href="#pullStatus">Activity</a><a href="#teamSettings" id="navTeam" hidden>Team access</a><a href="#brandSettings" id="navBrand" hidden>Verification page</a></nav>
<div class="grid">
<section class="card wide" id="servers"><div class="section-kicker">Your communities</div><h2>Source servers</h2><div class="sub">Pick a server to see recovery opt-ins. Only members who chose optional recovery are eligible.</div><div id="serverList" class="server-list"></div><div id="emptySources" class="note" hidden>JARVIS is not in any servers yet. Add the bot to the source server first.</div></section>
<section class="card wide" id="destinationSettings" hidden><div class="section-kicker">Setup</div><h2>Connect a destination server</h2><div class="sub">Choose a server JARVIS has joined. Once connected, it appears in the destination picker below.</div><label for="newServer">Server to connect</label><select id="newServer"></select><div class="row"><div><label for="newKey">Short server name</label><input id="newKey" maxlength="32" placeholder="backup"></div><div><label for="newRole">Role to give (optional)</label><input id="newRole" inputmode="numeric" placeholder="Leave blank for no role"></div></div><button id="addDestination">Connect server</button><div id="targetmsg" class="message"></div><div class="note">The bot must already be in the server. If it is missing, invite JARVIS there and refresh this page.</div></section>
<section class="card wide" id="pullControls"><div class="section-kicker">Recovery</div><h2>Pull opted-in members</h2><div class="sub">Select the destination for this pull. You can switch it any time before starting.</div><div class="row"><div><label for="source">Source server</label><select id="source"></select></div><div><label for="destination">Destination server</label><select id="destination"></select><div id="noDestinations" class="empty-destination" hidden>No destination connected yet. Connect one above, then refresh the picker.</div></div></div><label for="member">Single member ID (optional)</label><input id="member" inputmode="numeric" placeholder="Leave blank to plan a batch"><button class="secondary" id="plan">Preview pull</button><button id="start">Start pull</button><div id="planmsg" class="message"></div></section>
<section class="card wide" id="cloneSettings" hidden><div class="section-kicker">Server setup</div><h2>Clone server structure</h2><div class="sub">Copy roles, categories, and text/voice channel layout into another server you own.</div><div class="row"><div><label for="cloneSource">Source server</label><select id="cloneSource"></select></div><div><label for="cloneDestination">Destination server</label><select id="cloneDestination"></select></div></div><div class="note">Create the destination server in Discord first and invite JARVIS with Manage Roles and Manage Channels. This adds missing structure and leaves existing destination items in place. Members, messages, personal permission overrides, integrations, and webhooks are not copied.</div><button class="secondary" id="clonePreview">Preview clone</button><div id="clonePreviewResult" class="message"></div><div class="checks"><label><input id="cloneConfirm" type="checkbox"> I own both servers or am an authorized bot owner, and understand this adds structure to the destination.</label></div><button id="cloneStart" disabled>Start structure clone</button><div id="cloneStatus" class="message"></div></section>
<section class="card" id="pullStatus"><div class="section-kicker">Live activity</div><h2>Pull status</h2><div id="state" class="status">Loading…</div><div id="detail" class="counts">Checking bot status.</div><div class="stats"><div class="stat"><b id="processed">0</b><span>Processed</span></div><div class="stat"><b id="joined">0</b><span>Joined</span></div><div class="stat"><b id="existing">0</b><span>Already there</span></div><div class="stat"><b id="failed">0</b><span>Needs review</span></div></div><button class="secondary" data-action="pause">Pause</button><button class="secondary" data-action="resume">Resume</button><button class="stop" data-action="stop">Stop</button><button class="secondary" id="refresh">Refresh</button><div id="controlmsg" class="message"></div></section>
<section class="card wide" id="pullSettings" hidden><h2>Pull settings</h2><div class="row"><div><label for="minDelay">Minimum delay (seconds)</label><input id="minDelay" type="number" min="1" max="60" value="2"></div><div><label for="maxDelay">Maximum delay (seconds)</label><input id="maxDelay" type="number" min="1" max="60" value="4"></div><div><label for="maxMembers">Maximum members per pull</label><input id="maxMembers" type="number" min="1" max="1000" value="100"></div></div><button id="saveSettings" class="secondary">Save settings</button><span id="settingsmsg" class="message"></span><div class="note">Pacing is applied between accounts. Discord can still rate-limit or reject individual accounts.</div></section>
<section class="card wide" id="brandSettings" hidden><h2>Verification page look</h2><div class="sub">Choose an accent color and brand label for the public verification page.</div><div class="row"><div><label for="brandColor">Accent color</label><input id="brandColor" type="color" value="#6c63ff"></div><div><label for="brandLabel">Brand label</label><input id="brandLabel" maxlength="40" value="JARVIS • Community Security"></div><div><label>Preview</label><div id="brandPreview" class="brand-preview"><b>Verify to Unlock</b><button type="button" tabindex="-1">Verify</button></div></div></div><button id="saveBrand" class="secondary">Save verification look</button><span id="brandmsg" class="message"></span></section>
<section class="card wide" id="teamSettings" hidden><h2>Team access</h2><div class="sub">Give a Discord user access to one server. Choose only the actions they need.</div><div class="row"><div><label for="teamUser">Discord user ID</label><input id="teamUser" inputmode="numeric" placeholder="User ID"></div><div><label for="teamServer">Server</label><select id="teamServer"></select></div></div><div class="checks"><label><input id="permView" type="checkbox"> View recovery member counts</label><label><input id="permPull" type="checkbox"> Pull opted-in members to this server</label></div><button id="saveTeam">Save access</button><span id="teammsg" class="message"></span><div id="teamList" class="note"></div></section>
</div><footer>Member pulls include only accounts that opted into recovery. Structure clones add missing roles and channels to an existing destination server; they do not create a Discord server or copy its members and messages.</footer></main>
<script>
const $=id=>document.getElementById(id);let busy=false,clonePreviewReady=false,cloneJobId='';
const API_BASE='/api/';
const CSRF_TOKEN='__CSRF_TOKEN__';
async function api(path,body){const opt={credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF_TOKEN}};if(body){opt.method='POST';opt.body=JSON.stringify(body)}const r=await fetch(API_BASE+path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||d.message||'Request failed ('+r.status+')');return d}
function fill(id,items,valueKey,label){const el=$(id),old=el.value;el.innerHTML='';for(const x of items){const o=document.createElement('option');o.value=x[valueKey];o.textContent=label(x);el.appendChild(o)}if([...el.options].some(x=>x.value===old))el.value=old}
function drawServers(sources){const list=$('serverList');list.innerHTML='';$('emptySources').hidden=sources.length>0;for(const server of sources){const card=document.createElement('article');card.className='server-card';const head=document.createElement('div');head.className='server-head';const icon=document.createElement('span');icon.className='server-icon';icon.textContent=server.name.slice(0,2).toUpperCase();const name=document.createElement('strong');name.textContent=server.name;const count=document.createElement('span');count.className='badge';count.textContent=server.eligible+' eligible';head.append(icon,name,count);const note=document.createElement('p');note.textContent='Members who explicitly opted in to recovery from this server.';const button=document.createElement('button');button.textContent='Pull Members';button.onclick=()=>{$('source').value=String(server.id);$('pullControls').scrollIntoView({behavior:'smooth',block:'start'})};card.append(head,note,button);list.appendChild(card)}}
function drawTeam(rows){const box=$('teamList');box.innerHTML='';if(!rows.length){box.textContent='No sub-users yet.';return}for(const x of rows){const row=document.createElement('div');row.className='team-row';const label=document.createElement('span');label.textContent=x.user_id+' · '+x.server_name+' · '+Object.keys(x.permissions).filter(k=>x.permissions[k]).map(k=>k==='view_members'?'View members':'Pull members').join(', ');const remove=document.createElement('button');remove.className='secondary';remove.textContent='Remove';remove.onclick=async()=>{try{await api('team',{action:'remove',user_id:x.user_id,server_id:x.server_id});await refresh()}catch(e){$('teammsg').className='message error';$('teammsg').textContent=e.message}};row.append(label,remove);box.appendChild(row)}}
async function refresh(){try{const d=await api('info');fill('source',d.sources,'id',x=>x.name+' · '+x.eligible+' eligible');fill('destination',d.destinations,'key',x=>x.name);fill('newServer',d.available_guilds,'id',x=>x.name);fill('teamServer',d.guilds||[],'id',x=>x.name);fill('cloneSource',d.clone_guilds||[],'id',x=>x.name);fill('cloneDestination',d.clone_guilds||[],'id',x=>x.name);drawServers(d.sources);$('maxMembers').value=d.settings.limit;$('minDelay').value=d.settings.delay_min;$('maxDelay').value=d.settings.delay_max;$('brandColor').value=d.branding.color;$('brandLabel').value=d.branding.label;$('brandPreview').style.setProperty('--preview-accent',d.branding.color);$('teamSettings').hidden=!d.is_owner;$('brandSettings').hidden=!d.is_owner;$('pullSettings').hidden=!d.is_owner;$('navTeam').hidden=!d.is_owner;$('navBrand').hidden=!d.is_owner;$('destinationSettings').hidden=!d.can_manage_servers;$('noDestinations').hidden=d.destinations.length>0;$('destination').disabled=d.destinations.length===0;const canClone=(d.clone_guilds||[]).length>=2;$('cloneSettings').hidden=!canClone;$('navClone').hidden=!canClone;if(d.is_owner)drawTeam(d.team||[]);const s=d.status||{};$('state').textContent=(s.state||'idle').toUpperCase()+(s.job_id?' · '+s.job_id:'');$('detail').textContent=s.detail||'No pull has run.';const m=(s.detail||'').match(/(\d+)\/(\d+) processed · (\d+) joined · (\d+) already present · (\d+) revoked\/invalid · (\d+) failed/);if(m){$('processed').textContent=m[1]+'/'+m[2];$('joined').textContent=m[3];$('existing').textContent=m[4];$('failed').textContent=Number(m[5])+Number(m[6])}busy=['running','paused','stopping','queued'].includes(s.state);document.querySelectorAll('[data-action]').forEach(b=>b.disabled=!busy);$('newServer').disabled=d.available_guilds.length===0;if(!d.available_guilds.length)$('newServer').innerHTML='<option value="">No unconnected bot servers</option>'}catch(e){$('state').textContent='Dashboard error';$('detail').textContent=e.message;$('detail').className='counts error'}}
async function runPlan(start){const msg=$('planmsg');msg.className='message';try{const source=Number($('source').value),destination_key=$('destination').value,member_id=$('member').value?Number($('member').value):null;if(!source||!destination_key)throw Error('Choose a source and destination.');if(start){const d=await api('start',{source_server_id:source,destination_key,member_id});msg.textContent='Pull '+d.job_id+' started.'}else{const d=await api('plan',{source_server_id:source,destination_key,member_id});msg.textContent=d.eligible+' eligible · '+d.planned+' planned for this pull · '+d.destination}await refresh()}catch(e){msg.className='message error';msg.textContent=e.message}}
$('plan').onclick=()=>runPlan(false);$('start').onclick=()=>runPlan(true);$('refresh').onclick=refresh;
$('cloneSource').onchange=$('cloneDestination').onchange=()=>{clonePreviewReady=false;$('clonePreviewResult').textContent='Selection changed. Preview again before starting.';$('cloneStart').disabled=true};
$('cloneConfirm').onchange=()=>{$('cloneStart').disabled=!(clonePreviewReady&&$('cloneConfirm').checked)};
$('clonePreview').onclick=async()=>{const msg=$('clonePreviewResult');msg.className='message';clonePreviewReady=false;$('cloneStart').disabled=true;try{const d=await api('clone/preview',{source_server_id:Number($('cloneSource').value),destination_server_id:Number($('cloneDestination').value)});msg.textContent=`${d.source} → ${d.destination}: ${d.roles} roles, ${d.categories} categories, and ${d.channels} channels to add. Existing items stay in place.`;clonePreviewReady=true;$('cloneStart').disabled=!$('cloneConfirm').checked}catch(e){msg.className='message error';msg.textContent=e.message}};
async function pollClone(){if(!cloneJobId)return;try{const d=await api('clone/status?job_id='+encodeURIComponent(cloneJobId));$('cloneStatus').textContent=d.detail;if(d.state==='running'||d.state==='queued'){setTimeout(pollClone,1800)}else{$('cloneStart').disabled=false;$('clonePreviewResult').textContent=d.state==='completed'?`Completed for ${d.source} → ${d.destination}.`:'';cloneJobId=''}}catch(e){$('cloneStatus').className='message error';$('cloneStatus').textContent=e.message;cloneJobId='';$('cloneStart').disabled=false}}
$('cloneStart').onclick=async()=>{const msg=$('cloneStatus');msg.className='message';try{if(!clonePreviewReady||!$('cloneConfirm').checked)throw Error('Preview the clone and confirm ownership first.');const d=await api('clone/start',{source_server_id:Number($('cloneSource').value),destination_server_id:Number($('cloneDestination').value),confirmed:true});cloneJobId=d.job_id;$('cloneStart').disabled=true;msg.textContent='Clone queued…';pollClone()}catch(e){msg.className='message error';msg.textContent=e.message}};
$('addDestination').onclick=async()=>{const msg=$('targetmsg');msg.className='message';try{const d=await api('targets',{guild_id:Number($('newServer').value),key:$('newKey').value.trim(),role_id:$('newRole').value.trim()?Number($('newRole').value):0});msg.textContent=d.name+' connected. It is now selected as your destination.';$('newKey').value='';$('newRole').value='';await refresh();$('destination').value=d.key;$('pullControls').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){msg.className='message error';msg.textContent=e.message}};
$('brandColor').oninput=()=>{ $('brandPreview').style.setProperty('--preview-accent',$('brandColor').value) };
$('saveBrand').onclick=async()=>{try{await api('branding',{color:$('brandColor').value,label:$('brandLabel').value.trim()});$('brandmsg').className='message';$('brandmsg').textContent='Verification page look saved.'}catch(e){$('brandmsg').className='message error';$('brandmsg').textContent=e.message}};
$('saveTeam').onclick=async()=>{try{const d=await api('team',{action:'save',user_id:$('teamUser').value.trim(),server_id:Number($('teamServer').value),permissions:{view_members:$('permView').checked,pull_members:$('permPull').checked}});$('teammsg').className='message';$('teammsg').textContent='Access saved for '+d.user_id+'.';$('teamUser').value='';await refresh()}catch(e){$('teammsg').className='message error';$('teammsg').textContent=e.message}};
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{try{const info=await api('info');await api('control',{job_id:info.status.job_id,action:b.dataset.action});$('controlmsg').textContent='Sent '+b.dataset.action+' request.';await refresh()}catch(e){$('controlmsg').className='message error';$('controlmsg').textContent=e.message}});
$('saveSettings').onclick=async()=>{try{await api('settings',{delay_min:Number($('minDelay').value),delay_max:Number($('maxDelay').value),limit:Number($('maxMembers').value)});$('settingsmsg').className='message';$('settingsmsg').textContent='Saved.';await refresh()}catch(e){$('settingsmsg').className='message error';$('settingsmsg').textContent=e.message}};
refresh();setInterval(refresh,2500);
document.querySelectorAll('.dash-nav a').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('.dash-nav a').forEach(x=>x.classList.remove('active'));a.classList.add('active')}));
</script></body></html>"""


class PullDashboard:
    def __init__(self, bot, cfg):
        self.bot, self.cfg = bot, cfg
        self.dcfg = cfg.get("local_dashboard", {})
        self.public_mode = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT"))
        self.public_base_url = str(cfg.get("verify", {}).get("public_base_url", "")).rstrip("/")
        self.redirect_uri = str(self.dcfg.get("redirect_uri", "") or (self.public_base_url + "/dashboard/callback" if self.public_base_url else ""))
        self.login_states = {}
        self.sessions = {}
        self.host = "127.0.0.1"
        self.port = int(self.dcfg.get("port", 8790))
        self.token = secrets.token_urlsafe(32)
        self.runner = None
        self.site = None
        self.clone_jobs = {}
        self.clone_lock = asyncio.Lock()

    @property
    def url(self):
        if self.public_mode and self.public_base_url:
            return self.public_base_url + "/dashboard"
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
        if self.public_mode:
            log.info("Private bot dashboard routes will use the shared Railway web listener")
            return
        app = web.Application(client_max_size=16 * 1024)
        app.router.add_get("/", self.root)
        app.router.add_get("/dashboard/{token}", self.page)
        app.router.add_get("/api/info", self.info)
        app.router.add_post("/api/plan", self.plan)
        app.router.add_post("/api/start", self.start_pull)
        app.router.add_post("/api/control", self.control)
        app.router.add_post("/api/settings", self.settings)
        app.router.add_post("/api/targets", self.add_target)
        app.router.add_post("/api/branding", self.branding)
        app.router.add_post("/api/team", self.team)
        app.router.add_post("/api/clone/preview", self.clone_preview)
        app.router.add_post("/api/clone/start", self.clone_start)
        app.router.add_get("/api/clone/status", self.clone_status)
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

    def register_public_routes(self, app):
        app.router.add_get("/", self.public_page)
        app.router.add_get("/dashboard", self.public_page)
        app.router.add_get("/dashboard/login", self.public_login)
        app.router.add_get("/dashboard/callback", self.public_callback)
        app.router.add_get("/dashboard/logout", self.public_logout)
        app.router.add_get("/dashboard/api/info", self.info)
        app.router.add_post("/dashboard/api/plan", self.plan)
        app.router.add_post("/dashboard/api/start", self.start_pull)
        app.router.add_post("/dashboard/api/control", self.control)
        app.router.add_post("/dashboard/api/settings", self.settings)
        app.router.add_post("/dashboard/api/targets", self.add_target)
        app.router.add_post("/dashboard/api/branding", self.branding)
        app.router.add_post("/dashboard/api/team", self.team)
        app.router.add_post("/dashboard/api/clone/preview", self.clone_preview)
        app.router.add_post("/dashboard/api/clone/start", self.clone_start)
        app.router.add_get("/dashboard/api/clone/status", self.clone_status)

    def _public_session(self, request):
        token = request.cookies.get("jarvis_pull_dashboard", "")
        session = self.sessions.get(token)
        if not session or session["expires"] < time.time():
            self.sessions.pop(token, None)
            return None
        return session

    def _configured_bot_owners(self):
        discord_cfg = self.cfg.get("discord", {})
        ids = set()
        for value in list(discord_cfg.get("owner_ids", [])) + list(discord_cfg.get("co_owner_ids", [])):
            try: ids.add(int(value))
            except (TypeError, ValueError): pass
        return ids

    def _is_root_user(self, user_id):
        if user_id in self._configured_bot_owners():
            return True
        configured_guilds = {int(target.get("guild_id", 0) or 0) for target in self.bot.verify_portal.targets().values()}
        return any(guild.owner_id == user_id and guild.id in configured_guilds for guild in self.bot.guilds)

    async def _team_access(self):
        cur = await self.bot.db.conn.execute("SELECT value FROM settings WHERE key='pull_dashboard_team'")
        row = await cur.fetchone()
        try:
            data = json.loads(row["value"]) if row else []
            return [x for x in data if isinstance(x, dict) and x.get("user_id") and x.get("server_id")]
        except (TypeError, ValueError):
            log.exception("Saved Pull dashboard team permissions are invalid")
            return []

    async def _allowed_dashboard_users(self):
        ids = set(self._configured_bot_owners())
        # Let an owner of any guild the bot is already in reach the dashboard
        # so they can connect that guild as a destination for the first time.
        ids.update(int(guild.owner_id) for guild in self.bot.guilds if guild.owner_id)
        ids.update(int(x["user_id"]) for x in await self._team_access())
        return ids

    async def _has_permission(self, user_id, permission, guild_id):
        if not self.public_mode or self._is_root_user(user_id):
            return True
        guild = self.bot.get_guild(int(guild_id))
        if guild and guild.owner_id == user_id and int(guild_id) in {int(x.get("guild_id", 0) or 0) for x in self.bot.verify_portal.targets().values()}:
            return True
        return any(int(x["user_id"]) == user_id and int(x["server_id"]) == int(guild_id)
                   and bool(x.get("permissions", {}).get(permission)) for x in await self._team_access())

    def _request_user_id(self, request):
        session = self._public_session(request) if self.public_mode else None
        return int(session["user_id"]) if session else 0

    async def _read_branding(self):
        cur = await self.bot.db.conn.execute("SELECT value FROM settings WHERE key='verify_branding'")
        row = await cur.fetchone()
        try:
            value = json.loads(row["value"]) if row else {}
        except (TypeError, ValueError):
            value = {}
        color = str(value.get("color", "#6c63ff"))
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#6c63ff"
        label = str(value.get("label", "JARVIS • Community Security"))[:40]
        return {"color": color, "label": label}

    def _require_root(self, request):
        if self.public_mode and not self._is_root_user(self._request_user_id(request)):
            raise web.HTTPForbidden(text="Only a configured bot owner or co-owner can manage global dashboard settings.")

    async def public_page(self, request):
        session = self._public_session(request)
        if not session:
            body = """<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>JARVIS · Server Dashboard</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d12;color:#eff2f8;font:17px/1.6 system-ui}main{max-width:480px;padding:32px;border:1px solid #292f3b;border-radius:18px;background:#151922}a{display:inline-block;margin-top:12px;padding:12px 18px;border-radius:9px;background:#7065d9;color:white;text-decoration:none;font-weight:700}.muted{color:#aab3c2}</style><main><h1>JARVIS Server Dashboard</h1><p class='muted'>Private dashboard. Sign in with Discord. Access is limited to configured bot owners, co-owners, team users, and owners of servers JARVIS has joined.</p><a href='/dashboard/login'>Continue with Discord</a></main></html>"""
            return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})
        page = PAGE.replace("const API_BASE='/api/';", "const API_BASE='/dashboard/api/';")
        page = page.replace("__CSRF_TOKEN__", session["csrf"])
        page = page.replace('<span class="badge">Private Discord sign-in</span>', '<a class="badge" href="/dashboard/logout">Log out</a>')
        response = web.Response(text=page, content_type="text/html")
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def public_login(self, request):
        oauth = self.cfg.get("verify", {})
        if not oauth.get("client_id") or not oauth.get("client_secret") or not self.redirect_uri:
            raise web.HTTPServiceUnavailable(text="Dashboard sign-in needs Discord OAuth credentials and the dashboard callback URL.")
        state = secrets.token_urlsafe(32)
        self.login_states[state] = time.time() + 600
        params = {"client_id": str(oauth["client_id"]), "response_type": "code", "redirect_uri": self.redirect_uri, "scope": "identify", "state": state, "prompt": "consent"}
        raise web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode(params))

    async def public_callback(self, request):
        state = request.query.get("state", "")
        expires = self.login_states.pop(state, None)
        if not expires or expires < time.time():
            raise web.HTTPBadRequest(text="Dashboard sign-in expired. Return to the dashboard and try again.")
        if request.query.get("error"):
            raise web.HTTPForbidden(text="Discord sign-in was cancelled.")
        code = request.query.get("code")
        if not code:
            raise web.HTTPBadRequest(text="Discord did not return an authorization code.")
        oauth = self.cfg.get("verify", {})
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://discord.com/api/v10/oauth2/token", data={
                "client_id": str(oauth["client_id"]), "client_secret": str(oauth["client_secret"]),
                "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
                token_data = await response.json(content_type=None)
                if response.status != 200 or not token_data.get("access_token"):
                    log.warning("Dashboard Discord token exchange failed with HTTP %s", response.status)
                    raise web.HTTPUnauthorized(text="Discord sign-in failed. Check the dashboard callback in OAuth2 Redirects.")
            async with session.get("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bearer " + token_data["access_token"]}) as response:
                user = await response.json(content_type=None)
                if response.status != 200 or not user.get("id"):
                    raise web.HTTPUnauthorized(text="Could not confirm your Discord account.")
        user_id = int(user["id"])
        if user_id not in await self._allowed_dashboard_users():
            raise web.HTTPForbidden(text="This Discord account is not an allowed bot owner, server owner, or configured co-owner.")
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {"user_id": user_id, "csrf": secrets.token_urlsafe(32), "expires": time.time() + 43200}
        response = web.Response(status=302, headers={"Location": "/dashboard"})
        response.set_cookie("jarvis_pull_dashboard", token, httponly=True, secure=True, samesite="Lax", max_age=43200, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    async def public_logout(self, request):
        token = request.cookies.get("jarvis_pull_dashboard", "")
        self.sessions.pop(token, None)
        response = web.Response(status=302, headers={"Location": "/dashboard"})
        response.del_cookie("jarvis_pull_dashboard", path="/")
        return response

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

    async def _authorize(self, request):
        if self.public_mode:
            session = self._public_session(request)
            if not session:
                raise web.HTTPUnauthorized(text="Sign in with an authorized Discord owner account first.")
            if not self._is_root_user(int(session["user_id"])) and int(session["user_id"]) not in await self._allowed_dashboard_users():
                raise web.HTTPForbidden(text="This Discord account no longer has dashboard access.")
            if request.method != "GET":
                supplied = request.headers.get("X-CSRF-Token", "")
                if not hmac.compare_digest(supplied, session["csrf"]):
                    raise web.HTTPForbidden(text="Dashboard security check failed. Refresh the page and try again.")
            return
        if not self._is_local(request, require_cookie=True):
            raise web.HTTPForbidden(text="Local dashboard authorization required.")

    async def info(self, request):
        await self._authorize(request)
        user_id = self._request_user_id(request)
        is_owner = not self.public_mode or self._is_root_user(user_id)
        can_manage_servers = is_owner or any(guild.owner_id == user_id for guild in self.bot.guilds)
        team = await self._team_access() if is_owner else []
        cur = await self.bot.db.conn.execute("SELECT source_guild_id,COUNT(DISTINCT user_id) AS eligible FROM verify_recovery_grants GROUP BY source_guild_id ORDER BY source_guild_id")
        rows = await cur.fetchall()
        eligible_by_guild = {int(row["source_guild_id"]): int(row["eligible"]) for row in rows}
        target_names = {int(x["guild_id"]): x.get("name", str(x["guild_id"])) for x in self.bot.verify_portal.targets().values()}
        source_ids = set(eligible_by_guild) | {int(guild.id) for guild in self.bot.guilds}
        sources = [{"id": guild_id, "eligible": eligible_by_guild.get(guild_id, 0),
                    "name": getattr(self.bot.get_guild(guild_id), "name", None) or target_names.get(guild_id, f"Source {guild_id}")}
                   for guild_id in sorted(source_ids) if await self._has_permission(user_id, "view_members", guild_id)]
        destinations = [{"key": key, "guild_id": int(t["guild_id"]), "name": self.bot.get_guild(int(t["guild_id"])).name}
                        for key, t in self.bot.verify_portal.targets().items() if self.bot.get_guild(int(t["guild_id"])) and await self._has_permission(user_id, "pull_members", int(t["guild_id"]))]
        configured_ids = {int(t.get("guild_id", 0) or 0) for t in self.bot.verify_portal.targets().values()}
        available_guilds = [{"id": guild.id, "name": guild.name} for guild in self.bot.guilds if (is_owner or guild.owner_id == user_id) and guild.id not in configured_ids]
        guilds = [{"id": guild.id, "name": guild.name} for guild in self.bot.guilds if is_owner]
        clone_guilds = [{"id": guild.id, "name": guild.name} for guild in self.bot.guilds
                        if not self.public_mode or is_owner or guild.owner_id == user_id]
        async def setting(key, default):
            cur = await self.bot.db.conn.execute("SELECT value FROM settings WHERE key=?", (key,)); row = await cur.fetchone()
            return int(row["value"]) if row else default
        branding = await self._read_branding()
        team_view = [{"user_id": x["user_id"], "server_id": x["server_id"], "server_name": getattr(self.bot.get_guild(int(x["server_id"])), "name", str(x["server_id"])), "permissions": x.get("permissions", {})} for x in team]
        return web.json_response({"sources": sources, "destinations": destinations, "available_guilds": available_guilds, "guilds": guilds, "clone_guilds": clone_guilds, "is_owner": is_owner, "can_manage_servers": can_manage_servers, "team": team_view, "branding": branding,
            "settings": {"delay_min": await setting("member_pull_delay_min", 2), "delay_max": await setting("member_pull_delay_max", 4), "limit": await setting("member_pull_limit", 100)},
            "status": dict(self.bot.member_restore_status)})

    def _clone_pair(self, request, data):
        try:
            source_id = int(data["source_server_id"])
            destination_id = int(data["destination_server_id"])
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Choose both a source and a destination server.")
        if source_id == destination_id:
            raise web.HTTPBadRequest(text="Choose two different servers.")
        source, destination = self.bot.get_guild(source_id), self.bot.get_guild(destination_id)
        if not source or not destination:
            raise web.HTTPBadRequest(text="JARVIS must be in both servers. Invite it to the destination, then refresh.")
        actor_id = self._request_user_id(request)
        if self.public_mode and actor_id not in self._configured_bot_owners():
            if source.owner_id != actor_id or destination.owner_id != actor_id:
                raise web.HTTPForbidden(text="For safety, server cloning is limited to bot owners or the owner of both selected servers.")
        me = destination.me
        if not me or not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
            raise web.HTTPBadRequest(text="JARVIS needs Manage Roles and Manage Channels in the destination server.")
        return actor_id, source, destination

    async def clone_preview(self, request):
        data = await self._body(request)
        _, source, destination = self._clone_pair(request, data)
        snapshot = capture_server_structure(source, "dashboard-preview")
        missing_roles = sum(1 for role in snapshot["roles"] if not discord.utils.get(destination.roles, name=role["name"]))
        missing_categories = sum(1 for item in snapshot["channels"] if item["type"] == "category"
                                 and not discord.utils.get(destination.categories, name=item["name"]))
        missing_channels = sum(1 for item in snapshot["channels"] if item["type"] != "category"
                               and not any(channel.name == item["name"] and
                                   ((item["type"] == "text" and isinstance(channel, discord.TextChannel)) or
                                    (item["type"] == "voice" and isinstance(channel, discord.VoiceChannel)))
                                   for channel in destination.channels))
        return web.json_response({"source": source.name, "destination": destination.name,
            "roles": missing_roles, "categories": missing_categories, "channels": missing_channels})

    async def clone_start(self, request):
        data = await self._body(request)
        actor_id, source, destination = self._clone_pair(request, data)
        if data.get("confirmed") is not True:
            raise web.HTTPBadRequest(text="Confirm that you own both servers and want to add the missing structure.")
        if self.clone_lock.locked() or any(job.get("state") in {"queued", "running"} for job in self.clone_jobs.values()):
            raise web.HTTPConflict(text="A server structure clone is already running. Wait for it to finish first.")
        job_id = secrets.token_urlsafe(9)
        job = {"job_id": job_id, "actor_id": actor_id, "source_id": source.id, "destination_id": destination.id,
               "source": source.name, "destination": destination.name, "state": "queued", "detail": "Waiting to start."}
        self.clone_jobs[job_id] = job
        asyncio.create_task(self._run_clone(job_id))
        return web.json_response({"job_id": job_id, "state": "queued"}, status=202)

    async def _run_clone(self, job_id):
        job = self.clone_jobs[job_id]
        async with self.clone_lock:
            job["state"] = "running"
            job["detail"] = "Copying roles, categories, and channels. This can take a little while."
            try:
                source = self.bot.get_guild(job["source_id"])
                destination = self.bot.get_guild(job["destination_id"])
                if not source or not destination:
                    raise RuntimeError("The bot left one of the selected servers before the clone started.")
                if not destination.me or not destination.me.guild_permissions.manage_roles or not destination.me.guild_permissions.manage_channels:
                    raise RuntimeError("JARVIS needs Manage Roles and Manage Channels in the destination server.")
                snapshot = capture_server_structure(source, "dashboard-clone")
                roles, channels, skipped = await restore_server_structure(destination, snapshot)
                job.update(state="completed", roles=roles, channels=channels, skipped=skipped,
                           detail=f"Finished. {roles} roles and {channels} categories/channels added; {skipped} skipped.")
                await self.bot.db.audit(job["actor_id"], "dashboard_server_clone",
                    f"source={source.id}; destination={destination.id}; roles={roles}; channels={channels}; skipped={skipped}")
            except Exception as exc:
                log.exception("Dashboard structure clone %s failed", job_id)
                job.update(state="error", detail=f"Clone stopped: {str(exc)[:240]}")

    async def clone_status(self, request):
        await self._authorize(request)
        job_id = str(request.query.get("job_id", ""))
        job = self.clone_jobs.get(job_id)
        if not job:
            raise web.HTTPNotFound(text="That clone job was not found. Refresh and start a new preview.")
        actor_id = self._request_user_id(request)
        if self.public_mode and actor_id != job["actor_id"] and actor_id not in self._configured_bot_owners():
            raise web.HTTPForbidden(text="That clone job belongs to another dashboard user.")
        return web.json_response({key: job.get(key) for key in ("job_id", "source", "destination", "state", "detail", "roles", "channels", "skipped")})

    async def add_target(self, request):
        data = await self._body(request)
        try:
            guild_id = int(data["guild_id"])
            role_id = int(data.get("role_id") or 0)
            key = str(data["key"]).strip().lower()
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Choose a server and enter a short destination name.")
        if not key or len(key) > 32 or not key.replace("-", "").replace("_", "").isalnum():
            raise web.HTTPBadRequest(text="Use a destination name with letters, numbers, hyphens, or underscores (max 32 characters).")
        guild = self.bot.get_guild(guild_id)
        if not guild:
            raise web.HTTPBadRequest(text="JARVIS is not in that server yet. Invite the bot there, then refresh this page.")
        session = self._public_session(request) if self.public_mode else None
        actor_id = int(session["user_id"]) if session else 0
        if session:
            bot_owners = set()
            for value in list(self.cfg.get("discord", {}).get("owner_ids", [])) + list(self.cfg.get("discord", {}).get("co_owner_ids", [])):
                try: bot_owners.add(int(value))
                except (TypeError, ValueError): pass
            if actor_id not in bot_owners and actor_id != int(guild.owner_id or 0):
                raise web.HTTPForbidden(text="Only this server's owner or a configured bot owner/co-owner can add it as a destination.")
        if key in self.bot.verify_portal.targets():
            raise web.HTTPConflict(text="That destination name is already in use.")
        role = guild.get_role(role_id) if role_id else None
        if role_id and (not role or role.is_default()):
            raise web.HTTPBadRequest(text="That role ID does not belong to the selected server.")
        if role:
            bot_member = guild.me
            if not bot_member or not bot_member.guild_permissions.manage_roles or role >= bot_member.top_role:
                raise web.HTTPBadRequest(text="JARVIS needs Manage Roles, and its highest role must be above the role you selected.")
        target = {"key": key, "name": guild.name, "guild_id": guild.id, "role_id": role_id}
        portal = self.bot.verify_portal
        portal.extra_targets.append(target)
        portal.vcfg.setdefault("targets", []).append(target)
        await self.bot.db.conn.execute(
            "INSERT INTO settings(key,value) VALUES('verify_dashboard_targets',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(portal.extra_targets, separators=(",", ":")),),
        )
        await self.bot.db.conn.commit()
        await self.bot.db.audit(actor_id, "pull_destination_added", f"key={key}; guild={guild.id}; role={role_id}")
        return web.json_response({"key": key, "name": guild.name, "guild_id": guild.id, "role_id": role_id}, status=201)

    async def _body(self, request):
        await self._authorize(request)
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
        actor_id = self._request_user_id(request)
        if not await self._has_permission(actor_id, "view_members", source_id) or not await self._has_permission(actor_id, "pull_members", int(target["guild_id"])):
            raise web.HTTPForbidden(text="Your team access does not allow viewing that source and pulling to that destination.")
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
            session = self._public_session(request) if self.public_mode else None
            actor_id = int(session["user_id"]) if session else 0
            target = self.bot.verify_portal.targets().get(destination_key)
            if target and (not await self._has_permission(actor_id, "view_members", source_id) or not await self._has_permission(actor_id, "pull_members", int(target.get("guild_id", 0) or 0))):
                raise web.HTTPForbidden(text="Your team access does not allow pulling from that source to this destination.")
            job = await self.bot.start_member_pull(source_id, destination_key, member_id=member_id, actor_id=actor_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc) or "Invalid pull request.")
        except RuntimeError as exc:
            raise web.HTTPConflict(text=str(exc))
        return web.json_response(job, status=202)

    async def control(self, request):
        data = await self._body(request)
        control = self.bot.member_restore_control; status = self.bot.member_restore_status
        actor_id = self._request_user_id(request)
        if self.public_mode and not self._is_root_user(actor_id):
            source_id = int(status.get("source_guild_id", 0) or 0)
            destination_id = int(status.get("destination_guild_id", 0) or 0)
            if not await self._has_permission(actor_id, "view_members", source_id) or not await self._has_permission(actor_id, "pull_members", destination_id):
                raise web.HTTPForbidden(text="Your team access does not allow controlling this pull.")
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
        self._require_root(request)
        try:
            low, high, limit = int(data["delay_min"]), int(data["delay_max"]), int(data["limit"])
            if low < 1 or high < low or high > 60 or not 1 <= limit <= 1000: raise ValueError
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Delay must be 1–60 seconds, maximum delay must be at least minimum, and limit must be 1–1000.")
        for key, value in (("member_pull_delay_min", low), ("member_pull_delay_max", high), ("member_pull_limit", limit)):
            await self.bot.db.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        await self.bot.db.conn.commit()
        return web.json_response({"saved": True})

    async def branding(self, request):
        data = await self._body(request)
        self._require_root(request)
        color = str(data.get("color", "")).strip()
        label = str(data.get("label", "")).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or not label or len(label) > 40:
            raise web.HTTPBadRequest(text="Choose a valid color and a brand label of 1–40 characters.")
        value = {"color": color.lower(), "label": label}
        await self.bot.db.conn.execute("INSERT INTO settings(key,value) VALUES('verify_branding',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))
        await self.bot.db.conn.commit()
        await self.bot.db.audit(self._request_user_id(request), "verify_branding_updated", f"color={color.lower()}; label={label}")
        return web.json_response(value)

    async def team(self, request):
        data = await self._body(request)
        self._require_root(request)
        action = str(data.get("action", "save"))
        try:
            user_id = int(data["user_id"])
            guild_id = int(data["server_id"])
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Enter a Discord user ID and choose a server.")
        if user_id < 1000000000000 or not self.bot.get_guild(guild_id):
            raise web.HTTPBadRequest(text="Check the Discord user ID and choose a server the bot is in.")
        rows = await self._team_access()
        rows = [x for x in rows if not (int(x["user_id"]) == user_id and int(x["server_id"]) == guild_id)]
        if action == "save":
            raw_permissions = data.get("permissions", {})
            if not isinstance(raw_permissions, dict):
                raise web.HTTPBadRequest(text="Choose permissions using the checkboxes.")
            permissions = {name: bool(raw_permissions.get(name)) for name in ("view_members", "pull_members")}
            if not any(permissions.values()):
                raise web.HTTPBadRequest(text="Select at least one permission.")
            rows.append({"user_id": user_id, "server_id": guild_id, "permissions": permissions})
        elif action != "remove":
            raise web.HTTPBadRequest(text="Action must be save or remove.")
        await self.bot.db.conn.execute("INSERT INTO settings(key,value) VALUES('pull_dashboard_team',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(rows, separators=(",", ":")),))
        await self.bot.db.conn.commit()
        await self.bot.db.audit(self._request_user_id(request), "pull_dashboard_team_updated", f"user={user_id}; server={guild_id}; action={action}")
        return web.json_response({"saved": True, "user_id": user_id, "server_id": guild_id})
