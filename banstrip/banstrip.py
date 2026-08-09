import logging

import discord

from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.cogdesmond.banstrip")


class BanStrip(commands.Cog):
    """
    Strip every role from a member when a configured BAN role is applied,
    and run the Verify flow to restore standard roles when it is removed.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5498761210, force_registration=True)
        self.config.register_guild(
            enabled=False,
            ban_role=None,
            runverify=True,
        )

    # Settings commands

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @commands.group(name="banstripset", aliases=["banstrip"])
    async def banstripset(self, ctx: commands.Context):
        """
        Settings for role stripping when the BAN role is applied.
        """

    @banstripset.command(name="role")
    async def set_ban_role(self, ctx: commands.Context, role: discord.Role | None = None):
        """
        Set the BAN role that strips all other roles.

        Leave empty to clear the configured role.
        """
        guild_conf = self.config.guild(ctx.guild)
        if role is None:
            await guild_conf.ban_role.clear()
            await ctx.send("Cleared the BAN role.")
            return
        if role >= ctx.guild.me.top_role:
            await ctx.send("The BAN role must be lower than my highest role.")
            return
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("You can't set a role equal to or higher than your own.")
            return
        await guild_conf.ban_role.set(role.id)
        await ctx.send(f"BAN role set to {role.mention}.")

    @banstripset.command(name="toggle")
    async def toggle(self, ctx: commands.Context, state: bool | None = None):
        """
        Enable or disable role stripping.
        """
        guild_conf = self.config.guild(ctx.guild)
        if state is None:
            state = not await guild_conf.enabled()
        await guild_conf.enabled.set(state)
        await ctx.send(f"Role stripping is now {'enabled' if state else 'disabled'}.")

    @banstripset.command(name="runverify")
    async def toggle_runverify(self, ctx: commands.Context, state: bool | None = None):
        """
        Toggle whether the Verify flow runs after the BAN role is removed.
        """
        guild_conf = self.config.guild(ctx.guild)
        if state is None:
            state = not await guild_conf.runverify()
        await guild_conf.runverify.set(state)
        await ctx.send(
            f"Running Verify after BAN role removal is now {'enabled' if state else 'disabled'}.",
        )

    @banstripset.command(name="view")
    async def view(self, ctx: commands.Context):
        """
        Show the current settings.
        """
        data = await self.config.guild(ctx.guild).all()
        role = ctx.guild.get_role(data["ban_role"]) if data["ban_role"] else None
        lines = [
            f"Enabled: {data['enabled']}",
            f"BAN role: {role.mention if role else 'None'}",
            f"Run Verify after removal: {data['runverify']}",
        ]
        await ctx.send(box("\n".join(lines)))

    # Listener

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return
        guild = after.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not guild.me.guild_permissions.manage_roles:
            return
        guild_conf = self.config.guild(guild)
        if not await guild_conf.enabled():
            return
        ban_role_id = await guild_conf.ban_role()
        if not ban_role_id:
            return
        had_ban = any(role.id == ban_role_id for role in before.roles)
        has_ban = any(role.id == ban_role_id for role in after.roles)
        if not had_ban and has_ban:
            await self._strip_roles(after, ban_role_id)
        elif had_ban and not has_ban:
            await self._restore(after)

    async def _strip_roles(self, member: discord.Member, ban_role_id: int) -> None:
        keep = [role for role in member.roles if role.is_managed() or role.id == ban_role_id]
        if keep == member.roles:
            return
        reason = "banstrip: BAN role applied, stripping roles"
        try:
            await member.edit(roles=keep, reason=reason)
        except discord.Forbidden:
            for role in member.roles:
                if role.id == ban_role_id or role.is_managed() or role >= member.guild.me.top_role:
                    continue
                try:
                    await member.remove_roles(role, reason=reason)
                except (discord.Forbidden, discord.HTTPException):
                    continue
        except discord.HTTPException as e:
            log.warning("Failed to strip roles from %s in %s: %s", member.id, member.guild.id, e)

    async def _restore(self, member: discord.Member) -> None:
        guild_conf = self.config.guild(member.guild)
        if not await guild_conf.runverify():
            return
        verify_cog = self.bot.get_cog("Verify")
        if verify_cog is None or not hasattr(verify_cog, "_handle_role"):
            log.warning(
                "Verify cog not loaded, cannot run verification for %s in %s",
                member.id,
                member.guild.id,
            )
            return
        try:
            # noinspection PyProtectedMember
            await verify_cog._handle_role(member)
        except (discord.Forbidden, discord.HTTPException) as e:
            log.warning("Failed to run Verify for %s in %s: %s", member.id, member.guild.id, e)
