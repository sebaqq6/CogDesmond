import logging
from datetime import datetime

import discord
from redbot.core.bot import Red
from redbot.core.i18n import Translator

from .models import GuildSettings, Suggestion

log = logging.getLogger("red.vrt.ideaboard.embeds")
_ = Translator("IdeaBoard", __file__)

STATUS_EMOJI = {
    "pending": "🕐",
    "approved": "✅",
    "rejected": "❌",
    "deleted": "🗑️",
}

STATUS_COLORS = {
    "pending": discord.Color.blurple(),
    "approved": discord.Color.green(),
    "rejected": discord.Color.red(),
    "deleted": discord.Color.dark_grey(),
}


def _status_label(status: str) -> str:
    labels = {
        "pending": _("Pending Approval"),
        "approved": _("Approved"),
        "rejected": _("Rejected"),
        "deleted": _("Deleted"),
    }
    return labels[status]


def vote_fields(bot: Red, conf: GuildSettings, suggestion: Suggestion) -> tuple[str, str]:
    up, down = conf.get_emojis(bot)
    up_count = len(suggestion.upvotes)
    down_count = len(suggestion.downvotes)
    total = up_count + down_count
    up_pct = round(up_count / total * 100) if total else 0
    down_pct = round(down_count / total * 100) if total else 0
    return (
        f"```\n{up_count} ({up_pct}%)\n```",
        f"```\n{down_count} ({down_pct}%)\n```",
    )


def add_vote_fields(
    embed: discord.Embed,
    bot: Red,
    conf: GuildSettings,
    suggestion: Suggestion,
) -> None:
    up, down = conf.get_emojis(bot)
    up_val, down_val = vote_fields(bot, conf, suggestion)
    embed.add_field(name=str(up), value=up_val, inline=True)
    embed.add_field(name=str(down), value=down_val, inline=True)


def build_pending_embed(
    bot: Red,
    conf: GuildSettings,
    suggestion: Suggestion,
    number: int,
    author: discord.User | None,
    anonymous: bool,
    show_votes: bool,
) -> discord.Embed:
    embed = discord.Embed(
        color=STATUS_COLORS["pending"],
        description=suggestion.content,
        timestamp=suggestion.created,
    )
    embed.set_author(name=_("Suggestion #{}").format(number))
    if anonymous or author is None:
        embed.set_footer(text=_("Posted anonymously"))
    else:
        avatar = author.display_avatar.url
        embed.set_thumbnail(url=avatar)
        embed.set_footer(text=_("Posted by {}").format(author.name), icon_url=avatar)
    status = f"{STATUS_EMOJI['pending']} {_status_label('pending')}"
    embed.add_field(name=_("Status"), value=status, inline=False)
    if show_votes:
        add_vote_fields(embed, bot, conf, suggestion)
    return embed


def build_decision_embeds(
    bot: Red,
    conf: GuildSettings,
    suggestion: Suggestion,
    number: int,
    status: str,
    approver: discord.Member | None,
    reason: str | None,
    thread: discord.Thread | None,
    author: discord.User | None,
) -> list[discord.Embed]:
    color = STATUS_COLORS[status]
    emoji = STATUS_EMOJI[status]
    label = _status_label(status)

    proposal = discord.Embed(
        color=color,
        description=suggestion.content,
        timestamp=suggestion.created,
    )
    proposal.set_author(name=_("Suggestion #{}").format(number))
    reveal = status == "approved" or not conf.anonymous or conf.reveal
    if reveal and author is not None:
        avatar = author.display_avatar.url
        proposal.set_thumbnail(url=avatar)
        proposal.set_footer(text=_("Posted by {}").format(author.name), icon_url=avatar)
    elif reveal:
        proposal.set_footer(text=_("Suggested by a user who is no longer in the server."))
    else:
        proposal.set_footer(text=_("Posted anonymously"))
    proposal.add_field(name=_("Status"), value=f"{emoji} {label}", inline=False)
    add_vote_fields(proposal, bot, conf, suggestion)

    embeds = [proposal]
    if approver is None:
        return embeds

    details = discord.Embed(color=color, timestamp=datetime.now())
    avatar = approver.display_avatar.url
    if status == "approved":
        details.set_author(name=_("Approved by {}").format(approver.display_name), icon_url=avatar)
    else:
        details.set_author(name=_("Rejected by {}").format(approver.display_name), icon_url=avatar)
    if reason:
        name = _("Reason for Rejection") if status == "rejected" else _("Reason")
        details.add_field(name=name, value=reason, inline=False)
    decision_date = discord.utils.format_dt(datetime.now(), "R")
    details.add_field(name=_("Decision Date"), value=decision_date, inline=True)
    if thread is not None:
        thread_link = f"[{_('Discussion')}]({thread.jump_url})"
        details.add_field(name=_("Thread"), value=thread_link, inline=True)
    embeds.append(details)
    return embeds
