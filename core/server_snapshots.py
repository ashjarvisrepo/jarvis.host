"""Consent-safe, additive Discord server structure snapshots."""
import json
import re
from pathlib import Path

import discord


def _snapshot_dir():
    path = Path(__file__).resolve().parent.parent / "backups" / "server_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(value):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_")
    return value[:48] or "snapshot"


def capture(guild, name):
    roles = [r for r in sorted(guild.roles, key=lambda x: x.position) if not r.is_default() and not r.managed]
    role_names = {r.id: r.name for r in roles}

    def overwrites(channel):
        saved = []
        for target, overwrite in channel.overwrites.items():
            # Member-specific overwrites can contain personal access decisions; keep role overwrites only.
            if isinstance(target, discord.Role):
                saved.append({"role": "@everyone" if target.is_default() else target.name,
                              "allow": overwrite.pair()[0].value, "deny": overwrite.pair()[1].value})
        return saved

    channels = []
    for channel in sorted(guild.channels, key=lambda x: (x.position, x.name)):
        item = {"name": channel.name, "position": channel.position, "overwrites": overwrites(channel)}
        if isinstance(channel, discord.CategoryChannel):
            item["type"] = "category"
        elif isinstance(channel, discord.TextChannel):
            item.update(type="text", category=channel.category.name if channel.category else None,
                        topic=channel.topic, nsfw=channel.nsfw, slowmode=channel.slowmode_delay)
        elif isinstance(channel, discord.VoiceChannel):
            item.update(type="voice", category=channel.category.name if channel.category else None,
                        bitrate=channel.bitrate, user_limit=channel.user_limit)
        else:
            continue
        channels.append(item)
    return {"format": 1, "guild_id": guild.id, "guild_name": guild.name, "name": name,
            "roles": [{"name": r.name, "permissions": r.permissions.value, "colour": r.colour.value,
                       "hoist": r.hoist, "mentionable": r.mentionable, "position": r.position}
                      for r in roles], "channels": channels}


def save(snapshot):
    path = _snapshot_dir() / f"{snapshot['guild_id']}-{_slug(snapshot['name'])}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_snapshots(guild_id):
    result = []
    for path in _snapshot_dir().glob(f"{int(guild_id)}-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append((data.get("name", path.stem), path))
        except (OSError, ValueError):
            continue
    return sorted(result)


def load(guild_id, name):
    wanted = _slug(name)
    path = _snapshot_dir() / f"{int(guild_id)}-{wanted}.json"
    if not path.exists():
        raise FileNotFoundError(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != 1:
        raise ValueError("Unsupported snapshot format")
    return data


async def restore(guild, snapshot):
    role_map = {"@everyone": guild.default_role}
    made_roles = made_channels = skipped = 0
    for item in sorted(snapshot["roles"], key=lambda x: x.get("position", 0)):
        existing = discord.utils.get(guild.roles, name=item["name"])
        if existing:
            role_map[item["name"]] = existing
            continue
        try:
            role = await guild.create_role(name=item["name"][:100], permissions=discord.Permissions(item["permissions"]),
                colour=discord.Colour(item["colour"]), hoist=item["hoist"], mentionable=item["mentionable"],
                reason="JARVIS additive server snapshot restore")
            role_map[item["name"]] = role
            made_roles += 1
        except discord.HTTPException:
            skipped += 1

    def make_overwrites(items):
        result = {}
        for item in items:
            role = role_map.get(item["role"])
            if role:
                result[role] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(item["allow"]), discord.Permissions(item["deny"]))
        return result

    category_map = {}
    for item in (x for x in snapshot["channels"] if x["type"] == "category"):
        existing = discord.utils.get(guild.categories, name=item["name"])
        if existing:
            category_map[item["name"]] = existing
            continue
        try:
            category_map[item["name"]] = await guild.create_category(item["name"][:100],
                overwrites=make_overwrites(item["overwrites"]), reason="JARVIS additive server snapshot restore")
            made_channels += 1
        except discord.HTTPException:
            skipped += 1

    for item in (x for x in snapshot["channels"] if x["type"] != "category"):
        category = category_map.get(item.get("category"))
        exists = any(c.name == item["name"] and ((item["type"] == "text" and isinstance(c, discord.TextChannel)) or
                                                    (item["type"] == "voice" and isinstance(c, discord.VoiceChannel)))
                     for c in guild.channels)
        if exists:
            continue
        try:
            common = {"category": category, "overwrites": make_overwrites(item["overwrites"]),
                      "reason": "JARVIS additive server snapshot restore"}
            if item["type"] == "text":
                await guild.create_text_channel(item["name"][:100], topic=item.get("topic"),
                    nsfw=item.get("nsfw", False), slowmode_delay=item.get("slowmode", 0), **common)
            else:
                await guild.create_voice_channel(item["name"][:100], bitrate=min(item.get("bitrate", 64000), guild.bitrate_limit),
                    user_limit=item.get("user_limit", 0), **common)
            made_channels += 1
        except discord.HTTPException:
            skipped += 1
    return made_roles, made_channels, skipped
