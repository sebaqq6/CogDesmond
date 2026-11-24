import logging
import typing as t
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import humanize_timedelta

from ..abc import MixinMeta
from ..common.embeds import build_pending_embed
from ..common.models import Suggestion
from ..views.voteview import VoteView

log = logging.getLogger("red.vrt.ideaboard.commands.user")
_ = Translator("IdeaBoard", __file__)


@cog_i18n(_)
class User(MixinMeta):
    async def validate_suggester(self, guild: discord.Guild, member: discord.Member, prefix: str) -> str | None:
        """Check whether `member` may post a suggestion right now.

        Returns a user-facing error message, or None when everything is fine.
        Shared by the /idea command and the sticky-message modal.
        """
        conf = self.db.get_conf(guild)
        if not conf.pending:
            return _("The pending suggestions channel has not been set!")

        channel = guild.get_channel(conf.pending)
        if not channel:
            return _("The pending suggestions channel no longer exists!")

        my_perms = channel.permissions_for(guild.me)
        if not (my_perms.send_messages and my_perms.embed_links):
            return _("I do not have the required permissions to send messages in the pending suggestions channel.")

        role_ids = [r.id for r in member.roles]

        # Check user's permission to suggest
        if conf.suggest_roles and not any(r in role_ids for r in conf.suggest_roles):
            return _("You do not have the required roles to make suggestions.")

        # Check account age
        if conf.min_account_age_to_suggest:
            account_age = (datetime.now().astimezone() - member.created_at).total_seconds() / 3600
            if account_age < conf.min_account_age_to_suggest:
                return _("Your account is too young to make suggestions.")

        # Check join time
        if conf.min_join_time_to_suggest:
            join_age = (datetime.now().astimezone() - member.joined_at).total_seconds() / 3600
            if join_age < conf.min_join_time_to_suggest:
                return _("You haven't been in the server long enough to make suggestions.")

        # Check role blacklist
        if conf.role_blacklist and any(r in role_ids for r in conf.role_blacklist):
            return _("You are not allowed to make suggestions due to a blacklisted role.")

        # Check user blacklist
        if conf.user_blacklist and member.id in conf.user_blacklist:
            return _("You are blacklisted from making suggestions.")

        if not conf.approvers:
            return _("No approvers have been set! Admins needs to use the {} command to add one.").format(
                f"`{prefix}ideaset approverole @role`"
            )

        # Check LevelUp requirement
        try:
            if conf.min_level_to_suggest and self.bot.get_cog("LevelUp"):
                levelup = self.bot.get_cog("LevelUp")
                if guild.id in levelup.data:
                    levelup.init_user(guild.id, str(member.id))
                    level = levelup.data[guild.id]["users"][str(member.id)]["level"]
                    if level < conf.min_level_to_suggest:
                        return _(
                            "You must be level {} or higher to make suggestions.\nUse the {} command to check your level."
                        ).format(conf.min_level_to_suggest, f"`{prefix}pf`")
        except Exception as e:
            log.exception(f"Failed to check LevelUp requirement in {guild.name}", exc_info=e)

        # Check ArkTools requirement
        try:
            if conf.min_playtime_to_suggest and self.bot.get_cog("ArkTools"):
                arktools = self.bot.get_cog("ArkTools")
                players = await arktools.db_utils.search_players(guild, member)
                if not players:
                    return _("You must be registered in the ArkTools database to make suggestions.")
                playtime_hours = players[0].total_playtime / 3600
                if playtime_hours < conf.min_playtime_to_suggest:
                    return _("You must have at least {} hours of playtime to make suggestions.").format(
                        conf.min_playtime_to_suggest
                    )
        except Exception as e:
            log.exception(f"Failed to check ArkTools requirement in {guild.name}", exc_info=e)

        # Cooldowns only apply to non approvers
        is_approver = any(r in role_ids for r in conf.approvers)
        profile = conf.get_profile(member)
        if profile.last_suggestion and not is_approver:
            delta = datetime.now() - profile.last_suggestion
            cooldown = conf.base_cooldown
            # Use the lowest cooldown of all roles the member has
            cooldowns = {k: v for k, v in conf.role_cooldowns.items() if k in role_ids}
            if cooldowns:
                cooldown = min(cooldowns.values())
            if delta.total_seconds() < cooldown:
                return _("You must wait `{}` before making another suggestion.").format(
                    humanize_timedelta(seconds=cooldown - delta.total_seconds())
                )
        return None

    async def post_suggestion(
        self, guild: discord.Guild, member: discord.Member, title: str, content: str
    ) -> tuple[int, discord.Message, discord.Embed]:
        """Post an already validated suggestion to the pending channel and register it."""
        conf = self.db.get_conf(guild)
        channel = guild.get_channel(conf.pending)
        profile = conf.get_profile(member)

        suggestion_number = conf.counter + 1
        profile.last_suggestion = datetime.now()

        suggestion_id = str(uuid4())
        suggestion = Suggestion(
            id=suggestion_id,
            message_id=0,
            author_id=member.id,
            title=title,
            content=content,
        )

        def make_embed() -> discord.Embed:
            return build_pending_embed(
                bot=self.bot,
                conf=conf,
                suggestion=suggestion,
                number=suggestion_number,
                author=member,
                anonymous=conf.anonymous,
                show_votes=conf.show_vote_counts,
                guild_id=guild.id,
            )

        embed = make_embed()
        view = VoteView(self, guild, suggestion_number, suggestion_id)
        message = await channel.send(embed=embed, view=view)
        suggestion.message_id = message.id
        if conf.discussion_threads:
            try:
                name = _("Suggestion #{} Discussion").format(suggestion_number)
                reason = _("Discussion thread for suggestion #{}").format(suggestion_number)
                thread = await message.create_thread(name=name, reason=reason)
                suggestion.thread_id = thread.id
                # Make the embed title link to the freshly created thread
                embed = make_embed()
                with suppress(discord.HTTPException):
                    await message.edit(embed=embed)
            except discord.Forbidden:
                log.warning(f"Missing permissions to create a discussion thread in {guild}")

        conf.suggestions[suggestion_number] = suggestion
        conf.counter = suggestion_number
        profile.suggestions_made += 1
        await self.save()
        return suggestion_number, message, embed

    def posted_text(self, number: int, message: discord.Message, member: discord.Member, kind: str = "suggestion") -> str:
        """Confirmation text for the author. `kind` is the word they used (idea/suggestion)."""
        can_see = message.channel.permissions_for(member).view_channel
        if can_see:
            if kind == "idea":
                return _("Your [idea #{}]({}) has been posted!").format(number, message.jump_url)
            return _("Your [suggestion #{}]({}) has been posted!").format(number, message.jump_url)
        if kind == "idea":
            return _("Your idea #{} has been posted!").format(number)
        return _("Your suggestion #{} has been posted!").format(number)

    @commands.hybrid_command(name="idea", aliases=["suggest"], description=_("Share an idea/make a suggestion."))
    @app_commands.describe(content="Your idea or suggestion")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(send_messages=True, embed_links=True, create_public_threads=True)
    async def idea(self, ctx: commands.Context, *, content: str):
        """Share an idea/make a suggestion."""

        async def resp(txt: str):
            """Return a response to the user, and delete their message if possible."""
            if ctx.interaction:
                try:
                    await ctx.interaction.response.send_message(txt, ephemeral=True)
                except discord.NotFound:
                    await ctx.interaction.followup.send(txt, ephemeral=True)
            else:
                await ctx.send(txt)

            if ctx.channel.permissions_for(ctx.me).manage_messages:
                with suppress(discord.NotFound, discord.Forbidden):
                    await ctx.message.delete()

        if error := await self.validate_suggester(ctx.guild, ctx.author, ctx.clean_prefix):
            return await resp(error)

        if ctx.channel.permissions_for(ctx.me).manage_messages:
            with suppress(discord.NotFound, discord.Forbidden):
                await ctx.message.delete()

        number, message, embed = await self.post_suggestion(ctx.guild, ctx.author, "", content)
        txt = self.posted_text(number, message, ctx.author, "idea" if ctx.invoked_with == "idea" else "suggestion")

        if ctx.interaction:
            try:
                await ctx.interaction.response.send_message(txt, embed=embed, ephemeral=True)
            except discord.NotFound:
                try:
                    await ctx.interaction.followup.send(txt, embed=embed, ephemeral=True)
                except discord.NotFound:
                    try:
                        await ctx.author.send(txt, embed=embed)
                    except discord.Forbidden:
                        await ctx.channel.send(txt, embed=embed)
        else:
            try:
                await ctx.author.send(txt, embed=embed)
            except discord.Forbidden:
                await ctx.channel.send(txt, embed=embed, delete_after=10)

    @commands.hybrid_command(
        name="ideastats",
        description=_("View your profile stats regarding suggestions and votes."),
    )
    @commands.guild_only()
    async def view_profile(self, ctx: commands.Context, *, member: t.Optional[discord.Member] = None):
        """Display your current profile stats for suggestions and votes."""
        embed = await self.fetch_profile(member or ctx.author)
        await ctx.send(embed=embed)

    async def fetch_profile(self, user: discord.Member) -> discord.Embed:
        conf = self.db.get_conf(user.guild)
        profile = conf.get_profile(user)

        embed = discord.Embed(color=discord.Color.gold(), timestamp=datetime.now())
        embed.set_author(name=_("Stats for {}").format(user.display_name), icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        up, down = conf.get_emojis(self.bot)
        embed.add_field(
            name=_("Suggestion Summary"),
            value="```\n"
            f"{_('Suggestions Made')}: {profile.suggestions_made}\n"
            f"{_('Suggestions Approved')}: {profile.suggestions_approved}\n"
            f"{_('Suggestions Denied')}: {profile.suggestions_denied}\n"
            f"{_('Karma')}: {profile.karma_str}\n"
            "```",
            inline=False,
        )
        embed.add_field(
            name=_("Voting Summary"),
            value="```\n"
            f"{up} {_('Total Upvotes')}: {profile.upvotes}\n"
            f"{down} {_('Total Downvotes')}: {profile.downvotes}\n"
            f"{_('Wins')}: {profile.wins}\n"
            f"{_('Losses')}: {profile.losses}\n"
            "```",
            inline=False,
        )
        return embed
