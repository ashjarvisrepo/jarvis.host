"""Discord-native persistent support panel components."""
import discord


class SupportPanelView(discord.ui.View):
    """Persistent HELP/PURCHASE/QUESTIONS panel backed by a real ticket opener."""

    def __init__(self, open_ticket):
        super().__init__(timeout=None)
        self.open_ticket = open_ticket
        for label, emoji, kind in (
            ("HELP", "🆘", "help"),
            ("PURCHASE", "🛒", "purchase"),
            ("QUESTIONS", "❓", "questions"),
        ):
            button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.primary, custom_id=f"jarvis:support:{kind}")
            button.callback = self._handler(kind)
            self.add_item(button)

    def _handler(self, kind):
        async def callback(interaction):
            await self.open_ticket(interaction, kind)
        return callback


class AutoBuyPanelView(discord.ui.View):
    """Persistent SellAuth checkout link and private support button."""

    def __init__(self, open_ticket, store_url):
        super().__init__(timeout=None)
        if store_url:
            self.add_item(discord.ui.Button(label="Browse & Buy", emoji="🛒", style=discord.ButtonStyle.link, url=store_url))
        support = discord.ui.Button(label="Support Ticket", emoji="🎫", style=discord.ButtonStyle.secondary, custom_id="jarvis:autobuy:support")

        async def callback(interaction):
            await open_ticket(interaction, "help")

        support.callback = callback
        self.add_item(support)
