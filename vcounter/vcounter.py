import asyncio
import logging
from collections import defaultdict

import discord

from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.commands import Cog

RATE_LIMIT_DELAY = 60 * 6

log = logging.getLogger("red.cogdesmond.vcounter")


class VCounter(Cog):
    """
    Update the name of a single, user-chosen voice channel with a live server count.

    Forked from YamiKaitou's InfoChannel, reduced to update one existing voice
    channel instead of creating its own channels/category.
    """

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot

        self.config = Config.get_conf(
            self,
            identifier=731101021116710497110110101108,
            force_registration=True,
        )

        self.default_types = ["members", "humans", "boosters", "bots", "online", "offline"]

        default_guild = {
            "channel_id": None,
            "enabled": False,
            "name": "Online: {count}",
            "counter_type": "online",
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
            await self.update_channel(guild)

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
        """Settings for the voice channel counter."""

    @vcounter.command(name="channel")
    async def set_channel(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Set the existing voice channel whose name will be updated.

        The channel is updated in place; nothing is created or deleted.
        """
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await self.update_channel(ctx.guild)
        if not await ctx.tick():
            await ctx.maybe_send_embed(
                f"Counter channel set to `{channel.name}`. "
                f"Enable it with `{ctx.clean_prefix}vcounter toggle`.",
            )

    @vcounter.command(name="toggle")
    async def toggle(self, ctx: commands.Context, enabled: bool | None = None):
        """Enable or disable the counter."""
        if enabled is None:
            enabled = not await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(enabled)
        await self.update_channel(ctx.guild)
        state = "enabled" if enabled else "disabled"
        if not await ctx.tick():
            await ctx.maybe_send_embed(f"Counter {state}.")

    @vcounter.command(name="name")
    async def set_name(self, ctx: commands.Context, *, text: str | None = None):
        """Set the name template. `{count}` is replaced with the current count.

        Example: `[p]vcounter name Online: {count}`
        """
        if text is None:
            text = "Online: {count}"
        elif "{count}" not in text:
            await ctx.maybe_send_embed("Make sure to include `{count}` in the name.")
            return
        elif len(text) > 93:
            await ctx.maybe_send_embed("Name is too long, max length is 93.")
            return

        await self.config.guild(ctx.guild).name.set(text)
        await self.update_channel(ctx.guild)
        if not await ctx.tick():
            await ctx.maybe_send_embed("Name updated.")

    @vcounter.command(name="type")
    async def set_type(self, ctx: commands.Context, counter_type: str):
        """Set what to count.

        Valid types: members, humans, boosters, bots, online, offline
        """
        if counter_type not in self.default_types:
            await ctx.maybe_send_embed(
                f"Invalid type. Valid types: {', '.join(self.default_types)}",
            )
            return
        await self.config.guild(ctx.guild).counter_type.set(counter_type)
        await self.update_channel(ctx.guild)
        if not await ctx.tick():
            await ctx.maybe_send_embed(f"Counter type set to `{counter_type}`.")

    @vcounter.command(name="settings")
    async def settings(self, ctx: commands.Context):
        """Show the current counter settings."""
        data = await self.config.guild(ctx.guild).all()
        enabled = "enabled" if data["enabled"] else "disabled"
        channel = ctx.guild.get_channel(data["channel_id"]) if data["channel_id"] else None
        channel_name = channel.name if channel else "not set"
        embed = discord.Embed(title="VCounter settings", colour=await ctx.embed_color())
        embed.add_field(name="Channel", value=channel_name)
        embed.add_field(name="Status", value=enabled)
        embed.add_field(name="Type", value=data["counter_type"])
        embed.add_field(name="Name", value=data["name"], inline=False)
        await ctx.send(embed=embed)

    async def update_channel(self, guild: discord.Guild):
        data = await self.config.guild(guild).all()
        if not data["enabled"] or data["channel_id"] is None:
            return
        channel = guild.get_channel(data["channel_id"])
        if channel is None:
            return
        counts = await self.get_counts(guild)
        count = counts.get(data["counter_type"], 0)
        name = data["name"].format(count=count)
        await self.add_to_queue(guild, channel, count, name)

    async def add_to_queue(self, guild, channel, count, formatted_name):
        gid = guild.id
        self.channel_data[gid] = (count, formatted_name, channel.id)
        if not self.edit_queue[gid].full():
            try:
                self.edit_queue[gid].put_nowait(gid)
            except asyncio.QueueFull:
                pass
        if self._rate_limited_edits[gid] is None:
            self._rate_limited_edits[gid] = asyncio.create_task(self._process_queue(gid))

    def stop_all_queues(self):
        for task in self._rate_limited_edits.values():
            if task is not None:
                task.cancel()

    async def _process_queue(self, guild_id):
        while True:
            await self.edit_queue[guild_id].get()
            count, formatted_name, channel_id = self.channel_data[guild_id]
            channel: discord.VoiceChannel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            if channel.name == formatted_name:
                continue
            log.debug(f"Processing guild_id: {guild_id} - count: {count} - name: {formatted_name}")
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
        await self.update_channel(member.guild)

    @Cog.listener()
    async def on_presence_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if before.status != after.status:
            await self.update_channel(after.guild)
