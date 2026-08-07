import asyncio
import logging
from collections import defaultdict

import discord

from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.commands import Cog

RATE_LIMIT_DELAY = 60 * 6

log = logging.getLogger("red.cogdesmond.vcounter")

DEFAULT_NAMES = {
    "members": "Members: {count}",
    "humans": "Humans: {count}",
    "boosters": "Boosters: {count}",
    "bots": "Bots: {count}",
    "online": "Online: {count}",
    "offline": "Offline: {count}",
}

VALID_TYPES = tuple(DEFAULT_NAMES)


class VCounter(Cog):
    """
    Update the names of user-chosen voice channels with live server counts.

    One counter per type (members, humans, boosters, bots, online, offline).
    Forked from YamiKaitou's InfoChannel, reduced to update existing voice
    channels in place instead of creating its own channels/category.
    """

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot

        self.config = Config.get_conf(
            self,
            identifier=731101021116710497110110101108,
            force_registration=True,
        )

        default_guild = {
            "counters": {
                ctype: {"channel_id": None, "enabled": False, "name": DEFAULT_NAMES[ctype]}
                for ctype in VALID_TYPES
            },
        }
        self.config.register_guild(**default_guild)

        self.channel_data = defaultdict(dict)
        self.edit_queue = defaultdict(lambda: asyncio.Queue(maxsize=2))
        self._rate_limited_edits: dict[int, asyncio.Task | None] = defaultdict(lambda: None)

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return

    async def cog_load(self):
        asyncio.create_task(self.initialize())

    async def initialize(self):
        await self.bot.wait_until_red_ready()
        for guild in self.bot.guilds:
            await self.update_all_channels(guild)

    def cog_unload(self):
        self.stop_all_queues()

    @staticmethod
    async def get_counts(guild: discord.Guild) -> dict[str, int]:
        members = guild.member_count
        bot_num = len([m for m in guild.members if m.bot])
        offline_num = len([m for m in guild.members if m.status is discord.Status.offline])
        return {
            "members": members,
            "humans": members - bot_num,
            "boosters": guild.premium_subscription_count,
            "bots": bot_num,
            "online": members - offline_num,
            "offline": offline_num,
        }

    @commands.group(name="vcounter", aliases=["vcs"])
    @checks.admin()
    async def vcounter(self, ctx: commands.Context):
        """Settings for the voice channel counters."""

    @vcounter.command(name="set")
    async def set_channel(
        self,
        ctx: commands.Context,
        counter_type: str,
        channel: discord.VoiceChannel,
    ):
        """Assign an existing voice channel to a counter type.

        Valid types: members, humans, boosters, bots, online, offline
        The channel is updated in place; nothing is created or deleted.
        """
        if counter_type not in VALID_TYPES:
            await ctx.maybe_send_embed(
                f"Invalid type. Valid types: {', '.join(VALID_TYPES)}",
            )
            return
        await self.config.guild(ctx.guild).counters.set_raw(
            counter_type,
            "channel_id",
            value=channel.id,
        )
        await self.update_channel(ctx.guild, counter_type)
        if not await ctx.tick():
            await ctx.maybe_send_embed(
                f"`{counter_type}` counter set to `{channel.name}`.",
            )

    @vcounter.command(name="remove", aliases=["unset"])
    async def remove_channel(self, ctx: commands.Context, counter_type: str):
        """Remove a counter type (stops updating its channel)."""
        if counter_type not in VALID_TYPES:
            await ctx.maybe_send_embed(
                f"Invalid type. Valid types: {', '.join(VALID_TYPES)}",
            )
            return
        await self.config.guild(ctx.guild).counters.set_raw(
            counter_type,
            "channel_id",
            value=None,
        )
        await self.config.guild(ctx.guild).counters.set_raw(counter_type, "enabled", value=False)
        if not await ctx.tick():
            await ctx.maybe_send_embed(f"`{counter_type}` counter removed.")

    @vcounter.command(name="toggle")
    async def toggle(
        self,
        ctx: commands.Context,
        counter_type: str,
        enabled: bool | None = None,
    ):
        """Enable or disable a counter type."""
        if counter_type not in VALID_TYPES:
            await ctx.maybe_send_embed(
                f"Invalid type. Valid types: {', '.join(VALID_TYPES)}",
            )
            return
        if enabled is None:
            enabled = not await self.config.guild(ctx.guild).counters.get_raw(
                counter_type,
                "enabled",
            )
        await self.config.guild(ctx.guild).counters.set_raw(counter_type, "enabled", value=enabled)
        await self.update_channel(ctx.guild, counter_type)
        state = "enabled" if enabled else "disabled"
        if not await ctx.tick():
            await ctx.maybe_send_embed(f"`{counter_type}` counter {state}.")

    @vcounter.command(name="name")
    async def set_name(
        self,
        ctx: commands.Context,
        counter_type: str,
        *,
        text: str | None = None,
    ):
        """Set the name template for a counter type.

        `{count}` is replaced with the current count.

        Example: `[p]vcounter name online Online: {count}`
        """
        if counter_type not in VALID_TYPES:
            await ctx.maybe_send_embed(
                f"Invalid type. Valid types: {', '.join(VALID_TYPES)}",
            )
            return
        if text is None:
            text = DEFAULT_NAMES[counter_type]
        elif "{count}" not in text:
            await ctx.maybe_send_embed("Make sure to include `{count}` in the name.")
            return
        elif len(text) > 93:
            await ctx.maybe_send_embed("Name is too long, max length is 93.")
            return

        await self.config.guild(ctx.guild).counters.set_raw(counter_type, "name", value=text)
        await self.update_channel(ctx.guild, counter_type)
        if not await ctx.tick():
            await ctx.maybe_send_embed(f"`{counter_type}` name updated.")

    @vcounter.command(name="settings", aliases=["list"])
    async def settings(self, ctx: commands.Context):
        """Show the current counter settings."""
        data = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title="VCounter settings", colour=await ctx.embed_color())
        for counter_type in VALID_TYPES:
            c = data["counters"][counter_type]
            channel = ctx.guild.get_channel(c["channel_id"]) if c["channel_id"] else None
            channel_name = f"`{channel.name}`" if channel else "not set"
            state = "enabled" if c["enabled"] else "disabled"
            embed.add_field(
                name=counter_type,
                value=f"{channel_name} — {state}\nName: {c['name']}",
                inline=False,
            )
        await ctx.send(embed=embed)

    async def update_all_channels(self, guild: discord.Guild):
        for counter_type in VALID_TYPES:
            await self.update_channel(guild, counter_type)

    async def update_channel(self, guild: discord.Guild, counter_type: str):
        data = await self.config.guild(guild).counters.get_raw(counter_type)
        if not data["enabled"] or data["channel_id"] is None:
            return
        channel = guild.get_channel(data["channel_id"])
        if channel is None:
            return
        counts = await self.get_counts(guild)
        count = counts.get(counter_type, 0)
        name = data["name"].format(count=count)
        await self.add_to_queue(channel, count, name)

    async def add_to_queue(self, channel, count, formatted_name):
        cid = channel.id
        self.channel_data[cid] = (count, formatted_name, cid)
        if not self.edit_queue[cid].full():
            try:
                self.edit_queue[cid].put_nowait(cid)
            except asyncio.QueueFull:
                pass
        if self._rate_limited_edits[cid] is None:
            self._rate_limited_edits[cid] = asyncio.create_task(self._process_queue(cid))

    def stop_all_queues(self):
        for task in self._rate_limited_edits.values():
            if task is not None:
                task.cancel()

    async def _process_queue(self, channel_id):
        while True:
            await self.edit_queue[channel_id].get()
            count, formatted_name, cid = self.channel_data[channel_id]
            channel: discord.VoiceChannel = self.bot.get_channel(cid)
            if channel is None:
                continue
            if channel.name == formatted_name:
                continue
            log.debug(
                f"Processing channel_id: {channel_id} - count: {count} - name: {formatted_name}",
            )
            try:
                await channel.edit(reason="VCounter update", name=formatted_name)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except discord.InvalidArgument:
                log.exception(f"Invalid formatted vcounter name: {formatted_name}")
            else:
                await asyncio.sleep(RATE_LIMIT_DELAY)

    @Cog.listener(name="on_member_join")
    @Cog.listener(name="on_member_remove")
    async def on_member_join_remove(self, member: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        await self.update_all_channels(member.guild)

    @Cog.listener()
    async def on_presence_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if before.status != after.status:
            await self.update_all_channels(after.guild)
