"""Shared JARVIS embed styling helpers."""
import discord

COLORS = {"success": 0x36B37E, "error": 0xE5484D, "warning": 0xF5A623, "info": 0x7565D9, "security": 0x247BA0}
BRAND = "JARVIS SHOP EXTREME"

def build_embed(title, description=None, *, kind="info", timestamp=True):
    embed = discord.Embed(title=title[:256], description=description, color=COLORS.get(kind, COLORS["info"]), timestamp=discord.utils.utcnow() if timestamp else None)
    embed.set_footer(text=BRAND)
    return embed

def success(title, description=None): return build_embed(title, description, kind="success")
def error(title, description=None): return build_embed(title, description, kind="error")
def warning(title, description=None): return build_embed(title, description, kind="warning")
def info(title, description=None): return build_embed(title, description, kind="info")
