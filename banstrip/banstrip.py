import datetime
import logging
from io import BytesIO
from typing import Literal

import discord

from redbot.core import Config, commands, tasks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify

log = logging.getLogger("red.cogdesmond.banstrip")

RequesterTypes = Literal["discord_deleted_user", "owner", "user", "user_strict"]

PERM_KEYS = {"ban": "ban_roles", "unban": "unban_roles", "view": "view_roles"}


class BanStrip(commands.Cog):
    """
    Strip all roles from a member when a configured BAN role is applied,
    and run a configurable command (e.g. Verify) when the BAN role is removed.

    Includes `ban`/`unban`/`banlist` commands with reasons, optional durations
    in days (with automatic expiry), and per-guild permissions for each action.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5498761210, force_registration=True)
        self.config.register_guild(
            enabled=False,
            ban_role=None,
            restore_command="verify",
            ban_roles=[],
            unban_roles=[],
            view_roles=[],
        )
        self.config.register_member(
            reason=None,
            banned_by=None,
            banned_at=None,
            expires_at=None,
        )

    async def cog_load(self):
        await super().cog_load()
        self._expiry_loop.start()

    async def cog_unload(self):
        self._expiry_loop.cancel()
        await super().cog_unload()

    async def red_get_data_for_user(self, *, user_id: int) -> dict[str, BytesIO]:
        lines = []
        all_members = await self.config.all_members()
        for guild_id, members in all_members.items():
            data = members.get(str(user_id))
            if not data:
                continue
            lines.append(
                f"Server {guild_id}: reason={data.get('reason')!r} "
                f"banned_by={data.get('banned_by')} banned_at={data.get('banned_at')} "
                f"expires_at={data.get('expires_at')}",
            )
        if not lines:
            return {}
        content = f"banstrip records for user {user_id}:\n" + "\n".join(lines)
        return {"user_data.txt": BytesIO(content.encode())}

    async def red_delete_data_for_user(self, *, requester: RequesterTypes, user_id: int) -> None:
        for guild_id in await self.config.all_members():
            await self.config.member_from_ids(int(guild_id), user_id).clear()

    # ---------- Main group ----------

    @commands.guild_only()
    @commands.hybrid_group(name="banstrip", aliases=["banstripset", "bs"])
    async def banstrip(self, ctx: commands.Context):
        """
        Ban/unban members with the BAN role and manage banstrip settings.
        """

    # ---------- Actions ----------

    @commands.guild_only()
    @banstrip.command(name="ban")
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        details: str | None = None,
    ):
        """
        Apply the BAN role to a member (stripping their other roles).

        `details` may start with a number of days (0 or empty = permanent),
        optionally followed by a reason.
        Example: `[p]banstrip ban @user 7 spamming`
        """
        if not await self._check_action(ctx, "ban_roles"):
            return await self._reply(ctx, "You don't have permission to ban members.")
        if not await self._require_ban_role(ctx):
            return None
        if member == ctx.author:
            return await self._reply(ctx, "You can't ban yourself.")
        if member == ctx.guild.owner:
            return await self._reply(ctx, "You can't ban the server owner.")
        if member == ctx.guild.me:
            return await self._reply(ctx, "You can't ban the bot.")
        if member.guild_permissions.ban_members:
            return await self._reply(
                ctx,
                "You can't ban someone whose role has the `ban_members` permission.",
            )
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await self._reply(
                ctx,
                "You can't ban someone with a role equal to or higher than yours.",
            )
        if member.top_role >= ctx.guild.me.top_role:
            return await self._reply(
                ctx,
                "I can't manage that member's roles (their top role is too high).",
            )

        days, reason = self._parse_details(details)
        expires_at = self._expiry_from_days(days)

        ban_role = ctx.guild.get_role(await self.config.guild(ctx.guild).ban_role())
        already = ban_role in member.roles
        try:
            await member.add_roles(ban_role, reason=reason or "banstrip: banned")
        except discord.Forbidden:
            return await self._reply(ctx, "I don't have permission to add the BAN role.")
        except discord.HTTPException as e:
            return await self._reply(ctx, f"Failed to add the BAN role: {e}")

        member_conf = self.config.member(member)
        await member_conf.reason.set(reason)
        await member_conf.banned_by.set(ctx.author.id)
        await member_conf.banned_at.set(
            int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        )
        await member_conf.expires_at.set(expires_at)

        msg = (
            f"{member.mention} is already banned."
            if already
            else f"{member.mention} has been banned."
        )
        if reason:
            msg += f"\nReason: {reason}"
        msg += f"\nDuration: {days} days" if days else "\nDuration: permanent"
        await self._reply(ctx, msg)
        return None

    @commands.guild_only()
    @banstrip.command(name="unban")
    async def unban(self, ctx: commands.Context, member: discord.Member):
        """
        Remove the BAN role from a member and run the restore command.
        """
        if not await self._check_action(ctx, "unban_roles"):
            return await self._reply(ctx, "You don't have permission to unban members.")
        if not await self._require_ban_role(ctx):
            return None
        ban_role = ctx.guild.get_role(await self.config.guild(ctx.guild).ban_role())
        if ban_role not in member.roles:
            return await self._reply(ctx, f"{member.mention} does not have the BAN role.")
        try:
            await member.remove_roles(ban_role, reason=f"banstrip: unbanned by {ctx.author}")
        except (discord.Forbidden, discord.HTTPException) as e:
            return await self._reply(ctx, f"Failed to remove the BAN role: {e}")
        await self._reply(
            ctx,
            f"{member.mention} has been unbanned. Running the restore command...",
        )
        return None

    @commands.guild_only()
    @banstrip.command(name="banlist")
    async def banlist(self, ctx: commands.Context):
        """
        List currently banned members (with the BAN role), their reasons and durations.
        """
        if not await self._check_action(ctx, "view_roles"):
            return await self._reply(ctx, "You don't have permission to view the ban list.")
        ban_role_id = await self.config.guild(ctx.guild).ban_role()
        if not ban_role_id:
            return await self._reply(ctx, "No BAN role is configured.")
        ban_role = ctx.guild.get_role(ban_role_id)
        if ban_role is None:
            return await self._reply(ctx, "The configured BAN role no longer exists.")
        members = [m for m in ctx.guild.members if ban_role in m.roles]
        if not members:
            return await self._reply(ctx, "No members are currently banned.")
        lines = []
        for member in members:
            data = await self.config.member(member).all()
            reason = data["reason"] or "No reason"
            if expires := data["expires_at"]:
                dt = datetime.datetime.fromtimestamp(expires, tz=datetime.timezone.utc)
                duration = f"expires {discord.utils.format_dt(dt, 'R')}"
            else:
                duration = "permanent"
            lines.append(f"{member} ({member.id})\n  Reason: {reason}\n  Duration: {duration}")
        for page in pagify("\n".join(lines), shorten_by=10):
            await self._reply(ctx, box(page))
        return None

    # ---------- Settings ----------

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @banstrip.command(name="role", with_app_command=False)
    async def set_ban_role(self, ctx: commands.Context, role: discord.Role | None = None):
        """
        Set the BAN role that strips all other roles. Leave empty to clear.
        """
        guild_conf = self.config.guild(ctx.guild)
        if role is None:
            await guild_conf.ban_role.clear()
            return await self._reply(ctx, "Cleared the BAN role.")
        if role >= ctx.guild.me.top_role:
            return await self._reply(ctx, "The BAN role must be lower than my highest role.")
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await self._reply(ctx, "You can't set a role equal to or higher than your own.")
        await guild_conf.ban_role.set(role.id)
        await self._reply(ctx, f"BAN role set to {role.mention}.")
        return None

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @banstrip.command(name="toggle", with_app_command=False)
    async def toggle(self, ctx: commands.Context, state: bool | None = None):
        """
        Enable or disable role stripping and the ban commands.
        """
        guild_conf = self.config.guild(ctx.guild)
        if state is None:
            state = not await guild_conf.enabled()
        await guild_conf.enabled.set(state)
        await self._reply(ctx, f"banstrip is now {'enabled' if state else 'disabled'}.")

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @banstrip.command(name="restorecommand", with_app_command=False)
    async def set_restore_command(self, ctx: commands.Context, *, command: str | None = None):
        """
        Set the command run when the BAN role is removed (e.g. `verify`).

        Leave empty to disable. The command is invoked as the unbanned member.
        """
        guild_conf = self.config.guild(ctx.guild)
        if command is None or not command.strip():
            await guild_conf.restore_command.clear()
            return await self._reply(ctx, "No restore command will be run.")
        if self.bot.get_command(command.strip().split(maxsplit=1)[0]) is None:
            return await self._reply(ctx, "That command does not exist.")
        await guild_conf.restore_command.set(command.strip())
        await self._reply(ctx, f"Restore command set to `{command}`.")
        return None

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @banstrip.group(name="perms", with_app_command=False)
    async def perms(self, ctx: commands.Context):
        """
        Configure who can ban, unban, and view the ban list.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @perms.command(name="ban", with_app_command=False)
    async def perms_ban(self, ctx: commands.Context, role: discord.Role | None = None):
        """
        Add/remove a role allowed to use `ban`. Leave empty to clear (admins only).
        """
        await self._toggle_perm_role(ctx, "ban_roles", role)

    @perms.command(name="unban", with_app_command=False)
    async def perms_unban(self, ctx: commands.Context, role: discord.Role | None = None):
        """
        Add/remove a role allowed to use `unban`. Leave empty to clear (admins only).
        """
        await self._toggle_perm_role(ctx, "unban_roles", role)

    @perms.command(name="view", with_app_command=False)
    async def perms_view(self, ctx: commands.Context, role: discord.Role | None = None):
        """
        Add/remove a role allowed to view the ban list. Leave empty to clear (admins only).
        """
        await self._toggle_perm_role(ctx, "view_roles", role)

    @perms.command(name="list", with_app_command=False)
    async def perms_list(self, ctx: commands.Context):
        """
        Show who can use each action.
        """
        data = await self.config.guild(ctx.guild).all()
        lines = []
        for key, label in PERM_KEYS.items():
            role_ids = data[key]
            if not role_ids:
                lines.append(f"{label}: admins only")
                continue
            roles = [r.mention for rid in role_ids if (r := ctx.guild.get_role(rid))]
            lines.append(f"{label}: {humanize_list(roles) if roles else 'None'}")
        await self._reply(ctx, box("\n".join(lines)))

    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    @banstrip.command(name="view", with_app_command=False)
    async def view(self, ctx: commands.Context):
        """
        Show the current settings.
        """
        data = await self.config.guild(ctx.guild).all()
        role = ctx.guild.get_role(data["ban_role"]) if data["ban_role"] else None
        lines = [
            f"Enabled: {data['enabled']}",
            f"BAN role: {role.mention if role else 'None'}",
            f"Restore command: {data['restore_command'] or 'None'}",
            f"Can ban: {await self._format_roles(data['ban_roles'], ctx)}",
            f"Can unban: {await self._format_roles(data['unban_roles'], ctx)}",
            f"Can view: {await self._format_roles(data['view_roles'], ctx)}",
        ]
        await self._reply(ctx, box("\n".join(lines)))

    # ---------- Listener ----------

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
            await self.config.member(after).clear()
            await self._run_restore(guild, after)
        elif has_ban:
            await self._strip_roles(after, ban_role_id)

    # ---------- Internals ----------

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

    async def _run_restore(self, guild: discord.Guild, member: discord.Member) -> None:
        command_line = await self.config.guild(guild).restore_command()
        if not command_line:
            return
        channel = self._pick_channel(guild)
        if channel is None:
            log.warning(
                "No usable channel to run restore command for %s in %s",
                member.id,
                guild.id,
            )
            return
        prefix = (await self.bot.get_valid_prefixes(guild=guild))[0]
        message = self._make_fake_message(channel, member, f"{prefix}{command_line}")
        context = await self.bot.get_context(message)
        context.author = member
        context.guild = guild
        context.channel = channel
        if not context.valid:
            log.warning("Restore command '%s' not found in %s", command_line, guild.id)
            return
        try:
            await self.bot.invoke(context)
        except Exception as e:  # noqa: BLE001 - errors from arbitrary invoked commands are logged, not raised
            log.warning(
                "Error running restore command '%s' for %s in %s: %s",
                command_line,
                member.id,
                guild.id,
                e,
            )

    def _pick_channel(self, guild: discord.Guild) -> discord.abc.Messageable | None:
        system_channel = guild.system_channel
        if system_channel is not None and system_channel.permissions_for(guild.me).send_messages:
            return system_channel
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                return channel
        return None

    def _make_fake_message(self, channel, author, content) -> discord.Message:
        created_at = datetime.datetime.now(datetime.timezone.utc)
        message_id = discord.utils.time_snowflake(created_at)
        author_dict = {
            "id": str(author.id),
            "username": author.display_name,
            "avatar": None,
            "avatar_decoration": None,
            "discriminator": str(author.discriminator),
            "public_flags": 0,
            "bot": author.bot,
        }
        timestamp = created_at.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        data = {
            "id": str(message_id),
            "type": 0,
            "content": content,
            "channel_id": str(channel.id),
            "author": author_dict,
            "attachments": [],
            "embeds": [],
            "mentions": [],
            "mention_roles": [],
            "pinned": False,
            "mention_everyone": False,
            "tts": False,
            "timestamp": timestamp,
            "edited_timestamp": None,
            "flags": 0,
            "components": [],
            "referenced_message": None,
        }
        return discord.Message(channel=channel, state=self.bot._connection, data=data)

    @tasks.loop(seconds=60)
    async def _expiry_loop(self) -> None:
        all_members = await self.config.all_members()
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        for guild_id, members_data in all_members.items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue
            if await self.bot.cog_disabled_in_guild(self, guild):
                continue
            if not guild.me.guild_permissions.manage_roles:
                continue
            guild_conf = self.config.guild(guild)
            if not await guild_conf.enabled():
                continue
            ban_role_id = await guild_conf.ban_role()
            if not ban_role_id:
                continue
            ban_role = guild.get_role(ban_role_id)
            if ban_role is None:
                continue
            for user_id, data in members_data.items():
                expires_at = data.get("expires_at")
                if not expires_at or expires_at > now:
                    continue
                member = guild.get_member(int(user_id))
                if member is None or ban_role not in member.roles:
                    continue
                try:
                    await member.remove_roles(ban_role, reason="banstrip: ban expired")
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.warning("Failed to expire ban for %s in %s: %s", user_id, guild.id, e)

    @_expiry_loop.before_loop
    async def _before_expiry_loop(self) -> None:
        await self.bot.wait_until_red_ready()

    async def _check_action(self, ctx: commands.Context, key: str) -> bool:
        if ctx.author == ctx.guild.owner or await ctx.bot.is_owner(ctx.author):
            return True
        role_ids = await self.config.guild(ctx.guild).get_raw(key)
        if not role_ids:
            return ctx.author.guild_permissions.manage_roles
        return any(role.id in role_ids for role in ctx.author.roles)

    async def _require_ban_role(self, ctx: commands.Context) -> bool:
        guild_conf = self.config.guild(ctx.guild)
        if not await guild_conf.enabled():
            await self._reply(
                ctx,
                "banstrip is disabled in this server. Enable it with "
                f"`{ctx.clean_prefix}banstrip toggle true`.",
            )
            return False
        if not await guild_conf.ban_role():
            await self._reply(
                ctx,
                "No BAN role is configured. Set one with "
                f"`{ctx.clean_prefix}banstrip role <role>`.",
            )
            return False
        return True

    async def _toggle_perm_role(
        self,
        ctx: commands.Context,
        key: str,
        role: discord.Role | None,
    ) -> None:
        guild_conf = self.config.guild(ctx.guild)
        label = PERM_KEYS.get(key, key)
        if role is None:
            await guild_conf.set_raw(key, value=[])
            await self._reply(ctx, f"Cleared the '{label}' role list (admins only).")
            return
        role_ids = await guild_conf.get_raw(key)
        if role.id in role_ids:
            role_ids.remove(role.id)
        else:
            role_ids.append(role.id)
        await guild_conf.set_raw(key, value=role_ids)
        state = "removed from" if role.id not in role_ids else "added to"
        await self._reply(ctx, f"{role.mention} {state} the '{label}' role list.")

    async def _format_roles(self, role_ids: list[int], ctx: commands.Context) -> str:
        if not role_ids:
            return "admins only"
        roles = [ctx.guild.get_role(rid).mention for rid in role_ids if ctx.guild.get_role(rid)]
        return humanize_list(roles) if roles else "None"

    async def _reply(self, ctx: commands.Context, content: str, **kwargs) -> discord.Message:
        if ctx.interaction is not None:
            kwargs["ephemeral"] = True
        return await ctx.send(content, **kwargs)

    @staticmethod
    def _parse_details(details: str | None) -> tuple[int | None, str | None]:
        if not details:
            return None, None
        parts = details.split(maxsplit=1)
        try:
            days = int(parts[0])
        except ValueError:
            return None, details.strip()
        if days <= 0:
            return None, (parts[1].strip() if len(parts) > 1 else None)
        return days, (parts[1].strip() if len(parts) > 1 else None)

    @staticmethod
    def _expiry_from_days(days: int | None) -> int | None:
        if not days:
            return None
        now = datetime.datetime.now(datetime.timezone.utc)
        return int((now + datetime.timedelta(days=days)).timestamp())
