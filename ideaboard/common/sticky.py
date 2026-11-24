import asyncio
import logging
from contextlib import suppress

import discord
from redbot.core.i18n import Translator, set_contextual_locales_from_guild

from ..abc import MixinMeta
from ..views.sticky import STICKY_CUSTOM_ID, StickyView
from .embeds import build_sticky_embed

log = logging.getLogger("red.vrt.ideaboard.sticky")
_ = Translator("IdeaBoard", __file__)

# Seconds of channel silence before the sticky message is moved back to the bottom
STICKY_DELAY = 5


class Sticky(MixinMeta):
    """Keeps the 'Submit suggestion' message as the last message of the pending channel."""

    def is_sticky_message(self, message: discord.Message) -> bool:
        conf = self.db.configs.get(message.guild.id) if message.guild else None
        if conf and message.id == conf.sticky_message_id:
            return True
        # The gateway can deliver our own message before its id is stored, so check the button too
        for row in message.components:
            for child in getattr(row, "children", []):
                if getattr(child, "custom_id", None) == STICKY_CUSTOM_ID:
                    return True
        return False

    def schedule_sticky(self, guild_id: int) -> None:
        """Debounced refresh: restarts the timer on every new message in the channel."""
        if old := self.sticky_tasks.pop(guild_id, None):
            old.cancel()
        self.sticky_tasks[guild_id] = asyncio.create_task(self._sticky_later(guild_id))

    async def _sticky_later(self, guild_id: int) -> None:
        await asyncio.sleep(STICKY_DELAY)
        self.sticky_tasks.pop(guild_id, None)  # from now on a new schedule must not cancel the refresh
        if guild := self.bot.get_guild(guild_id):
            try:
                await self.refresh_sticky(guild)
            except Exception as e:
                log.exception(f"Failed to refresh sticky message in {guild}", exc_info=e)

    async def refresh_sticky(self, guild: discord.Guild) -> None:
        """Delete the previous sticky message and post a fresh one at the bottom."""
        if not self.initialized:
            return
        lock = self.sticky_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            conf = self.db.get_conf(guild)
            if not conf.sticky_enabled or not conf.pending:
                return
            channel = guild.get_channel(conf.pending)
            if not channel:
                return
            perms = channel.permissions_for(guild.me)
            if not (perms.send_messages and perms.embed_links):
                log.warning(f"Missing permissions for the sticky message in {guild}")
                return

            old_id, conf.sticky_message_id = conf.sticky_message_id, 0
            if old_id:
                with suppress(discord.HTTPException):
                    await channel.get_partial_message(old_id).delete()

            set_contextual_locales_from_guild(self.bot, guild)
            embed = build_sticky_embed(self.bot, conf, channel.name)
            message = await channel.send(embed=embed, view=StickyView(self))
            conf.sticky_message_id = message.id
            await self.save()

    async def remove_sticky(self, guild: discord.Guild) -> None:
        conf = self.db.get_conf(guild)
        if task := self.sticky_tasks.pop(guild.id, None):
            task.cancel()
        old_id, conf.sticky_message_id = conf.sticky_message_id, 0
        if old_id and (channel := guild.get_channel(conf.pending)):
            with suppress(discord.HTTPException):
                await channel.get_partial_message(old_id).delete()
        await self.save()
