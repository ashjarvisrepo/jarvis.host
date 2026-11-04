"""Data-driven command directory for prefix commands."""
import discord


CATEGORIES = {
    "Shop & Cart": {"shop", "store", "catalog", "catalog_search", "search", "find", "cart", "addcart", "cartadd", "cart_add", "checkout", "cart_remove", "cart_clear", "wishlist"},
    "Products & Inventory": {"product_add", "product_remove", "product_edit", "product_duplicate", "product_info", "addproduct", "newproduct", "stock_adjust", "stock"},
    "Orders & Payments": {"order", "orders_pending", "orderspending", "payment", "payment_submit", "paymentverify", "payment_verify", "deliver", "refund_record", "coupon_create", "order_cancel"},
    "Support & Staff": {"ticket", "ticket_close", "ticket_claim", "ticket_reopen", "ticket_panel", "ticketpanel", "ticketclaim", "ticketclose", "ticketreopen", "staff_report"},
    "DM Manager & Campaigns": {"dm_user", "dm_order", "dm", "dmorder", "dmtest", "dm_test", "dm_history", "dmhistory", "dm_settings", "dmsettings", "dm_optin", "dmoptin", "dm_campaign_create", "dm_campaign_approve", "dm_campaign_run", "dm_campaign_status", "dm_campaigns", "dm_campaign_cancel", "dmcampaign_create", "dmcampaign_approve", "dmcampaign_run", "dmcampaign_status", "dmcampaigns", "dmcampaign_cancel"},
    "Backups": {"backup_create", "backup_list", "backup_verify", "backup"},
    "Community & Moderation": {"updates", "updates_join", "updates_leave", "announce_updates", "poll", "suggest", "suggestion", "clear", "purge", "slowmode", "lock", "unlock", "announce", "say"},
    "Verification & Servers": {"verify", "verifypanel", "verify_link", "verify_stats", "verify_config", "verify_panel", "growth_invite", "server_setup", "server_clone", "serversnapshot", "recoverypanel", "memberrestore", "pull", "dashboard"},
    "Analytics & Owner": {"analytics", "store_health", "owner_status"},
    "General": {"help", "commands", "menu", "ai_help", "ping", "serverinfo", "server", "userinfo", "whois", "avatar", "pfp"},
}

ACCESS = {
    **{name: "Staff" for name in ("orders_pending", "orderspending", "payment_verify", "paymentverify", "deliver", "ticket_close", "ticket_claim", "ticket_reopen", "ticketclose", "ticketclaim", "ticketreopen", "staff_report", "clear", "purge")},
    **{name: "Admin" for name in ("slowmode", "lock", "unlock", "announce", "say", "ticket_panel", "ticketpanel", "autobuypanel", "refund_record", "analytics", "announce_updates")},
    **{name: "Owner" for name in (
        "owner_status", "store_health", "verify", "verify_link", "verify_config", "verify_stats", "verify_panel", "verifypanel", "growth_invite", "server_setup", "server_clone", "serversnapshot", "recoverypanel", "memberrestore", "pull", "dashboard",
        "product_add", "product_remove", "product_edit", "product_duplicate", "stock_adjust", "addproduct", "newproduct", "stock", "coupon_create",
        "dm_user", "dm_order", "dm_test", "dm_history", "dm_settings", "dm_campaign_create", "dm_campaign_approve", "dm_campaign_run", "dm_campaign_status", "dm_campaigns", "dm_campaign_cancel",
        "dm", "dmorder", "dmtest", "dmhistory", "dmsettings", "dmcampaign_create", "dmcampaign_approve", "dmcampaign_run", "dmcampaign_status", "dmcampaigns", "dmcampaign_cancel",
        "backup_create", "backup_list", "backup_verify", "backup"
    )},
}

PREFIX_DESCRIPTIONS = {
    "help": "Show the command groups available to your configured role. Example: $help.",
    "ping": "Check gateway latency. Example: $ping.",
    "shop": "Browse active products and stock. Example: $shop.",
    "search": "Search product names and descriptions. Example: $search nitro.",
    "addcart": "Add a product to your cart. Example: $addcart 3 2.",
    "cart": "Review your cart total. Example: $cart.",
    "checkout": "Create an order; optionally apply a coupon. Example: $checkout SAVE10.",
    "order": "View your own order. Example: $order JX-ABC12345.",
    "verify": "Open the configured opt-in Discord verification page. Example: $verify main.",
    "serversnapshot": "Save, list, or additively restore a structure snapshot; optionally restore from another server ID. Example: $serversnapshot restore launch 123456789012345678.",
    "recoverypanel": "Post an opt-in member rejoin panel using Discord OAuth consent. Example: $recoverypanel #verify-here main.",
    "pull": "Quick: $pull start <new_server_id> <role_id> pulls opted-in members from configured main. Controls: $pull status|pause|resume|stop. Advanced: $pull plan <source_id> <destination_key> [member_id]; $pull one <source_id> <destination_key> <member_id>; $pull settings. Requires member recovery opt-in.",
    "dashboard": "Open the private JARVIS Pull dashboard. On Railway, sign in with an allowed Discord owner or co-owner account. Example: $dashboard.",
    "updates": "Opt into or out of community updates. Example: $updates join.",
    "serverinfo": "Show public information about this server. Example: $serverinfo.",
    "userinfo": "Show public information about a member. Example: $userinfo @member.",
    "avatar": "Show a member's avatar. Example: $avatar @member.",
    "poll": "Create a reaction poll. Example: $poll Best game? | A | B.",
    "suggest": "Send an idea to the configured suggestions channel. Example: $suggest Add a game night.",
    "clear": "Delete 1–100 recent messages (staff). Example: $clear 10.",
    "slowmode": "Set channel slowmode in seconds (admin). Example: $slowmode 5.",
    "lock": "Block @everyone from sending messages in this channel (admin). Example: $lock.",
    "unlock": "Restore @everyone message sending in this channel (admin). Example: $unlock.",
    "announce": "Post an admin announcement embed. Example: $announce Maintenance at 8 PM.",
    "say": "Echo text without an embed or extra text (admin). Example: $say Store opens at noon.",
    "dm": "Send one customer DM (owner); message content is not stored in audit logs. Example: $dm @member Your order is ready.",
    "addproduct": "Create a product (owner). Example: $addproduct Nitro | 19900 | 5 | One month.",
    "stock": "Adjust finite product stock (owner). Example: $stock 3 5.",
    "product": "View product details. Example: $product 3.",
    "cartremove": "Remove a product from your cart. Example: $cartremove 3.",
    "cartclear": "Empty your cart. Example: $cartclear.",
    "wishlist": "View or manage your personal wishlist. Example: $wishlist add 3.",
    "cancelorder": "Cancel your own unpaid order and return finite stock. Example: $cancelorder JX-ABC12345.",
    "ticket": "Open a private support ticket. Example: $ticket My order is delayed.",
    "ticketpanel": "Post the HELP/PURCHASE/QUESTIONS panel. Example: $ticketpanel.",
    "ticketclaim": "Claim the open ticket in this channel. Example: $ticketclaim.",
    "ticketclose": "Close and archive this channel's ticket. Example: $ticketclose Resolved.",
    "ticketreopen": "Reopen an archived ticket. Example: $ticketreopen 12.",
    "dmtest": "Send a one time test DM and report whether Discord accepts it (owner). Example: $dmtest @member.",
    "dmhistory": "Review recent DM delivery metadata (owner). Message bodies are never logged. Example: $dmhistory @member.",
    "dmsettings": "Show opt-in count and campaign delay (owner). Example: $dmsettings.",
    "dmoptin": "Choose whether to receive promotional shop DMs. Example: $dmoptin off.",
    "dmcampaign_create": "Draft an opt-in customer DM campaign for owner approval. Start with `embed ` for a branded embed. Example: $dmcampaign_create New stock is here.",
    "dmcampaign_approve": "Approve another owner's pending campaign. Example: $dmcampaign_approve 12.",
    "dmcampaign_run": "Start an approved campaign (owner). Example: $dmcampaign_run 12.",
    "dmcampaign_status": "View campaign progress (owner). Example: $dmcampaign_status 12.",
    "dmcampaigns": "List recent campaign reports (owner). Example: $dmcampaigns.",
    "dmcampaign_cancel": "Cancel a pending, approved, or active campaign (owner). Example: $dmcampaign_cancel 12.",
    "payment": "Submit a transaction reference for your unpaid order. Example: $payment JX-ABC12345 BANK-REF-987.",
    "orderspending": "List payment references waiting for staff review. Example: $orderspending.",
    "paymentverify": "Mark a submitted payment as verified after checking it. Example: $paymentverify JX-ABC12345.",
    "deliver": "Mark a paid order delivered. Example: $deliver JX-ABC12345 Sent to customer.",
    "verifypanel": "Post a verification panel in this channel (owner). Configure the verification URL and destination first. Example: $verifypanel main.",
    "autobuypanel": "Post the SellAuth automatic checkout panel with purchase and support buttons (admin). Example: $autobuypanel.",
}


def _category(name):
    for category, names in CATEGORIES.items():
        if name in names:
            return category
    return "General"


def _namespace_access(access, namespace, viewer, cfg):
    from core.permissions import is_owner, is_admin, is_staff
    if namespace == "owner":
        return access == "Owner" and is_owner(viewer, cfg)
    if namespace == "staff":
        return (access == "Staff" and is_staff(viewer, cfg)) or (access == "Admin" and is_admin(viewer, cfg))
    if namespace == "member":
        return access == "Public"
    return access == "Public" or (access == "Staff" and is_staff(viewer, cfg)) or (access == "Admin" and is_admin(viewer, cfg)) or (access == "Owner" and is_owner(viewer, cfg))


def command_pages(bot, viewer=None, cfg=None, namespace=None):
    grouped = {category: [] for category in CATEGORIES}
    for command in sorted(bot.commands, key=lambda c: c.name):
        if command.hidden:
            continue
        access = ACCESS.get(command.name, "Public")
        if command.name == "help":
            allowed = True
        elif viewer is not None and cfg is not None:
            allowed = _namespace_access(access, namespace, viewer, cfg)
        elif namespace is not None:
            allowed = (namespace == "owner" and access == "Owner") or (namespace == "staff" and access in ("Staff", "Admin")) or (namespace == "member" and access == "Public")
        else:
            allowed = True
        if not allowed:
            continue
        desc = (PREFIX_DESCRIPTIONS.get(command.name) or command.help or command.short_doc or "No description provided.").replace("\n", " ")
        desc = desc.split("Example:", 1)[0].strip().rstrip(". ")
        if command.name == "pull":
            desc = "Start and control recovery pulls for members who opted in."
        elif command.name == "serversnapshot":
            desc = "Create, list, and restore server structure snapshots."
        name = f"{command.name}{(' · ' + ', '.join(command.aliases)) if command.aliases else ''}"
        grouped[_category(command.name)].append((name, desc, access))
    return {name: entries for name, entries in grouped.items() if entries}


def command_list_embeds(bot, prefixes, viewer, cfg):
    """Show only the command groups the current user is allowed to use."""
    lanes = (
        ("member", "MEMBER COMMANDS", "Public"),
        ("staff", "STAFF & ADMIN COMMANDS", "Staff and Admin"),
        ("owner", "OWNER COMMANDS", "Owner"),
    )
    from core.permissions import is_owner, is_staff
    if is_owner(viewer, cfg):
        visible_lanes = {"member", "staff", "owner"}
    elif is_staff(viewer, cfg):
        visible_lanes = {"member", "staff"}
    else:
        visible_lanes = {"member"}
    embeds = []
    for namespace, title, access_label in lanes:
        if namespace not in visible_lanes:
            continue
        grouped = command_pages(bot, viewer=viewer, cfg=cfg, namespace=namespace)
        embed = discord.Embed(
            title=f"JARVIS Command List · {title}",
            description="Commands you can use, grouped by category. Syntax appears only when a command needs correction.",
            colour=0x7565D9,
        )
        for category, entries in grouped.items():
            lines = [f"**{name}** — {description}" if description else f"**{name}**" for name, description, _access in entries]
            chunks, current = [], ""
            for line in lines:
                if current and len(current) + len(line) + 1 > 950:
                    chunks.append(current); current = ""
                current = (current + "\n" if current else "") + line
            if current:
                chunks.append(current)
            for index, chunk in enumerate(chunks):
                embed.add_field(name=category if index == 0 else f"{category} · more", value=chunk, inline=True)
        embed.set_footer(text=f"Access: {access_label}")
        embeds.append(embed)
    return embeds


