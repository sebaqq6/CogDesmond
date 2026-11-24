import logging
from datetime import datetime

import discord
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import humanize_timedelta

from .models import GuildSettings, Suggestion

log = logging.getLogger("red.vrt.ideaboard.embeds")
_ = Translator("IdeaBoard", __file__)

STATUS_EMOJI = {
    "pending": "🕐",
    "approved": "✅",
    "rejected": "❌",
    "deleted": "🗑️",
}

# Title emoji (pending gets a lightbulb instead of the clock used in the status line)
TITLE_EMOJI = {
    "pending": "💡",
    "approved": "✅",
    "rejected": "❌",
    "deleted": "🗑️",
}

BAR_LENGTH = 10

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


def quote(text: str) -> str:
    """Turn text into a Discord block quote (one `> ` per line)."""
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines()) or "> "


def vote_bar(up: int, down: int, length: int = BAR_LENGTH) -> str:
    """Emoji progress bar: green = upvotes, red = downvotes, black = no votes yet."""
    total = up + down
    if not total:
        return "⬛" * length
    green = round(length * up / total)
    if up and not green:
        green = 1
    if down and green == length:
        green = length - 1
    return "🟩" * green + "🟥" * (length - green)


def vote_field(bot: Red, conf: GuildSettings, suggestion: Suggestion) -> tuple[str, str]:
    """Return (name, value) for the single full-width vote field."""
    up, down = conf.get_emojis(bot)
    up_count = len(suggestion.upvotes)
    down_count = len(suggestion.downvotes)
    total = up_count + down_count
    up_pct = round(up_count / total * 100) if total else 0
    down_pct = round(down_count / total * 100) if total else 0
    value = (
        f"{vote_bar(up_count, down_count)}\n"
        f"{up} **{up_count}** ({up_pct}%)  ・  {down} **{down_count}** ({down_pct}%)"
    )
    if not total:
        value += f"\n-# {_('No votes yet')}"
    return f"📊 {_('Community Vote')}", value


def add_vote_fields(
    embed: discord.Embed,
    bot: Red,
    conf: GuildSettings,
    suggestion: Suggestion,
) -> None:
    name, value = vote_field(bot, conf, suggestion)
    embed.add_field(name=name, value=value, inline=False)


def thread_url(guild_id: int | None, suggestion: Suggestion) -> str | None:
    """Jump URL of the suggestion's discussion thread (a thread is a channel, so guild/thread id is enough)."""
    if guild_id and suggestion.thread_id:
        return f"https://discord.com/channels/{guild_id}/{suggestion.thread_id}"
    return None


def suggestion_body(number: int, status: str, content: str, url: str | None = None, title: str = "") -> str:
    """Embed description: big title, small status line, quoted suggestion text."""
    suggestion_title = title
    title = f"{TITLE_EMOJI[status]} {_('Suggestion #{}').format(number)}"
    if url:
        title = f"[{title}]({url})"  # clickable title -> discussion thread
    status_line = f"{STATUS_EMOJI[status]} {_status_label(status)}"
    heading = f"## {title}\n-# {status_line}\n\n"
    if suggestion_title:
        heading += f"### {suggestion_title}\n"
    return heading + quote(content)


def build_pending_embed(
    bot: Red,
    conf: GuildSettings,
    suggestion: Suggestion,
    number: int,
    author: discord.User | None,
    anonymous: bool,
    show_votes: bool,
    guild_id: int | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        color=STATUS_COLORS["pending"],
        description=suggestion_body(number, "pending", suggestion.content, thread_url(guild_id, suggestion), suggestion.title),
        timestamp=suggestion.created,
    )
    if anonymous or author is None:
        embed.set_footer(text=_("Posted anonymously"))
    else:
        avatar = author.display_avatar.url
        embed.set_thumbnail(url=avatar)
        embed.set_footer(text=_("Posted by {}").format(author.name), icon_url=avatar)
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

    proposal = discord.Embed(
        color=color,
        description=suggestion_body(number, status, suggestion.content, thread.jump_url if thread else None, suggestion.title),
        timestamp=suggestion.created,
    )
    reveal = status == "approved" or not conf.anonymous or conf.reveal
    if reveal and author is not None:
        avatar = author.display_avatar.url
        proposal.set_thumbnail(url=avatar)
        proposal.set_footer(text=_("Posted by {}").format(author.name), icon_url=avatar)
    elif reveal:
        proposal.set_footer(text=_("Suggested by a user who is no longer in the server."))
    else:
        proposal.set_footer(text=_("Posted anonymously"))
    add_vote_fields(proposal, bot, conf, suggestion)

    embeds = [proposal]
    if approver is None:
        return embeds

    now = datetime.now()
    details = discord.Embed(color=color, timestamp=now)
    avatar = approver.display_avatar.url
    if status == "approved":
        details.set_author(name=_("Approved by {}").format(approver.display_name), icon_url=avatar)
    else:
        details.set_author(name=_("Rejected by {}").format(approver.display_name), icon_url=avatar)
    if reason:
        name = _("Reason for Rejection") if status == "rejected" else _("Reason")
        details.add_field(name=f"💬 {name}", value=quote(reason), inline=False)
    decision_date = f"{discord.utils.format_dt(now, 'f')}\n-# {discord.utils.format_dt(now, 'R')}"
    details.add_field(name=f"📅 {_('Decision Date')}", value=decision_date, inline=True)
    if thread is not None:
        thread_link = f"[{_('Discussion')}]({thread.jump_url})"
        details.add_field(name=f"🧵 {_('Thread')}", value=thread_link, inline=True)
    embeds.append(details)
    return embeds


def build_sticky_embed(bot: Red, conf: GuildSettings, channel_name: str) -> discord.Embed:
    """The sticky 'Submit suggestion' message kept at the bottom of the pending channel."""
    up, down = conf.get_emojis(bot)
    lines = [
        f"## 💡 {_('Got an idea for the server?')}",
        _("Share it with the community – we implement the best proposals!"),
        "",
        f"### 📜 {_('How it works')}",
        "1️⃣ " + _("Click **Submit suggestion** below"),
        "2️⃣ " + _("Describe your idea in the window that appears"),
        "3️⃣ " + _("The community votes {} / {}").format(up, down),
        "4️⃣ " + _("Moderators approve or reject – you get the result in a DM"),
        "",
        f"### ⚠️ {_('Rules')}",
        "- " + _("One suggestion = one idea"),
        "- " + _("Check whether someone has already posted it – use Discord search and type `in: #{}` + a keyword").format(
            channel_name
        ),
        "- " + _("No spam, insults or unban requests (use a ticket for that)"),
        "",
        "-# " + (_("🕶️ Suggestions are posted anonymously") if conf.anonymous else _("👤 Suggestions are posted with your name")),
    ]
    approved = sum(p.suggestions_approved for p in conf.profiles.values())
    cooldown = humanize_timedelta(seconds=conf.base_cooldown) if conf.base_cooldown else "–"
    embed = discord.Embed(color=discord.Color.gold(), description="\n".join(lines))
    embed.add_field(name=f"📥 {_('Pending')}", value=f"**{len(conf.suggestions)}**", inline=True)
    embed.add_field(name=f"✅ {_('Approved')}", value=f"**{approved}**", inline=True)
    embed.add_field(name=f"⏱️ {_('Cooldown')}", value=f"**{cooldown}**", inline=True)
    return embed
