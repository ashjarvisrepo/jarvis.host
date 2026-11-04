import os, logging, asyncio, re, discord, inspect, shlex, typing, secrets
from discord import app_commands
from discord.ext import commands
from core.db import Database, now as db_now
from core.permissions import is_owner,is_admin,is_staff
from core.ai import LocalAI
from core.verify import VerifyPortal
from core.help_ui import command_list_embeds, ACCESS
from core.tickets import SupportPanelView, AutoBuyPanelView
from core.sellauth import SellAuthNotifications
from core.embeds import build_embed
from core.server_snapshots import capture as capture_server_snapshot, save as save_server_snapshot, list_snapshots, load as load_server_snapshot, restore as restore_server_snapshot
from core.local_dashboard import PullDashboard

log=logging.getLogger("jarvis")

def money(amount,cfg):
    return f'{cfg["shop"].get("currency_symbol","₹")}{amount/100:,.2f}'

def verification_panel_embed():
    embed = discord.Embed(
        title="🛡️ Verify to Unlock the Community",
        description=(
            "We verify members to help keep bots and raid accounts out and protect the private community. "
            "Complete Discord's official authorization to receive access."
        ),
        colour=0x7565D9,
    )
    embed.add_field(
        name="Why verify?",
        value="Only verified members can see the community channels. This helps keep the server safe for everyone.",
        inline=False,
    )
    embed.add_field(
        name="Privacy",
        value="We do not log or save your IP address. JARVIS never asks for your Discord password, MFA code, or session token.",
        inline=False,
    )
    embed.add_field(
        name="How it works",
        value="Click **Verify**, check the server name on Discord, and approve if you want to join.",
        inline=False,
    )
    embed.set_footer(text="JARVIS • Community Security")
    return embed

def create_bot(cfg):
    intents=discord.Intents.default()
    intents.members=True
    intents.message_content=True  # Enable Message Content Intent in the Discord Developer Portal.
    prefix_cfg = cfg["discord"].get("command_prefixes", {})
    prefix = str(cfg["discord"].get("command_prefix", prefix_cfg.get("owner", "$")))
    if not prefix or prefix.isspace():
        raise ValueError("discord.command_prefix must be a non-empty prefix.")
    prefixes = {"owner": prefix, "staff": prefix, "member": prefix}
    bot=commands.Bot(command_prefix=prefix,intents=intents,help_command=None)
    bot.prefix_map = prefixes
    bot.prefix_values = prefixes
    db=Database(cfg["database"]["path"])
    ai=LocalAI(cfg)
    bot.db=db; bot.cfg=cfg; bot.ai=ai
    bot.dm_campaign_tasks = {}
    bot.member_restore_task = None
    bot.member_restore_status = {"state": "idle"}
    bot.member_restore_control = None
    bot.verify_portal=VerifyPortal(bot,cfg,db)
    bot.local_dashboard=PullDashboard(bot,cfg)
    bot.sellauth_notifications = SellAuthNotifications(bot,cfg,db)
    bot.invite_cache={}

    def owner_check(i): return is_owner(i.user,cfg)
    def admin_check(i): return is_admin(i.user,cfg)
    def staff_check(i): return is_staff(i.user,cfg)

    async def assign_explicitly_verified_role(member):
        """Grant roles only to users queued after successful OAuth consent."""
        if getattr(member, "pending", False) or not getattr(bot, "_db_ready", False):
            return
        cur = await db.conn.execute(
            "SELECT target_key,role_id FROM verify_pending_roles WHERE user_id=? AND guild_id=?",
            (member.id, member.guild.id),
        )
        rows = await cur.fetchall()
        targets = {str(t.get("key")): t for t in cfg.get("verify", {}).get("targets", [])}
        for row in rows:
            target = targets.get(row["target_key"])
            if target and int(target.get("guild_id", 0) or 0) != member.guild.id:
                continue
            role = member.guild.get_role(int(row["role_id"] or (target.get("role_id", 0) if target else 0) or 0))
            if not role or role in member.roles:
                await db.conn.execute(
                    "DELETE FROM verify_pending_roles WHERE user_id=? AND guild_id=? AND target_key=?",
                    (member.id, member.guild.id, row["target_key"]),
                )
                continue
            try:
                await member.add_roles(role, reason="JARVIS VERIFY OAuth2 consent completed")
                await db.conn.execute(
                    "DELETE FROM verify_pending_roles WHERE user_id=? AND guild_id=? AND target_key=?",
                    (member.id, member.guild.id, row["target_key"]),
                )
                await db.audit(member.id, "verification_role_granted", f"guild={member.guild.id}; role={role.id}")
            except (discord.Forbidden, discord.HTTPException):
                log.info("Could not grant queued verification role to %s in %s", member.id, member.guild.id)
        await db.conn.commit()

    bot.assign_explicitly_verified_role = assign_explicitly_verified_role

    async def resume_explicit_verifications():
        cur = await db.conn.execute("SELECT DISTINCT user_id,guild_id FROM verify_pending_roles")
        for row in await cur.fetchall():
            guild = bot.get_guild(row["guild_id"])
            if not guild:
                continue
            try:
                member = guild.get_member(row["user_id"]) or await guild.fetch_member(row["user_id"])
                await assign_explicitly_verified_role(member)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

    @bot.check
    async def enforce_command_access(ctx):
        if ctx.command.name == "help": return True
        access = ACCESS.get(ctx.command.name, "Public")
        if access == "Public": return True
        if access == "Staff": return is_staff(ctx.author, cfg)
        if access == "Admin": return is_admin(ctx.author, cfg)
        return is_owner(ctx.author, cfg)

    async def create_ticket_channel(guild, user, kind, subject=None):
        cur = await db.conn.execute("SELECT id,channel_id FROM tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (user.id,))
        existing = await cur.fetchone()
        if existing:
            channel = guild.get_channel(existing["channel_id"] or 0)
            if channel:
                return channel, False
            await db.conn.execute("UPDATE tickets SET status='closed',closed_at=? WHERE id=?", (db_now(), existing["id"]))
            await db.conn.commit()
        ticket_subject = (subject or {"help": "Order, delivery, or account support", "purchase": "Product and purchase help", "questions": "Pre-purchase question"}.get(kind, "Support request"))[:150]
        slug = {"help": "help", "purchase": "purchase", "questions": "questions"}.get(kind, "support")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        me = guild.me or guild.get_member(bot.user.id)
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
        staff_ids = set(cfg["discord"].get("staff_role_ids", [])) | set(cfg["discord"].get("admin_role_ids", []))
        for role in guild.roles:
            if role.id in staff_ids:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        category = guild.get_channel(int(cfg["shop"].get("support_category_id", 0) or 0))
        if not isinstance(category, discord.CategoryChannel): category = None
        channel = await guild.create_text_channel(f"ticket-{slug}-{str(user.id)[-5:]}", category=category, overwrites=overwrites, reason="JARVIS private support ticket")
        cur = await db.conn.execute("INSERT INTO tickets(user_id,channel_id,subject,created_at) VALUES(?,?,?,?)", (user.id, channel.id, ticket_subject, db_now()))
        await db.conn.commit()
        ticket_id = cur.lastrowid
        await channel.edit(name=f"ticket-{ticket_id:04d}-{slug}")
        await channel.send(f"{user.mention} opened ticket **#{ticket_id}** · **{discord.utils.escape_markdown(ticket_subject)}**\nStaff can claim with `$ticketclaim` and close with `$ticketclose`.", allowed_mentions=discord.AllowedMentions(users=[user], roles=False, everyone=False))
        await db.audit(user.id, "ticket_opened", f"ticket={ticket_id}; kind={slug}")
        return channel, True

    async def open_ticket_button(interaction, kind):
        if not interaction.guild:
            return await interaction.response.send_message("Open support tickets from the shop server.", ephemeral=True)
        try:
            channel, created = await create_ticket_channel(interaction.guild, interaction.user, kind)
        except discord.Forbidden:
            return await interaction.response.send_message("The bot needs Manage Channels and permission to view the support category.", ephemeral=True)
        except discord.HTTPException:
            log.exception("Could not create support ticket")
            return await interaction.response.send_message("Discord could not create the ticket. Please try again later.", ephemeral=True)
        if created:
            await interaction.response.send_message(f"Your private ticket is open: {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)

    @bot.event
    async def on_ready():
        if not getattr(bot,"_db_ready",False):
            await db.connect(); bot._db_ready=True
            await db.conn.execute("UPDATE dm_campaigns SET status='interrupted',finished_at=? WHERE status='running'", (db_now(),))
            await db.conn.commit()
            await db.conn.execute("""CREATE TABLE IF NOT EXISTS verify_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
              target_key TEXT NOT NULL, result TEXT NOT NULL, ip_hash TEXT, created_at TEXT NOT NULL)""")
            await db.conn.execute("""CREATE TABLE IF NOT EXISTS invite_campaigns(
              code TEXT PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
              campaign TEXT NOT NULL, created_by INTEGER NOT NULL, created_at TEXT NOT NULL)""")
            await db.conn.execute("""CREATE TABLE IF NOT EXISTS invite_attributions(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
              invite_code TEXT, campaign TEXT, created_at TEXT NOT NULL)""")
            await db.conn.commit()
        await resume_explicit_verifications()
        if not getattr(bot, "_local_dashboard_started", False):
            try:
                await bot.local_dashboard.start()
                bot._local_dashboard_started = True
            except Exception:
                log.exception("Could not start the local Pull dashboard; check whether its port is in use")
        if not getattr(bot, "_support_view_registered", False):
            bot.add_view(SupportPanelView(open_ticket_button))
            bot.add_view(AutoBuyPanelView(open_ticket_button, cfg.get("sellauth", {}).get("store_url", "")))
            bot._support_view_registered = True
        if not getattr(bot, "_sellauth_start_attempted", False):
            await bot.sellauth_notifications.start()
            bot._sellauth_start_attempted = True
        if not getattr(bot, "_slash_commands_removed", False):
            try:
                # Remove previously published global commands, then clear any
                # guild-scoped commands from every server this bot is in.
                bot.tree.clear_commands(guild=None)
                await bot.tree.sync()
                for joined_guild in bot.guilds:
                    guild_scope = discord.Object(id=joined_guild.id)
                    bot.tree.clear_commands(guild=guild_scope)
                    await bot.tree.sync(guild=guild_scope)
                bot._slash_commands_removed = True
                log.info("Slash commands removed; use the configured $ prefix.")
            except Exception:
                log.exception("Could not remove previously published slash commands")
        if not getattr(bot,"_verify_started",False):
            await bot.verify_portal.start(); bot._verify_started=True
        # Cache invite usage for attribution when permissions allow it.
        for target in cfg.get("verify",{}).get("targets",[]):
            guild=bot.get_guild(int(target.get("guild_id",0) or 0))
            if guild:
                try: bot.invite_cache[guild.id]={x.code:x.uses for x in await guild.invites()}
                except (discord.Forbidden,discord.HTTPException): log.info("Invite attribution unavailable for guild %s (Manage Server permission needed)",guild.id)
        log.info("Logged in as %s",bot.user)

    @bot.listen("on_member_join")
    async def verification_member_join(member):
        try:
            old=bot.invite_cache.get(member.guild.id,{})
            current=await member.guild.invites()
            used=next((x for x in current if x.uses and x.uses>old.get(x.code,0)),None)
            bot.invite_cache[member.guild.id]={x.code:x.uses for x in current}
            if used:
                cur=await db.conn.execute("SELECT campaign FROM invite_campaigns WHERE code=?",(used.code,)); row=await cur.fetchone()
                await db.conn.execute("INSERT INTO invite_attributions(user_id,guild_id,invite_code,campaign,created_at) VALUES(?,?,?,?,datetime('now'))",
                    (member.id,member.guild.id,used.code,row["campaign"] if row else "Untracked invite"))
                await db.conn.commit()
        except (discord.Forbidden,discord.HTTPException): pass

    @bot.listen("on_member_update")
    async def verification_screening_complete(before, after):
        if getattr(before, "pending", False) and not getattr(after, "pending", False):
            await assign_explicitly_verified_role(after)

    @bot.tree.command(name="shop",description="Browse the shop catalog")
    async def shop(i:discord.Interaction):
        rows=await db.products()
        if not rows: return await i.response.send_message("The shop is being prepared. Please check back soon.",ephemeral=True)
        embed=discord.Embed(title=cfg["shop"]["name"],description="Browse available products below.",color=0x7565D9)
        for p in rows[:25]:
            stock="Unlimited" if p["stock"]<0 else str(p["stock"])
            embed.add_field(name=f'#{p["id"]} · {p["name"]} · {money(p["price"],cfg)}',
                            value=f'{p["description"][:180]}\nCategory: {p["category"]} · Stock: {stock}',inline=False)
        await i.response.send_message(embed=embed)

    @bot.tree.command(name="catalog_search", description="Search products and sort by price or name")
    @app_commands.describe(query="Optional words in a product name or description", category="Optional exact category", sort="Result ordering")
    @app_commands.choices(sort=[app_commands.Choice(name="Newest", value="newest"), app_commands.Choice(name="Price: low to high", value="price_low"), app_commands.Choice(name="Price: high to low", value="price_high"), app_commands.Choice(name="Name", value="name")])
    async def catalog_search(i: discord.Interaction, query: str = "", category: str = "", sort: str = "newest"):
        rows = await db.search_products(query, category, sort)
        if not rows:
            return await i.response.send_message("No products matched those filters.", ephemeral=True)
        embed = discord.Embed(title="Product results", colour=0x7565D9)
        for p in rows:
            stock = "Unlimited" if p["stock"] < 0 else str(p["stock"])
            embed.add_field(name=f'#{p["id"]} · {p["name"]} · {money(p["price"],cfg)}', value=f'{p["description"][:180]}\n{p["category"]} · Stock: {stock}', inline=False)
        await i.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="product_add",description="Add a product (admin)")
    @app_commands.describe(name="Product name",description="Description",price="Price in minor currency units (paise for INR)",stock="Use -1 for unlimited stock",delivery="Optional delivery text/template")
    async def product_add(i:discord.Interaction,name:str,description:str,price:int,stock:int=-1,category:str="General",delivery:str=""):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        if price<0 or stock < -1: return await i.response.send_message("Invalid price or stock.",ephemeral=True)
        pid=await db.add_product(name[:100],description[:1000],category[:80],price,stock,delivery[:1000])
        await db.audit(i.user.id,"product_add",f"id={pid}; name={name}")
        await i.response.send_message(f"Created product **#{pid} {discord.utils.escape_markdown(name)}**.",ephemeral=True)

    @bot.tree.command(name="product_remove",description="Deactivate a product (admin)")
    async def product_remove(i:discord.Interaction,product_id:int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        await db.conn.execute("UPDATE products SET active=0 WHERE id=?",(product_id,)); await db.conn.commit()
        await db.audit(i.user.id,"product_remove",str(product_id))
        await i.response.send_message("Product deactivated (historical orders retained).",ephemeral=True)

    @bot.tree.command(name="product_edit", description="Edit an active product (admin)")
    @app_commands.describe(product_id="Product number", name="New product name", description="New description", category="New category", price="Price in minor units", stock="Stock; use -1 for unlimited")
    async def product_edit(i: discord.Interaction, product_id: int, name: str = None, description: str = None, category: str = None, price: int = None, stock: int = None):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        if name is not None: name = name[:100]
        if description is not None: description = description[:1000]
        if category is not None: category = category[:80]
        try: await db.update_product(product_id, name=name, description=description, category=category, price=price, stock=stock)
        except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
        await db.audit(i.user.id, "product_edit", f"product={product_id}; fields=" + ",".join(k for k, v in {"name":name,"description":description,"category":category,"price":price,"stock":stock}.items() if v is not None))
        await i.response.send_message(f"Product `#{product_id}` updated.", ephemeral=True)

    @bot.tree.command(name="product_duplicate", description="Duplicate an active product (admin)")
    async def product_duplicate(i: discord.Interaction, product_id: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        try: duplicate_id = await db.duplicate_product(product_id)
        except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
        await db.audit(i.user.id, "product_duplicate", f"source={product_id}; copy={duplicate_id}")
        await i.response.send_message(f"Created product copy `#{duplicate_id}`. Review its price, stock, and delivery details before selling.", ephemeral=True)

    @bot.tree.command(name="product_info", description="View a product's public details")
    async def product_info(i: discord.Interaction, product_id: int):
        cur = await db.conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,))
        p = await cur.fetchone()
        if not p: return await i.response.send_message("Product not found.", ephemeral=True)
        stock = "Unlimited" if p["stock"] < 0 else str(p["stock"])
        embed = discord.Embed(title=p["name"], description=p["description"][:4000], colour=0x7565D9)
        embed.add_field(name="Price", value=money(p["price"], cfg))
        embed.add_field(name="Category", value=p["category"])
        embed.add_field(name="Stock", value=stock)
        await i.response.send_message(embed=embed)

    @bot.tree.command(name="stock_adjust", description="Increase or decrease a product's tracked stock (admin)")
    async def stock_adjust(i: discord.Interaction, product_id: int, change: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        if change == 0: return await i.response.send_message("Change must be non-zero.", ephemeral=True)
        try: stock = await db.adjust_stock(product_id, change)
        except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
        await db.audit(i.user.id, "stock_adjust", f"product={product_id}; change={change}; stock={stock}")
        await i.response.send_message(f"Stock for product `#{product_id}` is now **{stock}**.", ephemeral=True)

    @bot.tree.command(name="cart_add",description="Add a product to your cart")
    async def cart_add(i:discord.Interaction,product_id:int,quantity:app_commands.Range[int,1,20]=1):
        try: await db.cart_add(i.user.id,product_id,quantity,cfg["security"].get("max_cart_quantity",20))
        except ValueError as e: return await i.response.send_message(str(e),ephemeral=True)
        await i.response.send_message("Added to your cart.",ephemeral=True)

    @bot.tree.command(name="cart",description="View your shopping cart")
    async def cart(i:discord.Interaction):
        rows=await db.cart(i.user.id)
        if not rows: return await i.response.send_message("Your cart is empty.",ephemeral=True)
        total=sum(r["quantity"]*r["price"] for r in rows)
        body="\n".join(f'**{r["name"]}** × {r["quantity"]} — {money(r["price"]*r["quantity"],cfg)}' for r in rows)
        await i.response.send_message(f"{body}\n\n**Total: {money(total,cfg)}**",ephemeral=True)

    @bot.tree.command(name="cart_remove", description="Remove a product from your cart")
    async def cart_remove(i: discord.Interaction, product_id: int):
        if not await db.cart_remove(i.user.id, product_id):
            return await i.response.send_message("That product isn't in your cart.", ephemeral=True)
        await i.response.send_message("Product removed from your cart.", ephemeral=True)

    @bot.tree.command(name="cart_clear", description="Empty your cart")
    async def cart_clear(i: discord.Interaction):
        await db.cart_clear(i.user.id)
        await i.response.send_message("Your cart is empty now.", ephemeral=True)

    @bot.tree.command(name="wishlist", description="View or add/remove products in your wishlist")
    @app_commands.describe(action="Choose view, add, or remove", product_id="Required for add/remove")
    @app_commands.choices(action=[app_commands.Choice(name="View wishlist", value="view"), app_commands.Choice(name="Add product", value="add"), app_commands.Choice(name="Remove product", value="remove")])
    async def wishlist(i: discord.Interaction, action: app_commands.Choice[str], product_id: int = None):
        if action.value == "add":
            if product_id is None: return await i.response.send_message("Provide a product ID to add.", ephemeral=True)
            try: await db.wishlist_add(i.user.id, product_id)
            except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
            return await i.response.send_message("Added to your wishlist.", ephemeral=True)
        if action.value == "remove":
            if product_id is None: return await i.response.send_message("Provide a product ID to remove.", ephemeral=True)
            return await i.response.send_message("Removed from your wishlist." if await db.wishlist_remove(i.user.id, product_id) else "That product wasn't in your wishlist.", ephemeral=True)
        rows = await db.wishlist(i.user.id)
        if not rows: return await i.response.send_message("Your wishlist is empty.", ephemeral=True)
        body = "\n".join(f'`#{p["id"]}` **{p["name"]}** · {money(p["price"], cfg)}' for p in rows[:25])
        await i.response.send_message("**Your wishlist**\n" + body, ephemeral=True)

    @bot.tree.command(name="checkout",description="Create an order from your cart")
    async def checkout(i:discord.Interaction, coupon_code: str = ""):
        try: public,total=await db.checkout(i.user.id,cfg["shop"].get("order_prefix","JX"),coupon_code or None)
        except ValueError as e: return await i.response.send_message(str(e),ephemeral=True)
        await db.audit(i.user.id,"checkout",public)
        await i.response.send_message(f"Order **{public}** created. Total: **{money(total,cfg)}**" + (f" (coupon `{coupon_code.upper()}` applied)." if coupon_code else ".") + f"\n{cfg['shop'].get('payment_instructions','Contact staff for payment instructions')}\nSubmit your transaction reference with `$payment {public} REFERENCE`.",ephemeral=True)

    @bot.tree.command(name="payment_submit",description="Submit your payment transaction reference")
    async def payment_submit(i:discord.Interaction,order_id:str,transaction_reference:str):
        order=await db.order(order_id,i.user.id)
        if not order: return await i.response.send_message("Order not found.",ephemeral=True)
        if order["payment_status"]=="paid": return await i.response.send_message("This order is already marked paid.",ephemeral=True)
        await db.conn.execute("UPDATE orders SET payment_ref=?,payment_status='submitted',updated_at=datetime('now') WHERE public_id=?",(transaction_reference[:160],order_id))
        await db.conn.commit(); await db.audit(i.user.id,"payment_submitted",order_id)
        await i.response.send_message("Payment reference submitted for staff verification. This does not mean payment is confirmed.",ephemeral=True)

    @bot.tree.command(name="order",description="Check an order you own")
    async def order(i:discord.Interaction,order_id:str):
        o=await db.order(order_id,i.user.id)
        if not o: return await i.response.send_message("Order not found.",ephemeral=True)
        items=await db.order_items(o["id"])
        await i.response.send_message(f"**{o['public_id']}** · {o['status']} · Payment: {o['payment_status']} · Total: {money(o['total'],cfg)}\n"+"\n".join(f'• {x["product_name"]} × {x["quantity"]}' for x in items),ephemeral=True)

    @bot.tree.command(name="order_cancel", description="Cancel your unpaid order and return its finite stock")
    async def order_cancel(i: discord.Interaction, order_id: str):
        try: await db.cancel_unpaid_order(order_id, i.user.id)
        except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
        await db.audit(i.user.id, "order_cancelled", order_id)
        await i.response.send_message(f"Unpaid order `{order_id}` cancelled. Reserved finite stock was returned.", ephemeral=True)

    @bot.tree.command(name="orders_pending",description="View orders awaiting payment review (staff)")
    async def orders_pending(i:discord.Interaction):
        if not staff_check(i): return await i.response.send_message("Staff permission required.",ephemeral=True)
        cur=await db.conn.execute("SELECT * FROM orders WHERE payment_status='submitted' ORDER BY id LIMIT 20"); rows=await cur.fetchall()
        if not rows: return await i.response.send_message("No payment submissions waiting.",ephemeral=True)
        await i.response.send_message("\n".join(f'`{o["public_id"]}` · user `{o["user_id"]}` · {money(o["total"],cfg)} · ref `{o["payment_ref"]}`' for o in rows),ephemeral=True)

    @bot.tree.command(name="payment_verify",description="Mark submitted payment as verified (staff)")
    async def payment_verify(i:discord.Interaction,order_id:str):
        if not staff_check(i): return await i.response.send_message("Staff permission required.",ephemeral=True)
        o=await db.order(order_id)
        if not o: return await i.response.send_message("Order not found.",ephemeral=True)
        if o["payment_status"]!="submitted": return await i.response.send_message("Order has no submitted payment reference.",ephemeral=True)
        await db.conn.execute("UPDATE orders SET payment_status='paid',status='paid',updated_at=datetime('now') WHERE public_id=?",(order_id,))
        await db.conn.commit(); await db.audit(i.user.id,"payment_verified",order_id)
        await i.response.send_message(f"Payment verified for **{order_id}**. Delivery must now be fulfilled.",ephemeral=True)

    @bot.tree.command(name="deliver",description="Mark an order delivered (staff)")
    async def deliver(i:discord.Interaction,order_id:str,delivery_note:str=""):
        if not staff_check(i): return await i.response.send_message("Staff permission required.",ephemeral=True)
        o=await db.order(order_id)
        if not o: return await i.response.send_message("Order not found.",ephemeral=True)
        if o["payment_status"]!="paid": return await i.response.send_message("Payment must be verified before delivery.",ephemeral=True)
        await db.conn.execute("UPDATE orders SET status='delivered',updated_at=datetime('now') WHERE public_id=?",(order_id,))
        await db.conn.execute("UPDATE order_items SET delivery_status='delivered' WHERE order_id=?",(o["id"],))
        await db.conn.commit(); await db.audit(i.user.id,"delivered",order_id)
        try:
            user=await bot.fetch_user(o["user_id"])
            await user.send(f"Your order **{order_id}** has been marked delivered.\n{delivery_note[:1000]}")
        except Exception: pass
        await i.response.send_message("Order marked delivered. Customer DM attempted.",ephemeral=True)

    @bot.tree.command(name="refund_record",description="Record a refund (admin; does not move money)")
    async def refund_record(i:discord.Interaction,order_id:str,reason:str):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        o=await db.order(order_id)
        if not o: return await i.response.send_message("Order not found.",ephemeral=True)
        await db.conn.execute("UPDATE orders SET status='refund_requested',updated_at=datetime('now') WHERE public_id=?",(order_id,))
        await db.conn.commit(); await db.audit(i.user.id,"refund_recorded",f"{order_id}: {reason}")
        await i.response.send_message("Refund request recorded. This command does not issue a real payment refund.",ephemeral=True)

    @bot.tree.command(name="ticket",description="Open a private support ticket")
    async def ticket(i:discord.Interaction,subject:str):
        guild=i.guild
        if guild is None: return await i.response.send_message("Use this command in your shop server.",ephemeral=True)
        try: channel, created = await create_ticket_channel(guild, i.user, "questions", subject)
        except discord.Forbidden: return await i.response.send_message("The bot needs Manage Channels and permission to view the support category.", ephemeral=True)
        if created: return await i.response.send_message(f"Your ticket is open: {channel.mention}", ephemeral=True)
        await i.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)

    @bot.tree.command(name="ticket_panel", description="Post the support ticket button panel (admin)")
    @app_commands.describe(channel="Channel for the support panel; defaults to this channel")
    async def ticket_panel(i: discord.Interaction, channel: discord.TextChannel = None):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        channel = channel or i.channel
        if not isinstance(channel, discord.TextChannel): return await i.response.send_message("Choose a text channel.", ephemeral=True)
        embed = build_embed(f"© {cfg['shop'].get('name', 'JARVIS SHOP')} | MEMBER TICKETS", "Open a private ticket for purchase questions or support. Please choose the button that best matches your request.")
        embed.add_field(name="🛒 PURCHASE", value="Open a ticket for product availability or purchase help.", inline=False)
        embed.add_field(name="🆘 SUPPORT", value="Open a ticket for an existing order, delivery, or account issue.", inline=False)
        embed.add_field(name="TICKET RULES", value="• One ticket per issue.\n• Include your order ID when relevant.\n• Be patient and respectful with staff.\n• Do not post payment details or product keys publicly.", inline=False)
        embed.set_footer(text=f"© {cfg['shop'].get('name', 'JARVIS SHOP')} · Private support")
        await channel.send(embed=embed, view=SupportPanelView(open_ticket_button))
        await db.audit(i.user.id, "ticket_panel_posted", f"guild={i.guild_id}; channel={channel.id}")
        await i.response.send_message(f"Support panel posted in {channel.mention}.", ephemeral=True)

    @bot.tree.command(name="ticket_close",description="Close current support ticket (staff)")
    async def ticket_close(i:discord.Interaction, reason: str = "Resolved"):
        if not staff_check(i): return await i.response.send_message("Staff permission required.",ephemeral=True)
        cur = await db.conn.execute("SELECT id,user_id FROM tickets WHERE channel_id=? AND status='open'", (i.channel_id,))
        ticket_row = await cur.fetchone()
        if not ticket_row: return await i.response.send_message("This channel isn't an open JARVIS ticket.", ephemeral=True)
        await db.conn.execute("UPDATE tickets SET status='closed',closed_at=? WHERE id=?", (db_now(), ticket_row["id"]))
        await db.conn.commit()
        member = i.guild.get_member(ticket_row["user_id"]) if i.guild else None
        if member:
            overwrite = i.channel.overwrites_for(member)
            overwrite.send_messages = False
            await i.channel.set_permissions(member, overwrite=overwrite, reason=f"Ticket closed by {i.user}")
        try: await i.channel.edit(name=f"closed-{ticket_row['id']:04d}")
        except discord.HTTPException: pass
        await db.audit(i.user.id,"ticket_closed",f"ticket={ticket_row['id']}; reason={reason[:200]}")
        await i.response.send_message(f"Ticket #{ticket_row['id']} closed and archived. Reason: {discord.utils.escape_markdown(reason[:200])}", ephemeral=True)

    @bot.tree.command(name="ticket_claim", description="Claim an open support ticket (staff)")
    async def ticket_claim(i: discord.Interaction):
        if not staff_check(i): return await i.response.send_message("Staff permission required.", ephemeral=True)
        cur = await db.conn.execute("UPDATE tickets SET assigned_to=? WHERE channel_id=? AND status='open' AND (assigned_to IS NULL OR assigned_to=?)", (i.user.id, i.channel_id, i.user.id))
        await db.conn.commit()
        if not cur.rowcount: return await i.response.send_message("This ticket is closed, not recognized, or assigned to another staff member.", ephemeral=True)
        await db.audit(i.user.id, "ticket_claimed", f"channel={i.channel_id}")
        await i.response.send_message(f"Ticket claimed by {i.user.mention}.")

    @bot.tree.command(name="ticket_reopen", description="Reopen an archived ticket (staff)")
    async def ticket_reopen(i: discord.Interaction, ticket_id: int):
        if not staff_check(i): return await i.response.send_message("Staff permission required.", ephemeral=True)
        cur = await db.conn.execute("SELECT * FROM tickets WHERE id=? AND status='closed'", (ticket_id,))
        row = await cur.fetchone()
        if not row: return await i.response.send_message("Closed ticket not found.", ephemeral=True)
        channel = i.guild.get_channel(row["channel_id"]) if i.guild and row["channel_id"] else None
        if not channel: return await i.response.send_message("The archived ticket channel no longer exists.", ephemeral=True)
        member = i.guild.get_member(row["user_id"])
        if member:
            overwrite = channel.overwrites_for(member)
            overwrite.send_messages = True
            await channel.set_permissions(member, overwrite=overwrite, reason=f"Ticket reopened by {i.user}")
        await db.conn.execute("UPDATE tickets SET status='open',closed_at=NULL WHERE id=? AND status='closed'", (ticket_id,))
        await db.conn.commit()
        try: await channel.edit(name=f"ticket-{ticket_id:04d}-reopened")
        except discord.HTTPException: pass
        await db.audit(i.user.id, "ticket_reopened", f"ticket={ticket_id}")
        await i.response.send_message(f"Ticket #{ticket_id} reopened in {channel.mention}.", ephemeral=True)

    @bot.tree.command(name="coupon_create",description="Create a percentage coupon (admin)")
    async def coupon_create(i:discord.Interaction,code:str,percent:app_commands.Range[int,1,90],uses:int=-1):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        await db.conn.execute("INSERT OR REPLACE INTO coupons(code,percent,uses_left) VALUES(?,?,?)",(code.upper()[:32],percent,uses))
        await db.conn.commit(); await db.audit(i.user.id,"coupon_create",code.upper())
        await i.response.send_message("Coupon created. Customers can enter it during checkout.",ephemeral=True)

    @bot.tree.command(name="staff_report",description="View basic shop operations report")
    async def staff_report(i:discord.Interaction):
        if not staff_check(i): return await i.response.send_message("Staff permission required.",ephemeral=True)
        cur=await db.conn.execute("SELECT status,COUNT(*) n FROM orders GROUP BY status"); rows=await cur.fetchall()
        await i.response.send_message("**Order status summary**\n"+"\n".join(f'{r["status"]}: {r["n"]}' for r in rows),ephemeral=True)

    @bot.tree.command(name="analytics",description="View sales analytics (admin)")
    async def analytics(i:discord.Interaction):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        cur=await db.conn.execute("SELECT COUNT(*) n,COALESCE(SUM(total),0) revenue FROM orders WHERE payment_status='paid'")
        r=await cur.fetchone()
        cur=await db.conn.execute("SELECT COUNT(*) n FROM users"); u=await cur.fetchone()
        await i.response.send_message(f"**Shop analytics**\nPaid orders: {r['n']}\nRecorded gross revenue: {money(r['revenue'],cfg)}\nKnown customers: {u['n']}\n\nRevenue is gross recorded order value, not verified bank balance or net profit.",ephemeral=True)

    @bot.tree.command(name="owner_status",description="View bot status (owner)")
    async def owner_status(i:discord.Interaction):
        if not owner_check(i): return await i.response.send_message("Owner permission required.",ephemeral=True)
        await i.response.send_message(f"JARVIS SHOP online · Discord latency {bot.latency*1000:.0f} ms · DB `{cfg['database']['path']}` · AI `{cfg['ai'].get('provider')}`",ephemeral=True)

    @bot.tree.command(name="store_health", description="Review inventory, orders, database integrity, and backup status (owner)")
    async def store_health(i: discord.Interaction):
        if not owner_check(i): return await i.response.send_message("Owner permission required.", ephemeral=True)
        cur = await db.conn.execute("SELECT COUNT(*) n FROM products WHERE active=1 AND stock BETWEEN 0 AND 3")
        low_stock = (await cur.fetchone())["n"]
        cur = await db.conn.execute("SELECT COUNT(*) n FROM orders WHERE status IN ('awaiting_payment','refund_requested')")
        unresolved = (await cur.fetchone())["n"]
        cur = await db.conn.execute("SELECT COUNT(*) n FROM orders WHERE status='delivery_failed'")
        failed_delivery = (await cur.fetchone())["n"]
        cur = await db.conn.execute("PRAGMA integrity_check")
        integrity = (await cur.fetchone())[0]
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")
        backups = [f for f in os.listdir(backup_dir) if f.lower().endswith((".sqlite3", ".db"))] if os.path.isdir(backup_dir) else []
        score = 100 - min(30, low_stock * 5) - min(25, unresolved * 5) - min(30, failed_delivery * 10) - (40 if integrity != "ok" else 0) - (10 if not backups else 0)
        lines = [f"Health score: **{max(0, score)}/100**", f"Database integrity: `{integrity}`", f"Active products with stock 0–3: **{low_stock}**", f"Unresolved orders: **{unresolved}**", f"Delivery failures: **{failed_delivery}**", f"Database backup files found: **{len(backups)}**"]
        if low_stock: lines.append("Recommendation: review low inventory and restock as needed.")
        if unresolved: lines.append("Recommendation: review pending payment or refund cases.")
        if not backups: lines.append("Recommendation: create and test a database backup; backup recency is not yet tracked.")
        await i.response.send_message("**JARVIS Store Health**\n" + "\n".join(lines), ephemeral=True)

    backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")

    @bot.tree.command(name="backup_create", description="Create a consistent SQLite backup (owner)")
    async def backup_create(i: discord.Interaction):
        if not owner_check(i): return await i.response.send_message("Owner permission required.", ephemeral=True)
        try: name = await db.create_backup(backup_dir)
        except Exception:
            log.exception("Database backup failed")
            return await i.response.send_message("Backup failed. Check the bot log for details.", ephemeral=True)
        await db.audit(i.user.id, "backup_created", name)
        await i.response.send_message(f"Backup created: `{name}`. Verify it with `$backup verify {name}` before relying on it.", ephemeral=True)

    @bot.tree.command(name="backup_list", description="List local database backups (owner)")
    async def backup_list(i: discord.Interaction):
        if not owner_check(i): return await i.response.send_message("Owner permission required.", ephemeral=True)
        rows = db.list_backups(backup_dir)
        if not rows: return await i.response.send_message("No local database backups found.", ephemeral=True)
        body = "\n".join(f"`{name}` · {size:,} bytes" for name, size, _ in rows[:20])
        await i.response.send_message("**Local backups**\n" + body, ephemeral=True)

    @bot.tree.command(name="backup_verify", description="Check backup integrity without restoring it (owner)")
    async def backup_verify(i: discord.Interaction, filename: str):
        if not owner_check(i): return await i.response.send_message("Owner permission required.", ephemeral=True)
        try: valid, result = db.verify_backup(backup_dir, filename)
        except ValueError as exc: return await i.response.send_message(str(exc), ephemeral=True)
        await db.audit(i.user.id, "backup_verified", f"file={filename}; valid={valid}")
        await i.response.send_message(f"Backup `{filename}`: **{'valid' if valid else 'invalid'}** · `{result}`", ephemeral=True)

    @bot.tree.command(name="ai_help",description="Ask the optional local Ollama assistant")
    async def ai_help(i:discord.Interaction,question:str):
        await i.response.defer(ephemeral=True,thinking=True)
        answer=await ai.ask("You are JARVIS SHOP's support assistant. Do not claim to access live orders, payment status, or private data. Direct users to shop commands for account-specific information. Be concise.\nUser question: "+question)
        await i.followup.send(answer[:1900],ephemeral=True)

    dm_cooldowns = {}

    async def deliver_staff_dm(sender, guild_name, recipient, message):
        """Send one staff DM; audit only metadata and never persist its contents."""
        if recipient.bot:
            return False, "Bot accounts cannot receive customer messages."
        if not message.strip() or len(message) > 1500:
            return False, "Message must contain 1–1,500 characters."
        loop = asyncio.get_running_loop()
        current = loop.time()
        remaining = 10 - (current - dm_cooldowns.get(sender.id, -100))
        if remaining > 0:
            return False, f"Please wait {remaining:.1f}s before sending another staff DM."
        dm_cooldowns[sender.id] = current
        try:
            await recipient.send(f"**Message from {guild_name} shop staff:**\n{message}", allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await db.audit(sender.id, "staff_dm_failed", f"recipient={recipient.id}; reason=closed_dms")
            return False, "I couldn't DM that person; their DMs may be closed or they may block this bot."
        except discord.HTTPException:
            await db.audit(sender.id, "staff_dm_failed", f"recipient={recipient.id}; reason=discord_http_error")
            return False, "Discord could not deliver the DM. Try again later."
        await db.audit(sender.id, "staff_dm_sent", f"recipient={recipient.id}; chars={len(message)}")
        return True, "DM sent. Message content was not stored in the audit log."

    async def dm_campaign_delay():
        cur = await db.conn.execute("SELECT value FROM settings WHERE key='dm_campaign_delay_seconds'")
        row = await cur.fetchone()
        configured = int(row["value"]) if row else int(cfg.get("security", {}).get("dm_campaign_delay_seconds", 5))
        return max(5, min(30, configured))

    @bot.tree.command(name="dm_user", description="Send one direct message to a user (staff)")
    @app_commands.guild_only()
    @app_commands.describe(recipient="User to contact", message="Message text, up to 1,500 characters")
    async def dm_user(i: discord.Interaction, recipient: discord.User, message: str):
        if not staff_check(i):
            return await i.response.send_message("Staff permission required.", ephemeral=True)
        ok, result = await deliver_staff_dm(i.user, i.guild.name, recipient, message)
        await i.response.send_message(result, ephemeral=True)

    @bot.tree.command(name="dm_order", description="Contact the customer associated with an order (staff)")
    @app_commands.guild_only()
    async def dm_order(i: discord.Interaction, order_id: str, message: str):
        if not staff_check(i): return await i.response.send_message("Staff permission required.", ephemeral=True)
        order = await db.order(order_id.strip().upper())
        if not order: return await i.response.send_message("Order not found.", ephemeral=True)
        try: recipient = await bot.fetch_user(order["user_id"])
        except (discord.NotFound, discord.Forbidden): return await i.response.send_message("The order owner could not be found.", ephemeral=True)
        except discord.HTTPException: return await i.response.send_message("Discord could not look up the order owner.", ephemeral=True)
        ok, result = await deliver_staff_dm(i.user, i.guild.name, recipient, f"Regarding order {order['public_id']}: {message}")
        await db.audit(i.user.id, "staff_dm_order", f"order={order['public_id']}; recipient={recipient.id}; delivered={ok}")
        await i.response.send_message(result, ephemeral=True)

    @bot.tree.command(name="dm_test", description="Check whether a user can receive a DM from the bot (staff)")
    @app_commands.guild_only()
    async def dm_test(i: discord.Interaction, recipient: discord.User):
        if not staff_check(i): return await i.response.send_message("Staff permission required.", ephemeral=True)
        try:
            await recipient.send("This is a DM delivery test from the shop support bot.", allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await db.audit(i.user.id, "dm_test_failed", f"recipient={recipient.id}; reason=forbidden")
            return await i.response.send_message("Discord rejected the test DM. Their DMs may be closed or they may block this bot.", ephemeral=True)
        except discord.HTTPException:
            await db.audit(i.user.id, "dm_test_failed", f"recipient={recipient.id}; reason=http_error")
            return await i.response.send_message("Discord could not deliver the test DM.", ephemeral=True)
        await db.audit(i.user.id, "dm_test_sent", f"recipient={recipient.id}")
        await i.response.send_message("Test DM delivered.", ephemeral=True)

    @bot.tree.command(name="dm_optin", description="Choose whether to receive promotional shop DMs")
    @app_commands.choices(choice=[app_commands.Choice(name="Opt in", value="on"), app_commands.Choice(name="Opt out", value="off")])
    async def dm_optin(i: discord.Interaction, choice: app_commands.Choice[str]):
        enabled = choice.value == "on"
        await db.conn.execute("INSERT INTO dm_preferences(user_id,promotional_opt_in,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET promotional_opt_in=excluded.promotional_opt_in,updated_at=excluded.updated_at", (i.user.id, int(enabled), db_now()))
        await db.conn.commit()
        await i.response.send_message("Promotional shop DMs are **on**. Use `$dmoptin off` anytime." if enabled else "Promotional shop DMs are **off**.", ephemeral=True)

    @bot.tree.command(name="dm_history", description="Inspect recent DM delivery metadata for a user (admin)")
    @app_commands.guild_only()
    async def dm_history(i: discord.Interaction, recipient: discord.User):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("SELECT action,details,created_at FROM audit WHERE details LIKE ? AND action LIKE '%%dm%%' ORDER BY id DESC LIMIT 10", (f"%recipient={recipient.id}%",))
        rows = await cur.fetchall()
        if not rows: return await i.response.send_message("No recent DM delivery records found.", ephemeral=True)
        body = "\n".join(f"`{r['created_at'][:19]}` · `{r['action']}` · {discord.utils.escape_markdown(r['details'][:120])}" for r in rows)
        await i.response.send_message(embed=build_embed(f"DM history · {recipient}", body, kind="security"), ephemeral=True)

    @bot.tree.command(name="dm_settings", description="View DM campaign delivery settings (owner)")
    async def dm_settings(i: discord.Interaction, delay_seconds: int = None):
        if not owner_check(i): return await i.response.send_message("Owner permission required.", ephemeral=True)
        if delay_seconds is not None:
            if not 5 <= delay_seconds <= 30: return await i.response.send_message("Campaign delay must be between 5 and 30 seconds.", ephemeral=True)
            await db.conn.execute("INSERT INTO settings(key,value) VALUES('dm_campaign_delay_seconds',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(delay_seconds),)); await db.conn.commit()
        cur = await db.conn.execute("SELECT COUNT(*) n FROM dm_preferences WHERE promotional_opt_in=1")
        opted = (await cur.fetchone())["n"]
        delay = await dm_campaign_delay()
        await i.response.send_message(embed=build_embed("DM Manager Settings", f"Promotional opt-ins: **{opted}**\nCampaign delay: **{delay}s per recipient**\nCampaigns require a separate admin approval. Only opted-in customers are eligible."), ephemeral=True)

    @bot.tree.command(name="dm_campaign_create", description="Create an opt-in customer DM campaign for approval (admin)")
    @app_commands.guild_only()
    async def dm_campaign_create(i: discord.Interaction, message: str, as_embed: bool = False):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        if not message.strip() or len(message) > 1500: return await i.response.send_message("Campaign text must contain 1–1,500 characters.", ephemeral=True)
        cur = await db.conn.execute("INSERT INTO dm_campaigns(guild_id,created_by,audience,message,status,embed_enabled,created_at) VALUES(?,?,?,?,'pending_approval',?,?)", (i.guild.id, i.user.id, "opted_in_customers", message, int(as_embed), db_now()))
        await db.conn.commit()
        campaign_id = cur.lastrowid
        await db.audit(i.user.id, "dm_campaign_created", f"campaign={campaign_id}; guild={i.guild.id}; chars={len(message)}")
        await i.response.send_message(embed=build_embed(f"Campaign #{campaign_id} · awaiting approval", f"Audience: opted-in previous buyers in this server\nFormat: {'branded embed' if as_embed else 'plain text'}\nPreview: {discord.utils.escape_markdown(message[:500])}\n\nA different owner must run `$dmcampaign_approve {campaign_id}`."), ephemeral=True)

    @bot.tree.command(name="dm_campaign_approve", description="Approve a pending opt-in DM campaign (admin)")
    @app_commands.guild_only()
    async def dm_campaign_approve(i: discord.Interaction, campaign_id: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='approved',approved_by=? WHERE id=? AND guild_id=? AND status='pending_approval' AND created_by<>?", (i.user.id, campaign_id, i.guild.id, i.user.id))
        await db.conn.commit()
        if not cur.rowcount: return await i.response.send_message("Campaign not found, not pending, or you created it. A different admin must approve it.", ephemeral=True)
        await db.audit(i.user.id, "dm_campaign_approved", f"campaign={campaign_id}; guild={i.guild.id}")
        await i.response.send_message(f"Campaign #{campaign_id} approved. Run `$dmcampaign_run {campaign_id}` to start it.", ephemeral=True)

    async def run_dm_campaign(campaign_id, guild_id, actor_id):
        try:
            guild = bot.get_guild(guild_id)
            if guild is None:
                await db.conn.execute("UPDATE dm_campaigns SET status='failed',finished_at=? WHERE id=? AND status='running'", (db_now(), campaign_id)); await db.conn.commit()
                return
            cur = await db.conn.execute("SELECT message,embed_enabled FROM dm_campaigns WHERE id=?", (campaign_id,)); campaign = await cur.fetchone()
            cur = await db.conn.execute("SELECT p.user_id FROM dm_preferences p WHERE p.promotional_opt_in=1 AND EXISTS (SELECT 1 FROM orders o WHERE o.user_id=p.user_id) ORDER BY p.user_id")
            opted_buyer_ids = {row["user_id"] for row in await cur.fetchall()}
            recipients = [member.id for member in guild.members if member.id in opted_buyer_ids and not member.bot]
            delay = await dm_campaign_delay()
            for user_id in recipients:
                cur = await db.conn.execute("SELECT status FROM dm_campaigns WHERE id=?", (campaign_id,)); state = await cur.fetchone()
                if not state or state["status"] != "running": break
                cur = await db.conn.execute("SELECT promotional_opt_in FROM dm_preferences WHERE user_id=?", (user_id,)); pref = await cur.fetchone()
                if not pref or not pref["promotional_opt_in"]: continue
                cur = await db.conn.execute("SELECT 1 FROM dm_campaign_deliveries WHERE campaign_id=? AND user_id=?", (campaign_id, user_id))
                if await cur.fetchone(): continue
                status, reason = "failed", "user_unavailable"
                user = bot.get_user(user_id)
                if user is None:
                    try: user = await bot.fetch_user(user_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException): user = None
                if user:
                    try:
                        values = {"user": str(user), "username": user.display_name, "user_mention": user.mention, "server": guild.name, "shop_name": cfg["shop"].get("name", "JARVIS SHOP")}
                        personalized = re.sub(r"\{([a-z_]+)\}", lambda match: values.get(match.group(1), ""), campaign["message"])
                        if campaign["embed_enabled"]:
                            await user.send(embed=build_embed("Shop update", personalized, kind="info"), allowed_mentions=discord.AllowedMentions.none())
                        else:
                            await user.send(personalized, allowed_mentions=discord.AllowedMentions.none())
                        status, reason = "sent", None
                    except discord.Forbidden: reason = "dm_rejected"
                    except discord.HTTPException: reason = "discord_http_error"
                await db.conn.execute("INSERT OR IGNORE INTO dm_campaign_deliveries(campaign_id,user_id,status,reason,attempted_at) VALUES(?,?,?,?,?)", (campaign_id, user_id, status, reason, db_now()))
                await db.conn.execute("UPDATE dm_campaigns SET sent_count=(SELECT COUNT(*) FROM dm_campaign_deliveries WHERE campaign_id=? AND status='sent'),failed_count=(SELECT COUNT(*) FROM dm_campaign_deliveries WHERE campaign_id=? AND status='failed') WHERE id=?", (campaign_id, campaign_id, campaign_id))
                await db.conn.commit()
                await asyncio.sleep(delay)
            await db.conn.execute("UPDATE dm_campaigns SET status=CASE WHEN status='running' THEN 'completed' ELSE status END,finished_at=CASE WHEN status='running' THEN ? ELSE finished_at END WHERE id=?", (db_now(), campaign_id)); await db.conn.commit()
            cur = await db.conn.execute("SELECT status,sent_count,failed_count FROM dm_campaigns WHERE id=?", (campaign_id,)); result = await cur.fetchone()
            await db.audit(actor_id, "dm_campaign_finished", f"campaign={campaign_id}; status={result['status']}; sent={result['sent_count']}; failed={result['failed_count']}")
        except asyncio.CancelledError:
            await db.conn.execute("UPDATE dm_campaigns SET status='interrupted',finished_at=? WHERE id=? AND status='running'", (db_now(), campaign_id)); await db.conn.commit()
            raise
        except Exception:
            log.exception("DM campaign %s failed", campaign_id)
            await db.conn.execute("UPDATE dm_campaigns SET status='failed',finished_at=? WHERE id=? AND status='running'", (db_now(), campaign_id)); await db.conn.commit()

    @bot.tree.command(name="dm_campaign_run", description="Run an approved opt-in customer DM campaign (admin)")
    @app_commands.guild_only()
    async def dm_campaign_run(i: discord.Interaction, campaign_id: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='running',started_at=? WHERE id=? AND guild_id=? AND status='approved'", (db_now(), campaign_id, i.guild.id))
        await db.conn.commit()
        if not cur.rowcount: return await i.response.send_message("Campaign must be approved and not previously started.", ephemeral=True)
        task = bot.loop.create_task(run_dm_campaign(campaign_id, i.guild.id, i.user.id))
        bot.dm_campaign_tasks[campaign_id] = task
        task.add_done_callback(lambda _task, cid=campaign_id: bot.dm_campaign_tasks.pop(cid, None))
        await i.response.send_message(f"Campaign #{campaign_id} started in the background. Check `$dmcampaign_status {campaign_id}` for progress.", ephemeral=True)

    @bot.tree.command(name="dm_campaign_status", description="View campaign status and delivery counts (admin)")
    @app_commands.guild_only()
    async def dm_campaign_status(i: discord.Interaction, campaign_id: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("SELECT status,sent_count,failed_count,created_by,approved_by FROM dm_campaigns WHERE id=? AND guild_id=?", (campaign_id, i.guild.id)); row = await cur.fetchone()
        if not row: return await i.response.send_message("Campaign not found.", ephemeral=True)
        approved = f"<@{row['approved_by']}>" if row['approved_by'] else "Pending"
        await i.response.send_message(embed=build_embed(f"Campaign #{campaign_id}", f"Status: **{row['status']}**\nDelivered: **{row['sent_count']}**\nFailed: **{row['failed_count']}**\nCreated by: <@{row['created_by']}>\nApproved by: {approved}"), ephemeral=True)

    @bot.tree.command(name="dm_campaigns", description="List recent DM campaigns and delivery summaries (admin)")
    @app_commands.guild_only()
    async def dm_campaigns(i: discord.Interaction):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("SELECT id,status,sent_count,failed_count,created_at FROM dm_campaigns WHERE guild_id=? ORDER BY id DESC LIMIT 10", (i.guild.id,)); rows = await cur.fetchall()
        if not rows: return await i.response.send_message("No campaigns yet.", ephemeral=True)
        body = "\n".join(f"`#{r['id']}` · **{r['status']}** · sent {r['sent_count']} · failed {r['failed_count']} · {r['created_at'][:10]}" for r in rows)
        await i.response.send_message(embed=build_embed("Recent DM Campaigns", body), ephemeral=True)

    @bot.tree.command(name="dm_campaign_cancel", description="Cancel an approved or running campaign (admin)")
    @app_commands.guild_only()
    async def dm_campaign_cancel(i: discord.Interaction, campaign_id: int):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.", ephemeral=True)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='cancelled',finished_at=? WHERE id=? AND guild_id=? AND status IN ('pending_approval','approved','running')", (db_now(), campaign_id, i.guild.id)); await db.conn.commit()
        if not cur.rowcount: return await i.response.send_message("Campaign not found or already finished.", ephemeral=True)
        await db.audit(i.user.id, "dm_campaign_cancelled", f"campaign={campaign_id}")
        await i.response.send_message(f"Campaign #{campaign_id} marked cancelled. Active runs stop after the current delivery.", ephemeral=True)

    @bot.tree.command(name="verify_link",description="Get the official JARVIS verification link")
    @app_commands.describe(destination="Configured community to join")
    async def verify_link(i:discord.Interaction,destination:str="main"):
        targets=bot.verify_portal.targets()
        if destination not in targets:
            return await i.response.send_message("That verification destination is not configured. Ask an admin to check config/settings.yaml.",ephemeral=True)
        if not bot.verify_portal.vcfg.get("enabled") or not bot.verify_portal.public_url():
            return await i.response.send_message("Verification portal is not configured yet. The owner must configure its public HTTPS URL and Discord OAuth app.",ephemeral=True)
        url=f"{bot.verify_portal.public_url()}/verify/{destination}"
        await i.response.send_message(f"**JARVIS VERIFY**\nContinue here: {url}\nYou will see the target server and explicitly authorize Discord before joining.",ephemeral=True)

    @bot.tree.command(name="verify_stats",description="View verification and server growth stats (admin)")
    async def verify_stats(i:discord.Interaction):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        cur=await db.conn.execute("SELECT result,COUNT(*) n FROM verify_events GROUP BY result"); rows=await cur.fetchall()
        cur=await db.conn.execute("SELECT COUNT(*) n FROM invite_attributions"); invites=await cur.fetchone()
        cur=await db.conn.execute("SELECT campaign,COUNT(*) n FROM invite_attributions GROUP BY campaign ORDER BY n DESC LIMIT 10"); campaigns=await cur.fetchall()
        body="\n".join(f"{r['result']}: {r['n']}" for r in rows) or "No verification events yet."
        camp="\n".join(f"• {r['campaign']}: {r['n']} joins" for r in campaigns) or "No tracked invite joins yet."
        await i.response.send_message(f"**JARVIS VERIFY report**\n{body}\nTracked invite joins: {invites['n']}\n\n**Top campaigns**\n{camp}",ephemeral=True)

    @bot.tree.command(name="growth_invite",description="Create a permanent tracked invite link (admin)")
    @app_commands.describe(campaign="Short campaign label, e.g. TikTok bio or YouTube Shorts")
    async def growth_invite(i:discord.Interaction,campaign:str):
        if not admin_check(i): return await i.response.send_message("Administrator permission required.",ephemeral=True)
        if not i.guild or not i.channel: return await i.response.send_message("Use this command in the destination server.",ephemeral=True)
        try: invite=await i.channel.create_invite(max_age=0,max_uses=0,unique=True,reason=f"JARVIS growth campaign: {campaign[:80]}")
        except discord.Forbidden: return await i.response.send_message("I need Create Invite permission in this channel.",ephemeral=True)
        await db.conn.execute("INSERT INTO invite_campaigns(code,guild_id,channel_id,campaign,created_by,created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (invite.code,i.guild_id,i.channel_id,campaign[:100],i.user.id)); await db.conn.commit()
        try: bot.invite_cache[i.guild_id]={x.code:x.uses for x in await i.guild.invites()}
        except Exception: pass
        await i.response.send_message(f"**Tracked invite created**\nCampaign: `{campaign[:100]}`\n{invite.url}\n\nShare this link to measure joins attributed to this campaign.",ephemeral=True)

    @bot.tree.command(name="verify_config",description="Show verification setup health (owner)")
    async def verify_config(i:discord.Interaction):
        if not owner_check(i): return await i.response.send_message("Owner permission required.",ephemeral=True)
        v=bot.verify_portal.vcfg
        targets=bot.verify_portal.targets()
        lines=[f"Portal enabled: {bool(v.get('enabled'))}",f"Portal running: {bool(bot.verify_portal.runner)}",f"Public URL configured: {bool(bot.verify_portal.public_url())}",f"OAuth client configured: {bool(v.get('client_id') and v.get('client_secret'))}",f"Targets configured: {len(targets)}"]
        for key,t in targets.items(): lines.append(f"• {key}: {t.get('name','Community')} · guild {t.get('guild_id')} · role {t.get('role_id',0)}")
        await i.response.send_message("**JARVIS VERIFY setup**\n"+"\n".join(lines),ephemeral=True)


    # --- JARVIS VERIFY: one-command server setup, structure cloning, and opt-in updates ---
    @bot.tree.command(name="server_setup", description="Create a verified-only community layout in this server")
    async def server_setup(i: discord.Interaction):
        if not admin_check(i):
            return await i.response.send_message("Administrator permission required.", ephemeral=True)
        if not i.guild:
            return await i.response.send_message("Run this inside the server you want to configure.", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        guild = i.guild
        me = guild.me or guild.get_member(bot.user.id)
        if not me or not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
            return await i.followup.send("I need **Manage Roles** and **Manage Channels** permissions. Give me those permissions and try again.", ephemeral=True)
        try:
            verified = discord.utils.get(guild.roles, name="Verified Member")
            if verified is None:
                verified = await guild.create_role(name="Verified Member", colour=discord.Colour.from_str("#6C63FF"), hoist=True, mentionable=False, reason="JARVIS verified-only server setup")
            updates = discord.utils.get(guild.roles, name="JARVIS Updates")
            if updates is None:
                updates = await guild.create_role(name="JARVIS Updates", colour=discord.Colour.from_str("#36B37E"), mentionable=False, reason="Opt-in community announcements")

            everyone = guild.default_role
            verify_cat = discord.utils.get(guild.categories, name="START HERE")
            if verify_cat is None:
                verify_cat = await guild.create_category("START HERE")
            verify_channel = discord.utils.get(guild.text_channels, name="verify-here")
            if verify_channel is None:
                verify_channel = await guild.create_text_channel("verify-here", category=verify_cat)
            else:
                await verify_channel.edit(category=verify_cat)
            await verify_cat.set_permissions(everyone, view_channel=True, read_message_history=True, send_messages=True)
            await verify_cat.set_permissions(verified, view_channel=True, read_message_history=True, send_messages=True)
            await verify_channel.set_permissions(everyone, view_channel=True, read_message_history=True, send_messages=True)
            await verify_channel.set_permissions(verified, view_channel=True, read_message_history=True, send_messages=True)

            community = discord.utils.get(guild.categories, name="COMMUNITY")
            if community is None:
                community = await guild.create_category("COMMUNITY")
            await community.set_permissions(everyone, view_channel=False)
            await community.set_permissions(verified, view_channel=True, read_message_history=True, send_messages=True)
            channel_specs = [
                ("general", "text"), ("introductions", "text"),
                ("announcements", "announcements"), ("voice-lounge", "voice")
            ]
            made = []
            for name, kind in channel_specs:
                if kind == "voice":
                    ch = discord.utils.get(guild.voice_channels, name=name)
                    if ch is None: ch = await guild.create_voice_channel(name, category=community)
                else:
                    ch = discord.utils.get(guild.text_channels, name=name)
                    if ch is None: ch = await guild.create_text_channel(name, category=community)
                if ch.category_id != community.id: await ch.edit(category=community)
                await ch.set_permissions(everyone, view_channel=False)
                await ch.set_permissions(verified, view_channel=True, connect=True, read_message_history=True, send_messages=(kind != "announcements"), speak=True)
                made.append(ch.mention if hasattr(ch, "mention") else ch.name)
            # Lock every existing channel except the onboarding category/channel.
            # Explicit staff/admin role overwrites remain intact; Discord Administrator bypasses channel denies.
            for existing_channel in guild.channels:
                if existing_channel.id in (verify_cat.id, verify_channel.id):
                    continue
                await existing_channel.set_permissions(everyone, view_channel=False)
                await existing_channel.set_permissions(verified, view_channel=True, read_message_history=True)

            # Make the OAuth target's role assignment match the role just created.
            for target in cfg.get("verify", {}).get("targets", []):
                if int(target.get("guild_id", 0) or 0) == guild.id:
                    target["role_id"] = verified.id
            try:
                import copy, yaml
                from pathlib import Path
                settings_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
                if settings_path.exists():
                    safe_cfg = copy.deepcopy(cfg)
                    safe_cfg.get("discord", {}).pop("token", None)
                    safe_cfg.get("verify", {}).pop("client_id", None)
                    safe_cfg.get("verify", {}).pop("client_secret", None)
                    with settings_path.open("w", encoding="utf-8") as f:
                        yaml.safe_dump(safe_cfg, f, sort_keys=False, allow_unicode=True)
            except Exception:
                log.exception("Could not persist the auto-created Verified role ID")
            await db.audit(i.user.id, "server_setup", f"guild={guild.id}; verified_role={verified.id}")
            panel_url = None
            for key, target in bot.verify_portal.targets().items():
                if int(target.get("guild_id", 0) or 0) == guild.id and bot.verify_portal.public_url():
                    panel_url = f"{bot.verify_portal.public_url()}/verify/{key}"
                    break
            embed = verification_panel_embed()
            embed.set_footer(text="JARVIS • Community Security")
            if panel_url:
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(label="Verify", style=discord.ButtonStyle.link, url=panel_url))
                await verify_channel.send(embed=embed, view=view)
                panel_status = "Verification panel posted."
            else:
                await verify_channel.send(embed=embed)
                panel_status = "Panel posted without a button; configure the OAuth portal and run $verifypanel after setup."
            await i.followup.send(
                f"**Server setup complete.**\nCreated/reused `{verified.name}` and `{updates.name}`.\n"
                f"`@everyone` can only see **START HERE**; **COMMUNITY** is visible to Verified Members.\n"
                f"Channels: {', '.join(made)}\n{panel_status}\n\n"
                "Note: this configures the current existing server; Discord does not let bots create brand-new servers.", ephemeral=True)
        except discord.Forbidden:
            await i.followup.send("Discord denied a setup action. Check my role position and Manage Roles/Manage Channels permissions.", ephemeral=True)
        except discord.HTTPException as e:
            await i.followup.send(f"Discord API error during setup: `{e}`. Some channels/roles may already have been created; rerun `$server_setup` to continue.", ephemeral=True)

    @bot.tree.command(name="verify_panel", description="Post or refresh the verification panel")
    async def verify_panel(i: discord.Interaction, channel: discord.TextChannel = None, destination: str = "main"):
        if not admin_check(i):
            return await i.response.send_message("Administrator permission required.", ephemeral=True)
        targets = bot.verify_portal.targets()
        if destination not in targets or not bot.verify_portal.public_url():
            return await i.response.send_message("That verification destination or public verification URL is not configured.", ephemeral=True)
        channel = channel or i.channel
        if not isinstance(channel, discord.TextChannel):
            return await i.response.send_message("Choose a text channel.", ephemeral=True)
        url = f"{bot.verify_portal.public_url()}/verify/{destination}"
        embed = verification_panel_embed()
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Verify", style=discord.ButtonStyle.link, url=url))
        await channel.send(embed=embed, view=view)
        await i.response.send_message(f"Verification panel posted in {channel.mention}.", ephemeral=True)

    @bot.tree.command(name="server_clone", description="Clone roles and channel layout into another server you administer")
    @app_commands.describe(source_server_id="Server ID to copy from", destination_server_id="Existing server ID to copy into")
    async def server_clone(i: discord.Interaction, source_server_id: str, destination_server_id: str):
        if not admin_check(i):
            return await i.response.send_message("Administrator permission required in the source server.", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            source = bot.get_guild(int(source_server_id)); dest = bot.get_guild(int(destination_server_id))
        except ValueError:
            return await i.followup.send("Server IDs must be numeric.", ephemeral=True)
        if not source or not dest:
            return await i.followup.send("The bot must already be a member of both existing servers.", ephemeral=True)
        if source.id == dest.id:
            return await i.followup.send("Choose two different servers.", ephemeral=True)
        try:
            source_member = source.get_member(i.user.id) or await source.fetch_member(i.user.id)
            dest_member = dest.get_member(i.user.id) or await dest.fetch_member(i.user.id)
            if not source_member.guild_permissions.administrator or not dest_member.guild_permissions.administrator:
                return await i.followup.send("For safety, you must have Discord Administrator permission in both servers.", ephemeral=True)
            bot_member = dest.me or dest.get_member(bot.user.id)
            if not bot_member or not bot_member.guild_permissions.manage_roles or not bot_member.guild_permissions.manage_channels:
                return await i.followup.send("I need Manage Roles and Manage Channels in the destination server.", ephemeral=True)
            role_map = {source.default_role.id: dest.default_role}
            created_roles = 0; created_channels = 0; skipped = 0
            for role in sorted(source.roles, key=lambda r: r.position):
                if role.is_default() or role.managed or role.name in ("@everyone",):
                    continue
                existing = discord.utils.get(dest.roles, name=role.name)
                if existing:
                    role_map[role.id] = existing; continue
                try:
                    new_role = await dest.create_role(name=role.name[:100], permissions=discord.Permissions(role.permissions.value), colour=role.colour, hoist=role.hoist, mentionable=role.mentionable, reason=f"JARVIS structure clone from {source.name}")
                    role_map[role.id] = new_role; created_roles += 1
                except discord.HTTPException:
                    skipped += 1
            def mapped_overwrites(channel):
                result = {}
                for target_obj, overwrite in channel.overwrites.items():
                    if isinstance(target_obj, discord.Role) and target_obj.id in role_map:
                        result[role_map[target_obj.id]] = overwrite
                return result
            category_map = {}
            for category in sorted(source.categories, key=lambda c: c.position):
                existing = discord.utils.get(dest.categories, name=category.name)
                if existing:
                    category_map[category.id] = existing; continue
                try:
                    category_map[category.id] = await dest.create_category(category.name[:100], overwrites=mapped_overwrites(category), reason=f"JARVIS structure clone from {source.name}")
                    created_channels += 1
                except discord.HTTPException:
                    skipped += 1
            for ch in sorted(source.channels, key=lambda c: (getattr(c, "position", 0), c.name)):
                if isinstance(ch, discord.CategoryChannel):
                    continue
                category = category_map.get(ch.category_id)
                existing = next((x for x in dest.channels if x.name == ch.name and type(x) is type(ch)), None)
                if existing:
                    continue
                try:
                    ow = mapped_overwrites(ch)
                    if isinstance(ch, discord.TextChannel):
                        await dest.create_text_channel(ch.name[:100], category=category, topic=ch.topic, nsfw=ch.nsfw, slowmode_delay=ch.slowmode_delay, overwrites=ow, reason=f"JARVIS structure clone from {source.name}")
                    elif isinstance(ch, discord.VoiceChannel):
                        await dest.create_voice_channel(ch.name[:100], category=category, bitrate=min(ch.bitrate, dest.bitrate_limit), user_limit=ch.user_limit, overwrites=ow, reason=f"JARVIS structure clone from {source.name}")
                    else:
                        skipped += 1; continue
                    created_channels += 1
                except discord.HTTPException:
                    skipped += 1
            await db.audit(i.user.id, "server_clone", f"source={source.id}; destination={dest.id}; roles={created_roles}; channels={created_channels}; skipped={skipped}")
            await i.followup.send(f"**Structure clone finished**\nSource: **{discord.utils.escape_markdown(source.name)}**\nDestination: **{discord.utils.escape_markdown(dest.name)}**\nNew roles: `{created_roles}` · New categories/channels: `{created_channels}` · Skipped: `{skipped}`\n\nMessages, members, personal permission overwrites, integrations, webhooks, and invite links are intentionally not copied. Run `$server_setup` in the destination to apply the verified-only layout.", ephemeral=True)
        except discord.Forbidden:
            await i.followup.send("Discord denied a clone action. Check Administrator access and the bot's role hierarchy/permissions.", ephemeral=True)
        except discord.HTTPException as e:
            await i.followup.send(f"Discord API error: `{e}`. The clone may be partial; rerun to fill missing structure.", ephemeral=True)

    @bot.tree.command(name="updates_join", description="Opt in to JARVIS community announcements")
    async def updates_join(i: discord.Interaction):
        if not i.guild or not isinstance(i.user, discord.Member):
            return await i.response.send_message("Use this in a server.", ephemeral=True)
        role = discord.utils.get(i.guild.roles, name="JARVIS Updates")
        if not role:
            return await i.response.send_message("The owner must run `$server_setup` first.", ephemeral=True)
        if role in i.user.roles:
            return await i.response.send_message("You're already subscribed.", ephemeral=True)
        try:
            await i.user.add_roles(role, reason="Member opted in to community updates")
            await i.response.send_message("You're subscribed to community announcements. Use `$updates leave` anytime.", ephemeral=True)
        except discord.Forbidden:
            await i.response.send_message("I cannot assign the updates role. Check my Manage Roles permission and role position.", ephemeral=True)

    @bot.tree.command(name="updates_leave", description="Opt out of JARVIS community announcements")
    async def updates_leave(i: discord.Interaction):
        if not i.guild or not isinstance(i.user, discord.Member):
            return await i.response.send_message("Use this in a server.", ephemeral=True)
        role = discord.utils.get(i.guild.roles, name="JARVIS Updates")
        if not role or role not in i.user.roles:
            return await i.response.send_message("You're not subscribed.", ephemeral=True)
        try:
            await i.user.remove_roles(role, reason="Member opted out of community updates")
            await i.response.send_message("You've been unsubscribed.", ephemeral=True)
        except discord.Forbidden:
            await i.response.send_message("I cannot remove the updates role. Check my role permissions.", ephemeral=True)

    @bot.tree.command(name="announce_updates", description="Post an announcement to members who opted in")
    @app_commands.describe(message="Announcement text", channel="Where to post the announcement")
    async def announce_updates(i: discord.Interaction, message: str, channel: discord.TextChannel = None):
        if not admin_check(i):
            return await i.response.send_message("Administrator permission required.", ephemeral=True)
        if not i.guild:
            return await i.response.send_message("Use this in a server.", ephemeral=True)
        if len(message) > 1500:
            return await i.response.send_message("Keep announcements under 1,500 characters.", ephemeral=True)
        role = discord.utils.get(i.guild.roles, name="JARVIS Updates")
        if not role:
            return await i.response.send_message("The owner must run `$server_setup` first to create the opt-in updates role.", ephemeral=True)
        channel = channel or i.channel
        if not isinstance(channel, discord.TextChannel):
            return await i.response.send_message("Choose a text channel.", ephemeral=True)
        embed = discord.Embed(title="📢 Community update", description=message, colour=0x36B37E)
        await channel.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False))
        await db.audit(i.user.id, "announce_updates", f"guild={i.guild.id}; role={role.id}; channel={channel.id}")
        await i.response.send_message(f"Announcement posted in {channel.mention} for members who opted in with `$updates join`.", ephemeral=True)


    # --- Prefix command suite (one shared $ prefix; permissions are role-based) ---
    # Prefix-only commands are permission-gated by configured roles, independent of prefix.
    def prefix_is_staff(ctx):
        return isinstance(ctx.author, discord.Member) and is_staff(ctx.author, cfg)

    def prefix_is_admin(ctx):
        return isinstance(ctx.author, discord.Member) and is_admin(ctx.author, cfg)

    @bot.command(name="help", aliases=["commands", "menu", "help_shop"])
    async def prefix_help(ctx):
        embeds = command_list_embeds(bot, prefixes, ctx.author, cfg)
        await ctx.reply(embeds=embeds, mention_author=False)

    @bot.command(name="serversnapshot")
    async def prefix_serversnapshot(ctx, action: str = "list", *, name: str = ""):
        if not is_owner(ctx.author, cfg):
            return await ctx.reply("Bot owner permission required.", mention_author=False)
        if not ctx.guild:
            return await ctx.reply("Use this command in the server you want to back up or restore.", mention_author=False)
        action = action.lower()
        if action == "create":
            name = name.strip()
            if not name:
                return await ctx.reply("Syntax: `$serversnapshot create <name>`", mention_author=False)
            snapshot = capture_server_snapshot(ctx.guild, name)
            path = save_server_snapshot(snapshot)
            await db.audit(ctx.author.id, "server_snapshot_created", f"guild={ctx.guild.id}; name={name[:48]}")
            return await ctx.reply(f"Saved snapshot **{discord.utils.escape_markdown(name[:48])}**. Roles: {len(snapshot['roles'])}; categories/channels: {len(snapshot['channels'])}. File: `{path.name}`. Member lists, messages, tokens, webhooks, and personal overwrites are not included.", mention_author=False)
        if action == "list":
            items = list_snapshots(ctx.guild.id)
            return await ctx.reply("Snapshots: " + (", ".join(f'`{name}`' for name, _ in items) if items else "none yet") + "\nCreate with `$serversnapshot create <name>`.", mention_author=False)
        if action == "restore":
            name = name.strip()
            if not name:
                return await ctx.reply("Syntax: `$serversnapshot restore <name> [source_server_id]`", mention_author=False)
            parts = name.rsplit(maxsplit=1)
            source_id = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else ctx.guild.id
            if source_id != ctx.guild.id:
                name = parts[0]
            member = ctx.author if isinstance(ctx.author, discord.Member) else None
            source_guild = bot.get_guild(source_id)
            me = ctx.guild.me
            if not member or not member.guild_permissions.administrator or not me or not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
                return await ctx.reply("You need Discord Administrator access, and I need Manage Roles and Manage Channels.", mention_author=False)
            try:
                if not source_guild:
                    return await ctx.reply("The bot must be in the snapshot's source server too.", mention_author=False)
                if source_id != ctx.guild.id:
                    source_member = source_guild.get_member(ctx.author.id) or await source_guild.fetch_member(ctx.author.id)
                    if not source_member.guild_permissions.administrator:
                        return await ctx.reply("For cross-server restores, you need Discord Administrator in both source and destination servers.", mention_author=False)
                snapshot = load_server_snapshot(source_id, name)
                roles, channels, skipped = await restore_server_snapshot(ctx.guild, snapshot)
            except FileNotFoundError:
                return await ctx.reply("I couldn't find that snapshot. Run `$serversnapshot list`.", mention_author=False)
            await db.audit(ctx.author.id, "server_snapshot_restored", f"guild={ctx.guild.id}; name={name[:48]}; roles={roles}; channels={channels}; skipped={skipped}")
            return await ctx.reply(f"Additive restore finished: {roles} roles and {channels} categories/channels created; {skipped} skipped. Existing roles and channels were left in place.", mention_author=False)
        await ctx.reply("Syntax: `$serversnapshot create <name>` · `$serversnapshot list` · `$serversnapshot restore <name> [source_server_id]`", mention_author=False)

    @bot.command(name="recoverypanel")
    async def prefix_recoverypanel(ctx, channel: discord.TextChannel = None, destination: str = "main"):
        if not is_owner(ctx.author, cfg):
            return await ctx.reply("Bot owner permission required.", mention_author=False)
        channel = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        target = bot.verify_portal.targets().get(destination)
        if not target or not bot.verify_portal.public_url() or not channel:
            return await ctx.reply("Choose a text channel and configured verification destination. Syntax: `$recoverypanel #channel [destination]`.", mention_author=False)
        url = f"{bot.verify_portal.public_url()}/verify/{destination}"
        embed = discord.Embed(title="Member recovery · rejoin", description=f"If you left or lost access to **{target.get('name', 'this community')}**, use Discord's official authorization to opt in and rejoin. This does not restore access silently; you choose whether to authorize.", colour=0x7565D9)
        embed.add_field(name="Privacy", value="Recovery is optional. Members must check the recovery box during Discord verification. The bot stores only an encrypted OAuth refresh grant for later migration; never a password or session token. Members can revoke the app in Discord Authorized Apps.", inline=False)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Verify & rejoin", style=discord.ButtonStyle.link, url=url))
        await channel.send(embed=embed, view=view)
        await db.audit(ctx.author.id, "member_recovery_panel", f"guild={ctx.guild.id if ctx.guild else 0}; channel={channel.id}; destination={destination}")
        await ctx.reply(f"Opt-in recovery panel posted in {channel.mention}.", mention_author=False)

    @bot.command(name="dashboard", aliases=["dash"])
    async def prefix_dashboard(ctx):
        if not is_owner(ctx.author, cfg):
            return await ctx.reply("Bot owner permission required.", mention_author=False)
        if not bot.local_dashboard.runner:
            return await ctx.reply("The local dashboard is disabled or failed to start. Check the bot log.", mention_author=False)
        try:
            await ctx.author.send(f"Your private JARVIS Pull dashboard link (open it on the same computer running the bot):\n{bot.local_dashboard.url}\n\nKeep this link private.")
            await ctx.reply("I sent the private local dashboard link to your DMs.", mention_author=False)
        except discord.Forbidden:
            await ctx.reply("I couldn't DM you. Enable server DMs, then run `$dashboard` again. The private link is also printed in the bot console log.", mention_author=False)

    async def start_member_pull(source_id, destination_key, member_id=None, actor_id=0):
        if not bot.verify_portal.recovery_cipher:
            raise ValueError("Encrypted recovery is not configured. Set JARVIS_RECOVERY_KEY and restart the bot.")
        if bot.member_restore_task and not bot.member_restore_task.done():
            raise RuntimeError("A pull is already running.")
        target = bot.verify_portal.targets().get(str(destination_key))
        destination = bot.get_guild(int(target["guild_id"])) if target else None
        if not destination:
            raise ValueError("The configured destination server is unavailable to the bot.")
        me = destination.me
        if not me or not me.guild_permissions.create_instant_invite or (int(target.get("role_id", 0) or 0) and not me.guild_permissions.manage_roles):
            raise ValueError("The bot needs Create Invite in the destination, plus Manage Roles if assigning the verified role.")
        async def setting(key, default):
            cur = await db.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return int(row["value"]) if row else default
        low = await setting("member_pull_delay_min", 2); high = await setting("member_pull_delay_max", 4)
        limit = 1 if member_id is not None else await setting("member_pull_limit", 100)
        control = {"stop": False, "pause_event": asyncio.Event()}; control["pause_event"].set()
        bot.member_restore_control = control
        job_id = secrets.token_hex(4)
        bot.member_restore_status = {"job_id": job_id, "state": "queued", "detail": "Preparing consented member queue."}
        async def run_pull():
            try:
                async def progress(counters):
                    state = "stopping" if control["stop"] else "paused" if not control["pause_event"].is_set() else "running"
                    bot.member_restore_status = {"job_id": job_id, "state": state, "detail": f"{counters['processed']}/{counters['eligible']} processed · {counters['joined']} joined · {counters['already_or_queued']} already present · {counters['revoked_or_invalid']} revoked/invalid · {counters['failed']} failed"}
                result = await bot.verify_portal.restore_members(source_id, destination_key, member_id=member_id, control=control, delay_range=(low, high), progress_callback=progress, max_members=limit)
                state = "stopped" if result["stopped"] else "complete"
                bot.member_restore_status = {"job_id": job_id, "state": state, "detail": f"{result['processed']}/{result['eligible']} processed · {result['joined']} joined · {result['already_or_queued']} already present · {result['revoked_or_invalid']} revoked/invalid · {result['failed']} failed"}
                await db.audit(actor_id, "member_pull_completed", f"job={job_id}; source={source_id}; destination={destination.id}; joined={result['joined']}; failed={result['failed']}; stopped={result['stopped']}")
            except Exception as exc:
                log.exception("Member pull job failed")
                bot.member_restore_status = {"job_id": job_id, "state": "failed", "detail": str(exc)[:300]}
        bot.member_restore_task = asyncio.create_task(run_pull())
        return {"job_id": job_id, "limit": limit, "delay_min": low, "delay_max": high}

    bot.start_member_pull = start_member_pull

    @bot.command(name="pull", aliases=["memberrestore"])
    async def prefix_pull(ctx, action: str = "help", *, arguments: str = ""):
        keys = {"delay_min": "member_pull_delay_min", "delay_max": "member_pull_delay_max", "limit": "member_pull_limit"}
        async def read_setting(key, default):
            cur = await db.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return int(row["value"]) if row else default
        if not is_owner(ctx.author, cfg):
            return await ctx.reply("Bot owner permission required.", mention_author=False)
        if not ctx.guild:
            return await ctx.reply("Run Pull commands in the destination server.", mention_author=False)
        action = action.lower()
        if action in {"status", "share"}:
            status = bot.member_restore_status
            return await ctx.reply(f"**Pull {status.get('job_id','—')} · {status.get('state','idle')}**\n{status.get('detail','No pull has run.')}", mention_author=False)
        if action in {"pause", "resume", "stop"}:
            control = bot.member_restore_control
            if not control or not bot.member_restore_task or bot.member_restore_task.done():
                return await ctx.reply("There is no active pull to control.", mention_author=False)
            if action == "pause":
                control["pause_event"].clear()
            elif action == "resume":
                control["pause_event"].set()
            else:
                control["stop"] = True
                control["pause_event"].set()
            bot.member_restore_status["state"] = {"pause": "paused", "resume": "running", "stop": "stopping"}[action]
            return await ctx.reply(f"Pull {action} requested. Check `$pull status` for the counters.", mention_author=False)
        if action == "settings":
            parts = arguments.split()
            if not parts:
                low = await read_setting(keys["delay_min"], 2); high = await read_setting(keys["delay_max"], 4); limit = await read_setting(keys["limit"], 100)
                return await ctx.reply(f"**Pull defaults**\nPacing: `{low}–{high}s` per member · Max members per pull: `{limit}`\nSet with `$pull settings delay <min_seconds> <max_seconds>` or `$pull settings limit <members>`.", mention_author=False)
            try:
                if parts[0] == "delay" and len(parts) == 3:
                    low, high = int(parts[1]), int(parts[2])
                    if low < 1 or high < low or high > 60: raise ValueError
                    values = ((keys["delay_min"], low), (keys["delay_max"], high))
                elif parts[0] == "limit" and len(parts) == 2:
                    limit = int(parts[1])
                    if not 1 <= limit <= 1000: raise ValueError
                    values = ((keys["limit"], limit),)
                else: raise ValueError
            except ValueError:
                return await ctx.reply("Use `$pull settings delay <min 1–60> <max up to 60>` or `$pull settings limit <1–1000>`.", mention_author=False)
            for key, value in values:
                await db.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            await db.conn.commit()
            return await ctx.reply("Pull settings saved.", mention_author=False)
        if action == "start":
            quick = arguments.split()
            if len(quick) == 2 and all(part.isdigit() for part in quick):
                destination_id, role_id = map(int, quick)
                source_target = bot.verify_portal.targets().get("main")
                if not source_target:
                    return await ctx.reply("I couldn't find the `main` source in `config/settings.yaml`. Keep the old server configured with key `main`.", mention_author=False)
                destination_guild = bot.get_guild(destination_id)
                if not destination_guild:
                    return await ctx.reply("The bot must already be in the new server. Invite it there, then retry.", mention_author=False)
                role = destination_guild.get_role(role_id)
                if not role or role.is_default() or role.managed:
                    return await ctx.reply("That role ID wasn't found as an assignable role in the new server.", mention_author=False)
                destination_key = f"pull-{destination_id}-{role_id}"
                targets = cfg.setdefault("verify", {}).setdefault("targets", [])
                targets[:] = [item for item in targets if str(item.get("key")) != destination_key]
                targets.append({"key": destination_key, "name": destination_guild.name, "guild_id": destination_id, "role_id": role_id})
                try:
                    job = await bot.start_member_pull(int(source_target["guild_id"]), destination_key, actor_id=ctx.author.id)
                except (RuntimeError, ValueError) as exc:
                    return await ctx.reply(str(exc), mention_author=False)
                cur = await db.conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM verify_recovery_grants WHERE source_guild_id=?", (int(source_target["guild_id"]),))
                eligible = (await cur.fetchone())["n"]
                return await ctx.reply(f"Pull `{job['job_id']}` started from **{source_target.get('name', 'Main server')}** to **{destination_guild.name}**. Up to `{min(eligible, job['limit'])}` opted-in people; role **{role.name}**. Use `$pull status`, `$pull pause`, `$pull resume`, or `$pull stop`.", mention_author=False)
        if action not in {"plan", "start", "one"}:
            return await ctx.reply("**Quick pull**\n`$pull start <new_server_id> <role_id>` — pulls opted-in members from your `main` server and gives them that role.\n`$pull status` · `$pull pause` · `$pull resume` · `$pull stop`\n`$pull plan <source_server_id> <destination_key> [member_id]` and `$pull one <source_server_id> <destination_key> <member_id>` are available for advanced use. Only recovery-opted members are eligible.", mention_author=False)
        parts = arguments.split()
        expected = 3 if action == "one" else None
        if len(parts) < (3 if action == "one" else 2) or (action == "one" and len(parts) != expected) or (action == "plan" and len(parts) > 3) or (action == "start" and len(parts) != 2):
            return await ctx.reply("Syntax: `$pull plan <source_server_id> <destination_key> [member_id]` · `$pull start <source_server_id> <destination_key>` · `$pull one <source_server_id> <destination_key> <member_id>`", mention_author=False)
        try:
            source_id = int(parts[0]); destination_key = parts[1]; member_id = int(parts[2]) if len(parts) == 3 else None
        except ValueError:
            return await ctx.reply("Server and member IDs must be numeric.", mention_author=False)
        if action == "one" and member_id is None:
            return await ctx.reply("Provide one member ID to pull.", mention_author=False)
        target = bot.verify_portal.targets().get(destination_key)
        if not target or int(target.get("guild_id", 0) or 0) != ctx.guild.id:
            return await ctx.reply("Destination key must point to the server where you ran this command.", mention_author=False)
        cur = await db.conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM verify_recovery_grants WHERE source_guild_id=?" + (" AND user_id=?" if member_id is not None else ""), (source_id, member_id) if member_id is not None else (source_id,))
        eligible = (await cur.fetchone())["n"]
        if action == "plan":
            limit = 1 if member_id is not None else await read_setting(keys["limit"], 100)
            return await ctx.reply(f"**Pull plan**\nEligible opted-in members: `{eligible}` · This run limit: `{min(eligible, limit)}` · Destination: **{target.get('name', destination_key)}**\nOnly encrypted recovery grants from successful JARVIS verifications qualify. Members without a grant are not included.", mention_author=False)
        if not eligible:
            return await ctx.reply("No eligible recovery grants found for that source/member. Older verification records without recovery opt-in cannot be pulled.", mention_author=False)
        try:
            job = await bot.start_member_pull(source_id, destination_key, member_id=member_id, actor_id=ctx.author.id)
        except (RuntimeError, ValueError) as exc:
            return await ctx.reply(str(exc), mention_author=False)
        await ctx.reply(f"Pull `{job['job_id']}` queued for up to `{min(eligible, job['limit'])}` eligible member(s). Pacing: `{job['delay_min']}–{job['delay_max']}s` per member. Use `$pull status`, `$pull pause`, `$pull resume`, or `$pull stop` to control it.", mention_author=False)

    @bot.command(name="ping")
    async def prefix_ping(ctx):
        await ctx.reply(f"🏓 Pong! `{bot.latency*1000:.0f} ms`", mention_author=False)

    @bot.command(name="shop", aliases=["store", "catalog"])
    async def prefix_shop(ctx):
        rows = await db.products()
        if not rows:
            return await ctx.reply("The shop is being prepared. Please check back soon.", mention_author=False)
        embed = discord.Embed(title=cfg["shop"].get("name", "JARVIS SHOP"), description="Available products · use `$addcart PRODUCT-ID [QTY]`", colour=0x7565D9)
        for item in rows[:25]:
            stock = "Unlimited" if item["stock"] < 0 else str(item["stock"])
            embed.add_field(name=f'#{item["id"]} · {item["name"]} · {money(item["price"],cfg)}', value=f'{item["description"][:160]}\n{item["category"]} · Stock: {stock}', inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="search", aliases=["find"])
    async def prefix_search(ctx, *, query: str):
        rows = await db.search_products(query)
        if not rows:
            return await ctx.reply("No products matched that search.", mention_author=False)
        embed = discord.Embed(title=f"Search results · {query[:80]}", colour=0x7565D9)
        for item in rows:
            stock = "Unlimited" if item["stock"] < 0 else str(item["stock"])
            embed.add_field(name=f'#{item["id"]} · {item["name"]} · {money(item["price"],cfg)}', value=f'{item["description"][:180]}\n{item["category"]} · Stock: {stock}', inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="addcart", aliases=["cartadd"])
    async def prefix_addcart(ctx, product_id: int, quantity: int = 1):
        if quantity < 1 or quantity > int(cfg["security"].get("max_cart_quantity", 20)):
            return await ctx.reply("Invalid quantity.", mention_author=False)
        try:
            await db.cart_add(ctx.author.id, product_id, quantity, cfg["security"].get("max_cart_quantity", 20))
        except ValueError as exc:
            return await ctx.reply(str(exc), mention_author=False)
        await ctx.reply("Added to your cart. Use `.cart` to review it.", mention_author=False)

    @bot.command(name="cart")
    async def prefix_cart(ctx):
        rows = await db.cart(ctx.author.id)
        if not rows:
            return await ctx.reply("Your cart is empty. Browse with `$shop`.", mention_author=False)
        total = sum(row["quantity"] * row["price"] for row in rows)
        body = "\n".join(f'{row["name"]} × {row["quantity"]} — {money(row["price"]*row["quantity"],cfg)}' for row in rows)
        await ctx.reply(f"{body}\n\n**Total: {money(total,cfg)}**\nUse `$checkout` when ready.", mention_author=False)

    @bot.command(name="cartremove")
    async def prefix_cartremove(ctx, product_id: int):
        removed = await db.cart_remove(ctx.author.id, product_id)
        await ctx.reply("Removed from cart." if removed else "That product isn't in your cart.", mention_author=False)

    @bot.command(name="cartclear")
    async def prefix_cartclear(ctx):
        await db.cart_clear(ctx.author.id)
        await ctx.reply("Your cart is empty now.", mention_author=False)

    @bot.command(name="wishlist")
    async def prefix_wishlist(ctx, action: str = "view", product_id: int = None):
        action = action.lower()
        if action == "add" and product_id is not None:
            try: await db.wishlist_add(ctx.author.id, product_id)
            except ValueError as exc: return await ctx.reply(str(exc), mention_author=False)
            return await ctx.reply("Added to your wishlist.", mention_author=False)
        if action == "remove" and product_id is not None:
            removed = await db.wishlist_remove(ctx.author.id, product_id)
            return await ctx.reply("Removed from your wishlist." if removed else "That product wasn't in your wishlist.", mention_author=False)
        if action not in ("view", "list"):
            return await ctx.reply("Usage: `.wishlist [view|add|remove] [PRODUCT-ID]`", mention_author=False)
        rows = await db.wishlist(ctx.author.id)
        if not rows: return await ctx.reply("Your wishlist is empty.", mention_author=False)
        await ctx.reply("**Your wishlist**\n" + "\n".join(f'`#{p["id"]}` **{p["name"]}** · {money(p["price"],cfg)}' for p in rows[:20]), mention_author=False)

    @bot.command(name="product")
    async def prefix_product(ctx, product_id: int):
        cur = await db.conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,))
        p = await cur.fetchone()
        if not p: return await ctx.reply("Product not found.", mention_author=False)
        stock = "Unlimited" if p["stock"] < 0 else str(p["stock"])
        embed = discord.Embed(title=p["name"], description=p["description"][:4000], colour=0x7565D9)
        embed.add_field(name="Price", value=money(p["price"], cfg))
        embed.add_field(name="Category", value=p["category"])
        embed.add_field(name="Stock", value=stock)
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="checkout")
    async def prefix_checkout(ctx, coupon_code: str = ""):
        try:
            public_id, total = await db.checkout(ctx.author.id, cfg["shop"].get("order_prefix", "JX"), coupon_code or None)
        except ValueError as exc:
            return await ctx.reply(str(exc), mention_author=False)
        await db.audit(ctx.author.id, "checkout_prefix", public_id)
        await ctx.reply(f"Order **{public_id}** created · Total: **{money(total,cfg)}**.\n{cfg['shop'].get('payment_instructions','Contact staff for payment instructions')}\nSubmit your reference with `$payment ORDER-ID REFERENCE`.", mention_author=False)

    @bot.command(name="payment")
    async def prefix_payment(ctx, order_id: str, *, transaction_reference: str):
        order_id = order_id.strip().upper()
        if not transaction_reference.strip() or len(transaction_reference) > 160:
            return await ctx.reply("Payment reference must contain 1–160 characters.", mention_author=False)
        order_row = await db.order(order_id, ctx.author.id)
        if not order_row: return await ctx.reply("Order not found.", mention_author=False)
        if order_row["payment_status"] == "paid": return await ctx.reply("This order is already marked paid.", mention_author=False)
        await db.conn.execute("UPDATE orders SET payment_ref=?,payment_status='submitted',updated_at=datetime('now') WHERE public_id=?", (transaction_reference.strip()[:160], order_id))
        await db.conn.commit(); await db.audit(ctx.author.id, "payment_submitted_prefix", order_id)
        await ctx.reply("Payment reference submitted for staff verification. This does not mean payment is confirmed.", mention_author=False)

    @bot.command(name="orderspending")
    async def prefix_orderspending(ctx):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        cur=await db.conn.execute("SELECT * FROM orders WHERE payment_status='submitted' ORDER BY id LIMIT 20"); rows=await cur.fetchall()
        if not rows: return await ctx.reply("No payment submissions waiting.", mention_author=False)
        await ctx.reply("\n".join(f'`{o["public_id"]}` · user `{o["user_id"]}` · {money(o["total"],cfg)} · ref `{o["payment_ref"]}`' for o in rows), mention_author=False)

    @bot.command(name="paymentverify")
    async def prefix_paymentverify(ctx, order_id: str):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        order_id=order_id.strip().upper(); order_row=await db.order(order_id)
        if not order_row: return await ctx.reply("Order not found.", mention_author=False)
        if order_row["payment_status"] != "submitted": return await ctx.reply("Order has no submitted payment reference.", mention_author=False)
        await db.conn.execute("UPDATE orders SET payment_status='paid',status='paid',updated_at=datetime('now') WHERE public_id=?", (order_id,)); await db.conn.commit()
        await db.audit(ctx.author.id,"payment_verified_prefix",order_id)
        await ctx.reply(f"Payment verified for **{order_id}**. Delivery must now be fulfilled.", mention_author=False)

    @bot.command(name="deliver")
    async def prefix_deliver(ctx, order_id: str, *, delivery_note: str = ""):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        order_id=order_id.strip().upper(); order_row=await db.order(order_id)
        if not order_row: return await ctx.reply("Order not found.", mention_author=False)
        if order_row["payment_status"] != "paid": return await ctx.reply("Payment must be verified before delivery.", mention_author=False)
        await db.conn.execute("UPDATE orders SET status='delivered',updated_at=datetime('now') WHERE public_id=?", (order_id,))
        await db.conn.execute("UPDATE order_items SET delivery_status='delivered' WHERE order_id=?", (order_row["id"],)); await db.conn.commit()
        await db.audit(ctx.author.id,"delivered_prefix",f"{order_id}; note={delivery_note[:150]}")
        await ctx.reply(f"Order `{order_id}` marked delivered.", mention_author=False)

    @bot.command(name="order")
    async def prefix_order(ctx, order_id: str):
        order_row = await db.order(order_id, ctx.author.id)
        if not order_row:
            return await ctx.reply("Order not found.", mention_author=False)
        items = await db.order_items(order_row["id"])
        detail = "\n".join(f'• {x["product_name"]} × {x["quantity"]}' for x in items)
        await ctx.reply(f'**{order_row["public_id"]}** · {order_row["status"]} · Payment: {order_row["payment_status"]} · {money(order_row["total"],cfg)}\n{detail}', mention_author=False)

    @bot.command(name="cancelorder")
    async def prefix_cancelorder(ctx, order_id: str):
        try: await db.cancel_unpaid_order(order_id, ctx.author.id)
        except ValueError as exc: return await ctx.reply(str(exc), mention_author=False)
        await db.audit(ctx.author.id, "order_cancelled_prefix", order_id)
        await ctx.reply(f"Unpaid order `{order_id}` cancelled. Finite stock was returned.", mention_author=False)

    @bot.command(name="verify")
    async def prefix_verify(ctx, destination: str = "main"):
        targets = bot.verify_portal.targets()
        if destination not in targets:
            return await ctx.reply("That verification destination is not configured.", mention_author=False)
        if not bot.verify_portal.vcfg.get("enabled") or not bot.verify_portal.public_url():
            return await ctx.reply("Verification is not configured yet. Ask the owner to configure the HTTPS OAuth portal.", mention_author=False)
        url = f"{bot.verify_portal.public_url()}/verify/{destination}"
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Verify", style=discord.ButtonStyle.link, url=url))
        await ctx.send(embed=verification_panel_embed(), view=view)

    @bot.command(name="verifypanel")
    async def prefix_verifypanel(ctx, destination: str = "main"):
        if not is_owner(ctx.author, cfg):
            return await ctx.reply("Owner permission required.", mention_author=False)
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Run this command in the text channel where the panel should appear.", mention_author=False)
        targets = bot.verify_portal.targets()
        public_url = bot.verify_portal.public_url()
        if destination not in targets or not public_url:
            return await ctx.reply("That verification destination or public URL is not configured. Set it in `config/settings.yaml`, then restart the bot.", mention_author=False)
        url = f"{public_url}/verify/{destination}"
        embed = verification_panel_embed()
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Verify", style=discord.ButtonStyle.link, url=url))
        await ctx.send(embed=embed, view=view)
        await ctx.message.add_reaction("✅")

    @bot.command(name="updates")
    async def prefix_updates(ctx, action: str = "join"):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("Use this command inside a server.", mention_author=False)
        role = discord.utils.get(ctx.guild.roles, name="JARVIS Updates")
        if role is None:
            return await ctx.reply("The owner must run `$server_setup` first.", mention_author=False)
        try:
            if action.lower() in ("leave", "off", "unsubscribe"):
                if role in ctx.author.roles: await ctx.author.remove_roles(role, reason="Member opted out of updates")
                return await ctx.reply("You've unsubscribed from community updates.", mention_author=False)
            if action.lower() not in ("join", "on", "subscribe"):
                return await ctx.reply("Use `$updates join` or `$updates leave`.", mention_author=False)
            if role not in ctx.author.roles: await ctx.author.add_roles(role, reason="Member opted in to updates")
            await ctx.reply("You're subscribed. Use `$updates leave` anytime to opt out.", mention_author=False)
        except discord.Forbidden:
            await ctx.reply("I cannot manage that role. Check my Manage Roles permission and role hierarchy.", mention_author=False)

    @bot.command(name="serverinfo", aliases=["server"])
    async def prefix_serverinfo(ctx):
        if not ctx.guild:
            return await ctx.reply("Use this in a server.", mention_author=False)
        g = ctx.guild
        embed = discord.Embed(title=g.name, colour=0x7565D9)
        if g.icon: embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Members", value=str(g.member_count or "Unknown"))
        embed.add_field(name="Channels", value=str(len(g.channels)))
        embed.add_field(name="Roles", value=str(len(g.roles)))
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, style="D"), inline=False)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>")
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="userinfo", aliases=["whois"])
    async def prefix_userinfo(ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"User info · {member}", colour=member.colour if member.colour.value else 0x7565D9)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, style="D") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="D"), inline=True)
        roles = [r.mention for r in member.roles if not r.is_default()]
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:15]) or "None", inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="avatar", aliases=["pfp"])
    async def prefix_avatar(ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"{member.display_name}'s avatar", colour=0x7565D9)
        embed.set_image(url=member.display_avatar.url)
        await ctx.reply(embed=embed, mention_author=False)

    @bot.command(name="poll")
    async def prefix_poll(ctx, *, poll_text: str):
        parts = [part.strip() for part in poll_text.split("|") if part.strip()]
        if len(parts) < 3 or len(parts) > 11:
            return await ctx.reply("Format: `.poll Question | Option 1 | Option 2` (up to 10 options).", mention_author=False)
        symbols = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        embed = discord.Embed(title="📊 Community Poll", description="\n".join(f"{symbols[idx]} {option[:100]}" for idx, option in enumerate(parts[1:])), colour=0x7565D9)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        msg = await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        for symbol in symbols[:len(parts)-1]:
            try: await msg.add_reaction(symbol)
            except discord.HTTPException: break

    @bot.command(name="suggest", aliases=["suggestion"])
    async def prefix_suggest(ctx, *, idea: str):
        if len(idea) < 8 or len(idea) > 1000:
            return await ctx.reply("Please write a suggestion between 8 and 1,000 characters.", mention_author=False)
        channel = discord.utils.get(ctx.guild.text_channels, name="suggestions") if ctx.guild else None
        if channel is None:
            return await ctx.reply("I couldn't find a #suggestions channel. Ask an admin to create one.", mention_author=False)
        embed = discord.Embed(title="💡 New suggestion", description=idea, colour=0x36B37E)
        embed.set_footer(text=f"Submitted by {ctx.author} · {ctx.author.id}")
        msg = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        for emoji in ("👍", "👎"):
            try: await msg.add_reaction(emoji)
            except discord.HTTPException: pass
        await ctx.reply(f"Suggestion submitted in {channel.mention}. Thanks!", mention_author=False)

    @bot.command(name="clear", aliases=["purge"])
    async def prefix_clear(ctx, amount: int):
        if not prefix_is_staff(ctx):
            return await ctx.reply("Staff permission required.", mention_author=False)
        if amount < 1 or amount > 100:
            return await ctx.reply("Choose a number from 1 to 100.", mention_author=False)
        if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            return await ctx.reply("I need Manage Messages permission.", mention_author=False)
        deleted = await ctx.channel.purge(limit=amount + 1, reason=f"Bulk cleanup by {ctx.author} via JARVIS")
        notice = await ctx.send(f"🧹 Deleted {max(0,len(deleted)-1)} message(s).", allowed_mentions=discord.AllowedMentions.none())
        await notice.delete(delay=5)
        await db.audit(ctx.author.id, "messages_cleared", f"guild={ctx.guild.id}; channel={ctx.channel.id}; count={max(0,len(deleted)-1)}")

    @bot.command(name="slowmode")
    async def prefix_slowmode(ctx, seconds: int):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        if seconds < 0 or seconds > 21600:
            return await ctx.reply("Slowmode must be between 0 and 21,600 seconds.", mention_author=False)
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Configured by {ctx.author} via JARVIS")
        await ctx.reply(f"Slowmode set to **{seconds} seconds**.", mention_author=False)
        await db.audit(ctx.author.id, "slowmode_changed", f"channel={ctx.channel.id}; seconds={seconds}")

    async def set_channel_lock(ctx, locked: bool):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = not locked
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Channel {'locked' if locked else 'unlocked'} by {ctx.author}")
        await ctx.reply("🔒 Channel locked for @everyone." if locked else "🔓 Channel unlocked for @everyone.", mention_author=False)
        await db.audit(ctx.author.id, "channel_lock" if locked else "channel_unlock", f"channel={ctx.channel.id}")

    @bot.command(name="lock")
    async def prefix_lock(ctx): await set_channel_lock(ctx, True)

    @bot.command(name="unlock")
    async def prefix_unlock(ctx): await set_channel_lock(ctx, False)

    @bot.command(name="announce")
    async def prefix_announce(ctx, *, message: str):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        if len(message) > 1800:
            return await ctx.reply("Keep announcements under 1,800 characters.", mention_author=False)
        embed = discord.Embed(title="📢 Announcement", description=message, colour=0x7565D9)
        embed.set_footer(text=f"Posted by {ctx.author.display_name}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await db.audit(ctx.author.id, "prefix_announcement", f"guild={ctx.guild.id}; channel={ctx.channel.id}")

    @bot.command(name="say")
    async def prefix_say(ctx, *, text: str):
        # Keep output text exact and suppress mention notifications.
        await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    @bot.command(name="dm")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def prefix_dm(ctx, recipient: discord.User, *, message: str):
        if not prefix_is_staff(ctx):
            return await ctx.reply("Staff permission required.", mention_author=False)
        if not ctx.guild:
            return await ctx.reply("Use this command in your shop server.", mention_author=False)
        _, result = await deliver_staff_dm(ctx.author, ctx.guild.name, recipient, message)
        await ctx.reply(result, mention_author=False)

    @bot.command(name="dmorder")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def prefix_dmorder(ctx, order_id: str, *, message: str):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        if not ctx.guild: return await ctx.reply("Use this command in your shop server.", mention_author=False)
        order = await db.order(order_id.strip().upper())
        if not order: return await ctx.reply("Order not found.", mention_author=False)
        try: recipient = await bot.fetch_user(order["user_id"])
        except (discord.NotFound, discord.Forbidden): return await ctx.reply("The order owner could not be found.", mention_author=False)
        except discord.HTTPException: return await ctx.reply("Discord could not look up the order owner.", mention_author=False)
        ok, result = await deliver_staff_dm(ctx.author, ctx.guild.name, recipient, f"Regarding order {order['public_id']}: {message}")
        await db.audit(ctx.author.id, "staff_dm_order", f"order={order['public_id']}; recipient={recipient.id}; delivered={ok}")
        await ctx.reply(result, mention_author=False)

    @bot.command(name="dmtest")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def prefix_dmtest(ctx, recipient: discord.User):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        if recipient.bot: return await ctx.reply("Bot accounts cannot receive customer DMs.", mention_author=False)
        try: await recipient.send("This is a DM delivery test from the shop support bot.", allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden: return await ctx.reply("Discord rejected the test DM; their DMs may be closed or they may block this bot.", mention_author=False)
        except discord.HTTPException: return await ctx.reply("Discord could not deliver the test DM.", mention_author=False)
        await db.audit(ctx.author.id, "dm_test_sent", f"recipient={recipient.id}")
        await ctx.reply("Test DM delivered.", mention_author=False)

    @bot.command(name="dmhistory")
    async def prefix_dmhist(ctx, recipient: discord.User):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("SELECT action,details,created_at FROM audit WHERE details LIKE ? AND action LIKE '%dm%' ORDER BY id DESC LIMIT 10", (f"%recipient={recipient.id}%",)); rows = await cur.fetchall()
        if not rows: return await ctx.reply("No recent DM delivery records found.", mention_author=False)
        await ctx.reply(embed=build_embed(f"DM history · {recipient}", "\n".join(f"`{r['created_at'][:19]}` · `{r['action']}` · {discord.utils.escape_markdown(r['details'][:100])}" for r in rows), kind="security"), mention_author=False)

    @bot.command(name="dmsettings")
    async def prefix_dmsettings(ctx, action: str = "", delay_seconds: int = None):
        if not is_owner(ctx.author, cfg): return await ctx.reply("Owner permission required.", mention_author=False)
        if action:
            if action.lower() != "delay" or delay_seconds is None: return await ctx.reply("Usage: `$dmsettings delay SECONDS` (5–30).", mention_author=False)
            if not 5 <= delay_seconds <= 30: return await ctx.reply("Campaign delay must be between 5 and 30 seconds.", mention_author=False)
            await db.conn.execute("INSERT INTO settings(key,value) VALUES('dm_campaign_delay_seconds',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(delay_seconds),)); await db.conn.commit()
        cur = await db.conn.execute("SELECT COUNT(*) n FROM dm_preferences WHERE promotional_opt_in=1"); opted = (await cur.fetchone())["n"]
        delay = await dm_campaign_delay()
        await ctx.reply(embed=build_embed("DM Manager Settings", f"Promotional opt-ins: **{opted}**\nCampaign delay: **{delay}s per recipient**\nCampaigns require approval and target opted-in customers only."), mention_author=False)

    @bot.command(name="dmoptin")
    async def prefix_dmoptin(ctx, choice: str = "on"):
        choice = choice.lower()
        if choice not in ("on", "off"):
            return await ctx.reply("Use `$dmoptin on` or `$dmoptin off`.", mention_author=False)
        enabled = choice == "on"
        await db.conn.execute("INSERT INTO dm_preferences(user_id,promotional_opt_in,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET promotional_opt_in=excluded.promotional_opt_in,updated_at=excluded.updated_at", (ctx.author.id, int(enabled), db_now()))
        await db.conn.commit()
        await ctx.reply("Promotional shop DMs are **on**. Use `$dmoptin off` anytime." if enabled else "Promotional shop DMs are **off**.", mention_author=False)

    @bot.command(name="dmcampaign_create")
    async def prefix_dmcampaign_create(ctx, *, details: str):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        mode, sep, message = details.partition(" ")
        as_embed = mode.lower() == "embed"
        if not sep: message, as_embed = details, False
        if mode.lower() not in ("text", "embed") and sep:
            message, as_embed = details, False
        if not message.strip() or len(message) > 1500: return await ctx.reply("Campaign message must contain 1–1,500 characters. Add `embed ` first for a branded embed.", mention_author=False)
        cur = await db.conn.execute("INSERT INTO dm_campaigns(guild_id,created_by,audience,message,status,embed_enabled,created_at) VALUES(?,?,?,?,'pending_approval',?,?)", (ctx.guild.id, ctx.author.id, "opted_in_customers", message, int(as_embed), db_now()))
        await db.conn.commit(); campaign_id = cur.lastrowid
        await db.audit(ctx.author.id, "dm_campaign_created", f"campaign={campaign_id}; guild={ctx.guild.id}; chars={len(message)}")
        await ctx.reply(embed=build_embed(f"Campaign #{campaign_id} · awaiting approval", f"Audience: opted-in previous buyers in this server\nFormat: {'branded embed' if as_embed else 'plain text'}\nPreview: {discord.utils.escape_markdown(message[:500])}\nA different owner must run `$dmcampaign_approve {campaign_id}`."), mention_author=False)

    @bot.command(name="dmcampaign_approve")
    async def prefix_dmcampaign_approve(ctx, campaign_id: int):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='approved',approved_by=? WHERE id=? AND guild_id=? AND status='pending_approval' AND created_by<>?", (ctx.author.id, campaign_id, ctx.guild.id, ctx.author.id)); await db.conn.commit()
        if not cur.rowcount: return await ctx.reply("Campaign not found, not pending, or you created it. A different admin must approve it.", mention_author=False)
        await db.audit(ctx.author.id, "dm_campaign_approved", f"campaign={campaign_id}; guild={ctx.guild.id}")
        await ctx.reply(f"Campaign #{campaign_id} approved. Run `$dmcampaign_run {campaign_id}`.", mention_author=False)

    @bot.command(name="dmcampaign_run")
    async def prefix_dmcampaign_run(ctx, campaign_id: int):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='running',started_at=? WHERE id=? AND guild_id=? AND status='approved'", (db_now(), campaign_id, ctx.guild.id)); await db.conn.commit()
        if not cur.rowcount: return await ctx.reply("Campaign must be approved and not previously started.", mention_author=False)
        task = bot.loop.create_task(run_dm_campaign(campaign_id, ctx.guild.id, ctx.author.id))
        bot.dm_campaign_tasks[campaign_id] = task
        task.add_done_callback(lambda _task, cid=campaign_id: bot.dm_campaign_tasks.pop(cid, None))
        await ctx.reply(f"Campaign #{campaign_id} started. Check `$dmcampaign_status {campaign_id}` for progress.", mention_author=False)

    @bot.command(name="dmcampaign_status")
    async def prefix_dmcampaign_status(ctx, campaign_id: int):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("SELECT status,sent_count,failed_count,created_by,approved_by FROM dm_campaigns WHERE id=? AND guild_id=?", (campaign_id, ctx.guild.id)); row = await cur.fetchone()
        if not row: return await ctx.reply("Campaign not found.", mention_author=False)
        approved = f"<@{row['approved_by']}>" if row["approved_by"] else "Pending"
        await ctx.reply(embed=build_embed(f"Campaign #{campaign_id}", f"Status: **{row['status']}**\nDelivered: **{row['sent_count']}**\nFailed: **{row['failed_count']}**\nCreated by: <@{row['created_by']}>\nApproved by: {approved}"), mention_author=False)

    @bot.command(name="dmcampaigns")
    async def prefix_dmcampaigns(ctx):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("SELECT id,status,sent_count,failed_count,created_at FROM dm_campaigns WHERE guild_id=? ORDER BY id DESC LIMIT 10", (ctx.guild.id,)); rows = await cur.fetchall()
        if not rows: return await ctx.reply("No campaigns yet.", mention_author=False)
        body = "\n".join(f"`#{r['id']}` · **{r['status']}** · sent {r['sent_count']} · failed {r['failed_count']} · {r['created_at'][:10]}" for r in rows)
        await ctx.reply(embed=build_embed("Recent DM Campaigns", body), mention_author=False)

    @bot.command(name="dmcampaign_cancel")
    async def prefix_dmcampaign_cancel(ctx, campaign_id: int):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        cur = await db.conn.execute("UPDATE dm_campaigns SET status='cancelled',finished_at=? WHERE id=? AND guild_id=? AND status IN ('pending_approval','approved','running')", (db_now(), campaign_id, ctx.guild.id)); await db.conn.commit()
        if not cur.rowcount: return await ctx.reply("Campaign not found or already finished.", mention_author=False)
        await db.audit(ctx.author.id, "dm_campaign_cancelled", f"campaign={campaign_id}")
        await ctx.reply(f"Campaign #{campaign_id} marked cancelled. It stops after the current delivery.", mention_author=False)

    @bot.command(name="ticketpanel")
    async def prefix_ticket_panel(ctx):
        if not prefix_is_admin(ctx): return await ctx.reply("Administrator permission required.", mention_author=False)
        if not isinstance(ctx.channel, discord.TextChannel): return await ctx.reply("Use this in a text channel.", mention_author=False)
        embed = build_embed(f"© {cfg['shop'].get('name', 'JARVIS SHOP')} | MEMBER TICKETS", "Open a private ticket for purchase questions or support. Please choose the button that best matches your request.")
        embed.add_field(name="🛒 PURCHASE", value="Open a ticket for product availability or purchase help.", inline=False)
        embed.add_field(name="🆘 SUPPORT", value="Open a ticket for an existing order, delivery, or account issue.", inline=False)
        embed.add_field(name="TICKET RULES", value="• One ticket per issue.\n• Include your order ID when relevant.\n• Be patient and respectful with staff.\n• Do not post payment details or product keys publicly.", inline=False)
        embed.set_footer(text=f"© {cfg['shop'].get('name', 'JARVIS SHOP')} · Private support")
        await ctx.channel.send(embed=embed, view=SupportPanelView(open_ticket_button))
        await db.audit(ctx.author.id, "ticket_panel_posted_prefix", f"guild={ctx.guild.id}; channel={ctx.channel.id}")
        await ctx.reply("Support panel posted.", mention_author=False)

    @bot.command(name="autobuypanel", aliases=["buypanel"])
    async def prefix_autobuy_panel(ctx):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.reply("Use this in a server text channel.", mention_author=False)
        store_url = str(cfg.get("sellauth", {}).get("store_url", "")).strip()
        if not store_url.startswith("https://"):
            return await ctx.reply("Set SELLAUTH_STORE_URL in your local .env to your HTTPS SellAuth storefront first.", mention_author=False)
        shop_name = cfg.get("shop", {}).get("name", "JARVIS SHOP")
        embed = discord.Embed(
            title=f"{shop_name} | INSTANT DIGITAL DELIVERY",
            description="Browse the official store and complete secure checkout. SellAuth confirms payment and delivers the digital items configured for each product.",
            colour=0xB32936,
        )
        embed.add_field(name="🛒 AUTO BUY", value="Select Browse & Buy to view products and pay through the official checkout. Your digital delivery appears after payment is confirmed.", inline=False)
        embed.add_field(name="🎫 SUPPORT", value="If checkout or delivery needs help, open a private support ticket with the button below.", inline=False)
        embed.add_field(name="ORDER RULES", value="• Pay only through the linked SellAuth checkout.\n• Never share a checkout receipt or delivered key publicly.\n• If a payment is still confirming, wait for SellAuth to finish processing it.\n• Open a support ticket if delivery does not appear.", inline=False)
        embed.set_footer(text=f"© {shop_name} · Secure checkout · Automatic digital delivery")
        banner = str(cfg.get("sellauth", {}).get("panel_banner_url", "")).strip()
        logo = str(cfg.get("sellauth", {}).get("panel_logo_url", "")).strip()
        if banner.startswith("https://"):
            embed.set_image(url=banner)
        if logo.startswith("https://"):
            embed.set_thumbnail(url=logo)
        await ctx.channel.send(embed=embed, view=AutoBuyPanelView(open_ticket_button, store_url))
        await db.audit(ctx.author.id, "autobuy_panel_posted", f"guild={ctx.guild.id}; channel={ctx.channel.id}")
        await ctx.reply("Auto-buy panel posted.", mention_author=False)

    @bot.command(name="ticket")
    async def prefix_ticket(ctx, *, subject: str = "Support request"):
        if not ctx.guild: return await ctx.reply("Open support tickets from the shop server.", mention_author=False)
        try: channel, created = await create_ticket_channel(ctx.guild, ctx.author, "questions", subject)
        except discord.Forbidden: return await ctx.reply("The bot needs Manage Channels and access to the support category.", mention_author=False)
        await ctx.reply(f"Your ticket is {channel.mention}." if created else f"You already have an open ticket: {channel.mention}", mention_author=False)

    @bot.command(name="ticketclaim")
    async def prefix_ticket_claim(ctx):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        cur = await db.conn.execute("UPDATE tickets SET assigned_to=? WHERE channel_id=? AND status='open' AND (assigned_to IS NULL OR assigned_to=?)", (ctx.author.id, ctx.channel.id, ctx.author.id))
        await db.conn.commit()
        if not cur.rowcount: return await ctx.reply("This ticket is closed, not recognized, or assigned to another staff member.", mention_author=False)
        await db.audit(ctx.author.id, "ticket_claimed_prefix", f"channel={ctx.channel.id}")
        await ctx.reply(f"Ticket claimed by {ctx.author.mention}.", mention_author=False)

    @bot.command(name="ticketclose")
    async def prefix_ticket_close(ctx, *, reason: str = "Resolved"):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        cur = await db.conn.execute("SELECT id,user_id FROM tickets WHERE channel_id=? AND status='open'", (ctx.channel.id,))
        row = await cur.fetchone()
        if not row: return await ctx.reply("This channel isn't an open JARVIS ticket.", mention_author=False)
        await db.conn.execute("UPDATE tickets SET status='closed',closed_at=? WHERE id=?", (db_now(), row["id"]))
        await db.conn.commit()
        member = ctx.guild.get_member(row["user_id"])
        if member:
            overwrite = ctx.channel.overwrites_for(member); overwrite.send_messages = False
            await ctx.channel.set_permissions(member, overwrite=overwrite, reason=f"Ticket closed by {ctx.author}")
        try: await ctx.channel.edit(name=f"closed-{row['id']:04d}")
        except discord.HTTPException: pass
        await db.audit(ctx.author.id, "ticket_closed_prefix", f"ticket={row['id']}; reason={reason[:200]}")
        await ctx.reply(f"Ticket #{row['id']} closed and archived. Reason: {discord.utils.escape_markdown(reason[:200])}", mention_author=False)

    @bot.command(name="ticketreopen")
    async def prefix_ticket_reopen(ctx, ticket_id: int):
        if not prefix_is_staff(ctx): return await ctx.reply("Staff permission required.", mention_author=False)
        cur = await db.conn.execute("SELECT * FROM tickets WHERE id=? AND status='closed'", (ticket_id,))
        row = await cur.fetchone()
        channel = ctx.guild.get_channel(row["channel_id"]) if row and ctx.guild else None
        if not row or not channel: return await ctx.reply("Closed ticket or archived channel not found.", mention_author=False)
        member = ctx.guild.get_member(row["user_id"])
        if member:
            overwrite = channel.overwrites_for(member); overwrite.send_messages = True
            await channel.set_permissions(member, overwrite=overwrite, reason=f"Ticket reopened by {ctx.author}")
        await db.conn.execute("UPDATE tickets SET status='open',closed_at=NULL WHERE id=? AND status='closed'", (ticket_id,))
        await db.conn.commit()
        try: await channel.edit(name=f"ticket-{ticket_id:04d}-reopened")
        except discord.HTTPException: pass
        await db.audit(ctx.author.id, "ticket_reopened_prefix", f"ticket={ticket_id}")
        await ctx.reply(f"Ticket reopened in {channel.mention}.", mention_author=False)

    @bot.command(name="backup")
    async def prefix_backup(ctx, action: str = "list", *, filename: str = ""):
        if not is_owner(ctx.author, cfg): return await ctx.reply("Owner permission required.", mention_author=False)
        action = action.lower()
        if action == "create":
            try: created = await db.create_backup(backup_dir)
            except Exception:
                log.exception("Database backup failed")
                return await ctx.reply("Backup failed. Check the bot log for details.", mention_author=False)
            await db.audit(ctx.author.id, "backup_created_prefix", created)
            return await ctx.reply(f"Backup created: `{created}`. Verify it with `$backup verify {created}`.", mention_author=False)
        if action == "verify":
            if not filename: return await ctx.reply("Usage: `$backup verify FILENAME`", mention_author=False)
            try: valid, result = db.verify_backup(backup_dir, filename)
            except ValueError as exc: return await ctx.reply(str(exc), mention_author=False)
            await db.audit(ctx.author.id, "backup_verified_prefix", f"file={filename}; valid={valid}")
            return await ctx.reply(f"Backup `{filename}` is **{'valid' if valid else 'invalid'}** · `{result}`", mention_author=False)
        if action != "list": return await ctx.reply("Usage: `$backup [list|create|verify FILENAME]`", mention_author=False)
        rows = db.list_backups(backup_dir)
        if not rows: return await ctx.reply("No local database backups found.", mention_author=False)
        await ctx.reply("**Local backups**\n" + "\n".join(f"`{name}` · {size:,} bytes" for name, size, _ in rows[:20]), mention_author=False)

    @bot.command(name="addproduct", aliases=["newproduct"])
    async def prefix_addproduct(ctx, *, details: str):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        parts = [x.strip() for x in details.split("|", 3)]
        if len(parts) != 4:
            return await ctx.reply("Format: `$addproduct Name | price_in_paise | stock (-1 unlimited) | description`", mention_author=False)
        name, price_text, stock_text, description = parts
        try: price, stock = int(price_text), int(stock_text)
        except ValueError: return await ctx.reply("Price and stock must be whole numbers. Example: `$addproduct Nitro | 19900 | 10 | One month Nitro`", mention_author=False)
        if price < 0 or stock < -1:
            return await ctx.reply("Price must be non-negative and stock must be -1 or greater.", mention_author=False)
        product_id = await db.add_product(name[:100], description[:1000], "General", price, stock, "")
        await db.audit(ctx.author.id, "product_add_prefix", f"id={product_id}; name={name}")
        await ctx.reply(f"Created product **#{product_id} {discord.utils.escape_markdown(name)}** · {money(price,cfg)}", mention_author=False)

    @bot.command(name="stock")
    async def prefix_stock(ctx, product_id: int, change: int):
        if not prefix_is_admin(ctx):
            return await ctx.reply("Administrator permission required.", mention_author=False)
        if change == 0:
            return await ctx.reply("Change must be non-zero.", mention_author=False)
        try:
            stock = await db.adjust_stock(product_id, change)
        except ValueError as exc:
            return await ctx.reply(str(exc), mention_author=False)
        await db.audit(ctx.author.id, "stock_adjust_prefix", f"product={product_id}; change={change}; stock={stock}")
        await ctx.reply(f"Stock for product `#{product_id}` is now **{stock}**.", mention_author=False)

    @bot.event
    async def on_command_completion(ctx):
        """Give a quiet, visible success signal after every prefix command."""
        try:
            await ctx.message.add_reaction("✅")
        except (discord.Forbidden, discord.HTTPException):
            # The command result still appears; this only means Discord blocked
            # the optional acknowledgement reaction in that channel.
            pass

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            try:
                await ctx.reply(f"I couldn't find that command. Run `{ctx.prefix}help` to see the command list.", mention_author=False)
                await ctx.message.add_reaction("❓")
            except discord.HTTPException:
                pass
            return
        if isinstance(error, commands.MissingRequiredArgument):
            message = await ctx.reply(f"I need `{error.param.name}` to run that. Use `{ctx.prefix}help` to see the syntax.", mention_author=False)
            try: await ctx.message.add_reaction("❌")
            except discord.HTTPException: pass
            return message
        if isinstance(error, commands.BadArgument):
            message = await ctx.reply(f"I couldn't understand that argument. Use `{ctx.prefix}help` to see the syntax.", mention_author=False)
            try: await ctx.message.add_reaction("❌")
            except discord.HTTPException: pass
            return message
        if isinstance(error, commands.CommandOnCooldown):
            message = await ctx.reply(f"That command is still cooling down. Try again in {error.retry_after:.1f}s.", mention_author=False)
            try: await ctx.message.add_reaction("⏳")
            except discord.HTTPException: pass
            return message
        if isinstance(error, commands.MissingPermissions):
            message = await ctx.reply("I couldn't run that because you don't have permission to use it.", mention_author=False)
            try: await ctx.message.add_reaction("❌")
            except discord.HTTPException: pass
            return message
        if isinstance(error, commands.CheckFailure):
            message = await ctx.reply(f"I couldn't run that because you don't have permission. Run `{ctx.prefix}help` to see which commands you can use.", mention_author=False)
            try: await ctx.message.add_reaction("❌")
            except discord.HTTPException: pass
            return message
        log.exception("Prefix command failed", exc_info=error)
        try:
            await ctx.reply("I tried to run that, but hit an error. Check the bot log or ask an admin for help.", mention_author=False)
            await ctx.message.add_reaction("❌")
        except discord.HTTPException: pass

    # Carry every legacy application-command feature into the prefix interface,
    # then leave the local Discord application-command tree empty.
    legacy_commands = list(bot.tree.get_commands())
    prefix_equivalents = {
        "cart_add": "addcart", "cart_remove": "cartremove", "cart_clear": "cartclear",
        "payment_submit": "payment", "order_cancel": "cancelorder",
        "orders_pending": "orderspending", "payment_verify": "paymentverify",
        "ticket_panel": "ticketpanel", "ticket_close": "ticketclose",
        "ticket_claim": "ticketclaim", "ticket_reopen": "ticketreopen",
        "dm_user": "dm", "dm_order": "dmorder", "dm_test": "dmtest",
        "dm_optin": "dmoptin", "dm_history": "dmhistory", "dm_settings": "dmsettings",
        "dm_campaign_create": "dmcampaign_create", "dm_campaign_approve": "dmcampaign_approve",
        "dm_campaign_run": "dmcampaign_run", "dm_campaign_status": "dmcampaign_status",
        "dm_campaigns": "dmcampaigns", "dm_campaign_cancel": "dmcampaign_cancel",
        "help_shop": "help", "verify_link": "verify", "verify_panel": "verifypanel",
    }

    class PrefixResponse:
        def __init__(self, ctx):
            self.ctx = ctx
            self.message = None

        async def send_message(self, content=None, **kwargs):
            private = kwargs.pop("ephemeral", False)
            kwargs.pop("silent", None)
            if private:
                kwargs.pop("mention_author", None)
                try:
                    self.message = await self.ctx.author.send(content=content, **kwargs)
                    try: await self.ctx.reply("I sent the private result to your DMs.", mention_author=False)
                    except discord.HTTPException: pass
                    return self.message
                except discord.Forbidden:
                    return await self.ctx.reply("I couldn't DM you. Enable server DMs and try again.", mention_author=False)
            self.message = await self.ctx.reply(content=content, mention_author=False, **kwargs)
            return self.message

        async def defer(self, **kwargs):
            return None

    class PrefixFollowup:
        def __init__(self, response): self.response = response
        async def send(self, content=None, **kwargs):
            # Reuse the response adapter so slash-style private replies stay private.
            return await self.response.send_message(content, **kwargs)

    class PrefixInteraction:
        def __init__(self, ctx):
            self.user = ctx.author
            self.guild = ctx.guild
            self.guild_id = ctx.guild.id if ctx.guild else None
            self.channel = ctx.channel
            self.channel_id = ctx.channel.id
            self.client = bot
            self.response = PrefixResponse(ctx)
            self.followup = PrefixFollowup(self.response)
        async def original_response(self):
            return self.response.message or self.channel

    async def parse_legacy_arguments(ctx, app_command, raw):
        callback = app_command.callback
        signature = inspect.signature(callback)
        parameters = list(signature.parameters.values())[1:]
        if not parameters:
            if raw.strip(): raise ValueError("This command takes no arguments.")
            return {}
        tokens = shlex.split(raw)
        kwargs = {}
        hints = typing.get_type_hints(callback, include_extras=True)

        async def parse_value(parameter, value):
            annotation = hints.get(parameter.name, parameter.annotation)
            origin = typing.get_origin(annotation)
            args = typing.get_args(annotation)
            if origin is typing.Annotated:
                annotation = args[0] if args else str
                origin = typing.get_origin(annotation)
            if origin is typing.Union and type(None) in args:
                annotation = next((arg for arg in args if arg is not type(None)), str)
                origin = typing.get_origin(annotation)
            if origin is app_commands.Choice or annotation is app_commands.Choice:
                return app_commands.Choice(name=value, value=value)
            if annotation is bool:
                lowered = value.lower()
                if lowered not in {"true", "false", "yes", "no", "on", "off", "1", "0"}:
                    raise ValueError(f"`{parameter.name}` must be true or false.")
                return lowered in {"true", "yes", "on", "1"}
            if annotation is int or (isinstance(annotation, type) and issubclass(annotation, int)):
                try: return int(value)
                except ValueError as exc: raise ValueError(f"`{parameter.name}` must be a whole number.") from exc
            if annotation is float:
                try: return float(value)
                except ValueError as exc: raise ValueError(f"`{parameter.name}` must be a number.") from exc
            if annotation is discord.TextChannel:
                try: return await commands.TextChannelConverter().convert(ctx, value)
                except commands.BadArgument as exc: raise ValueError(f"Couldn't find text channel `{value}` in this server.") from exc
            if annotation is discord.User:
                try: return await commands.UserConverter().convert(ctx, value)
                except commands.BadArgument as exc: raise ValueError(f"Couldn't find Discord user `{value}`.") from exc
            if annotation is discord.Member:
                try: return await commands.MemberConverter().convert(ctx, value)
                except commands.BadArgument as exc: raise ValueError(f"Couldn't find server member `{value}`.") from exc
            return value

        for index, parameter in enumerate(parameters):
            app_parameter = next((item for item in app_command.parameters if item.name == parameter.name), None)
            required = app_parameter.required if app_parameter else parameter.default is inspect.Parameter.empty
            if not tokens:
                if required: raise ValueError(f"Missing `{parameter.name}`. Use `{ctx.prefix}help` for the full command list.")
                if parameter.default is not inspect.Parameter.empty:
                    kwargs[parameter.name] = parameter.default
                continue
            annotation = hints.get(parameter.name, parameter.annotation)
            is_string = annotation is str or annotation is inspect.Parameter.empty
            take_rest = is_string and index == len(parameters) - 1
            # A final boolean flag can follow an unquoted message, e.g. "hello there true".
            if is_string and index == len(parameters) - 2 and parameters[-1].annotation is bool:
                if tokens[-1].lower() in {"true", "false", "yes", "no", "on", "off", "1", "0"} and len(tokens) > 1:
                    value, bool_value = " ".join(tokens[:-1]), tokens[-1]
                    kwargs[parameters[-1].name] = await parse_value(parameters[-1], bool_value)
                else:
                    value = " ".join(tokens)
                tokens = []
                kwargs[parameter.name] = await parse_value(parameter, value)
                break
            value = " ".join(tokens) if take_rest else tokens.pop(0)
            if take_rest: tokens.clear()
            kwargs[parameter.name] = await parse_value(parameter, value)
        if tokens:
            raise ValueError("Too many arguments. Put quotes around multi-word values and check the command syntax in help.")
        return kwargs

    for app_command in legacy_commands:
        existing = bot.get_command(app_command.name)
        if existing:
            continue
        equivalent = prefix_equivalents.get(app_command.name)
        if equivalent and bot.get_command(equivalent):
            if app_command.name not in bot.all_commands:
                target = bot.get_command(equivalent)
                target.aliases.append(app_command.name)
                bot.all_commands[app_command.name] = target
            continue

        async def legacy_prefix_callback(ctx, *, arguments="", _app_command=app_command):
            try:
                values = await parse_legacy_arguments(ctx, _app_command, arguments)
                result = _app_command.callback(PrefixInteraction(ctx), **values)
                return await result if inspect.isawaitable(result) else result
            except (TypeError, ValueError, commands.BadArgument) as exc:
                return await ctx.reply(f"{exc} Use `{ctx.prefix}help` for the command syntax.", mention_author=False)

        usage = " ".join((f"<{p.name}>" if p.required else f"[{p.name}]") for p in app_command.parameters)
        legacy_prefix_callback.__name__ = f"prefix_legacy_{app_command.name}"
        bridged = commands.Command(legacy_prefix_callback, name=app_command.name,
                                   help=(app_command.description or "Prefix command migrated from the previous build.") + " Put quotes around any argument containing spaces.",
                                   usage=usage)
        bot.add_command(bridged)

    # Short aliases keep the existing canonical commands and syntax working,
    # while giving every frequently used feature a quick-to-type form.
    simple_aliases = {
        "help": ("h",), "ping": ("p",), "shop": ("s",), "search": ("find",), "catalog_search": ("filter",),
        "addcart": ("add",), "cart": ("bag",), "cartremove": ("rmcart",), "cartclear": ("emptycart",),
        "wishlist": ("wish",), "product": ("prod",), "checkout": ("buy",), "payment": ("payref",),
        "order": ("track",), "cancelorder": ("cancel",), "orderspending": ("pending",),
        "paymentverify": ("approvepay",), "deliver": ("ship",), "verify": ("v",),
        "verifypanel": ("vpanel",), "updates": ("up",), "serverinfo": ("si",),
        "userinfo": ("ui",), "avatar": ("av",), "poll": ("vote",), "suggest": ("idea",), "ai_help": ("ai",),
        "clear": ("clean",), "slowmode": ("sm",), "lock": ("lk",), "unlock": ("ul",),
        "announce": ("ann",), "say": ("echo",), "ticket": ("tk",),
        "ticketpanel": ("tpanel",), "ticketclaim": ("tclaim",), "ticketclose": ("tclose",),
        "ticketreopen": ("treopen",), "autobuypanel": ("buyembed",), "backup": ("bkup",),
        "backup_create": ("bcreate",), "backup_list": ("blist",), "backup_verify": ("bverify",),
        "product_add": ("padd",), "product_remove": ("pdel",), "product_edit": ("pedit",),
        "product_duplicate": ("pdup",), "product_info": ("pinfo",), "stock_adjust": ("stockset",),
        "coupon_create": ("coupon",), "refund_record": ("refund",), "analytics": ("stats",),
        "owner_status": ("owner",), "store_health": ("health",), "server_setup": ("setupserver",),
        "server_clone": ("clone",), "serversnapshot": ("snap",), "recoverypanel": ("recover",),
        "pull": ("restore",), "dashboard": ("dash",), "verify_stats": ("vstats",), "verify_config": ("vconfig",),
        "growth_invite": ("invite",), "staff_report": ("report",), "dmorder": ("dmo",), "dmtest": ("dmtest",),
        "dmhistory": ("dmhist",), "dmsettings": ("dmset",), "dmoptin": ("dmopt",),
        "dmcampaign_create": ("campnew",), "dmcampaign_approve": ("campapprove",),
        "dmcampaign_run": ("camprun",), "dmcampaign_status": ("campstatus",),
        "dmcampaigns": ("camplist",), "dmcampaign_cancel": ("campcancel",),
        "announce_updates": ("upannounce",), "updates_join": ("upjoin",), "updates_leave": ("upleave",),
    }
    for command_name, aliases in simple_aliases.items():
        command = bot.get_command(command_name)
        if not command:
            continue
        for alias in aliases:
            if alias not in bot.all_commands:
                command.aliases.append(alias)
                bot.all_commands[alias] = command

    bot.tree.clear_commands(guild=None)
    return bot
