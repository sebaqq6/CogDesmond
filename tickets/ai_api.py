import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import aiohttp
import discord

from redbot.core import commands
from redbot.core.i18n import Translator

_ = Translator("Tickets", __file__)

log = logging.getLogger("red.AAA3A.tickets.ai")

AI_API_BASE = "https://ai.eadventure.pl"

# The API rate limits to 30 req/min/IP -> keep at least one request every 2s.
_AI_MIN_INTERVAL = 2.0
_AI_POLL_INTERVAL = 3
_AI_POLL_TIMEOUT = 120


class AiApiError(RuntimeError):
    def __init__(self, status: int, body: str = "") -> None:
        super().__init__(f"AI API error {status}: {body}")
        self.status: int = status
        self.body: str = body


class AIAPI:
    BASE = AI_API_BASE

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def health(self) -> tuple[int, dict]:
        async with (await self._get_session()).get(
            f"{self.BASE}/api/health",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            try:
                data: dict = await response.json(content_type=None)
            except (ValueError, TypeError):
                data = {"raw": (await response.text())[:500]}
            return response.status, data

    async def create_ticket_report(
        self,
        token: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"}
        async with (await self._get_session()).post(
            f"{self.BASE}/api/ticket-report",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as response:
            if response.status in (200, 202):
                try:
                    data: dict = await response.json(content_type=None)
                except (ValueError, TypeError):
                    data = {}
                return response.status, data
            raise AiApiError(response.status, (await response.text())[:300])

    async def get_report(self, token: str, report_id: str) -> tuple[int, str | None]:
        headers = {"Authorization": f"Bearer {token}"}
        async with (await self._get_session()).get(
            f"{self.BASE}/api/report/{report_id}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status == 404:
                return 404, None
            if response.status in (200, 202):
                return response.status, await response.text()
            raise AiApiError(response.status, (await response.text())[:300])

    async def list_reports(self, token: str) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        async with (await self._get_session()).get(
            f"{self.BASE}/api/reports",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status == 200:
                try:
                    data: Any = await response.json(content_type=None)
                except (ValueError, TypeError):
                    data = (await response.text())[:300]
                return response.status, data
            raise AiApiError(response.status, (await response.text())[:300])


def _match_answers(
    answers: dict[str, str],
    keywords: Sequence[str],
) -> str | None:
    for label, value in answers.items():
        label_lower = label.lower()
        if any(keyword in label_lower for keyword in keywords):
            return value
    return None


def _extract_ticket_data(
    ticket,
    label_map: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """Extract the player nick and a description from the ticket modal answers.

    This returns ``(player_nick, description)``. ``player_nick`` may be None
    when the ticket has no modal answers containing a nick.
    """
    answers: dict[str, str] = dict(getattr(ticket, "owner_answers", None) or {})
    label_map = dict(label_map or {})

    player_nick: str | None = None
    if label_map.get("player_nick") in answers:
        player_nick = answers[label_map["player_nick"]]
    if not player_nick:
        player_nick = _match_answers(answers, ("zgłaszanego gracza",))
    if not player_nick:
        player_nick = _match_answers(answers, ("twój nick w grze",))

    description: str | None = None
    if label_map.get("description") in answers:
        description = answers[label_map["description"]]
    if not description:
        description = _match_answers(
            answers,
            (
                "na czym polega problem",
                "opis sytuacji",
                "opis błędu",
                "opis",
            ),
        )
    if not description:
        description = "\n".join(f"• {label} {value}" for label, value in answers.items())
    if not description:
        description = getattr(ticket, "reason", None) or ""

    description = (description or "").strip()[:2000]
    return (player_nick or "").strip() or None, description


class AiTools:
    """Mixin providing the AI report helpers for the Tickets cog."""

    def __init__(self, bot, *args, **kwargs) -> None:
        self._ai_api: AIAPI = AIAPI()
        self._ai_rate_lock: asyncio.Lock = asyncio.Lock()
        self._ai_last_request: float = 0.0
        self._ai_pollers: dict[str, asyncio.Task] = {}
        super().__init__(*args, bot=bot, **kwargs)

    async def cog_unload(self) -> None:
        await self._ai_api.close()
        for task in self._ai_pollers.values():
            task.cancel()
        await super().cog_unload()

    def _get_ticket_by_channel(self, guild, channel):
        if guild is None or channel is None:
            return None
        for ticket in self.tickets.get(guild.id, {}).values():
            if ticket.channel_id == channel.id:
                return ticket
        return None

    async def _can_use_ai_reports(self, author: discord.Member, guild) -> bool:
        if await self.bot.is_owner(author):
            return True
        if author.guild_permissions.manage_guild:
            return True
        if author.guild_permissions.administrator:
            return True
        roles = await self.config.guild(guild).ai_report_roles()
        return any(author.get_role(role_id) is not None for role_id in roles)

    async def _ai_rate_limit(self) -> None:
        async with self._ai_rate_lock:
            wait = _AI_MIN_INTERVAL - (time.monotonic() - self._ai_last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._ai_last_request = time.monotonic()

    async def _ai_token(self, guild) -> str | None:
        return await self.config.guild(guild).ai_token()

    async def _ai_health(self, guild) -> tuple[int, dict]:
        await self._ai_rate_limit()
        return await self._ai_api.health()

    async def _ai_list_reports(self, guild) -> tuple[int, Any]:
        await self._ai_rate_limit()
        token = await self._ai_token(guild)
        if not token:
            raise commands.UserFeedbackCheckFailure(
                _("Set the AI API token first with `[p]settickets ai token <token>`."),
            )
        return await self._ai_api.list_reports(token)

    async def _ai_get_report_status(self, guild, report_id: str) -> int:
        await self._ai_rate_limit()
        token = await self._ai_token(guild)
        if not token:
            return 404
        try:
            status, _ = await self._ai_api.get_report(token, report_id)
        except AiApiError as error:
            if error.status == 404:
                return 404
            raise
        return status

    async def _prepare_report(self, guild, ticket, refresh: bool = False) -> dict[str, Any]:
        """Ensure a report exists for the ticket and return its metadata.

        Uses the local cache first, then relies on the API's server-side dedup
        (same ``ticket_id`` returns the existing report). ``refresh=True``
        always creates a new report (no ``ticket_id`` sent).
        """
        ticket_key = f"TKT-{guild.id}-{ticket.id}"
        result: dict[str, Any] = {
            "ticket_key": ticket_key,
            "report_id": None,
            "report_url": None,
            "status": None,
            "cached": False,
        }

        cache = await self.config.guild(guild).ai_reports()
        entry = (cache or {}).get(ticket_key) if isinstance(cache, dict) else None
        if entry and not refresh:
            entry_id = entry.get("report_id")
            try:
                status = await self._ai_get_report_status(guild, entry_id)
            except AiApiError:
                status = 404
            if status in (200, 202):
                result.update(
                    {
                        "report_id": entry_id,
                        "report_url": entry.get("report_url"),
                        "status": status,
                        "cached": True,
                    },
                )
                return result

        player_nick, description = _extract_ticket_data(
            ticket,
            await self.config.guild(guild).ai_label_map(),
        )
        if not player_nick:
            raise commands.UserFeedbackCheckFailure(
                _(
                    "Nie znaleziono nicku gracza w odpowiedziach modala ticketa. "
                    "Upewnij się, że modal zawiera pole z nickiem.",
                ),
            )

        payload: dict[str, Any] = {
            "player_nick": player_nick[:36],
            "description": description[:2000],
        }
        if not refresh:
            payload["ticket_id"] = ticket_key

        try:
            status, data = await self._ai_api.create_ticket_report(
                await self._ai_token(guild) or "",
                payload,
            )
        except AiApiError as error:
            log.error("AI API create report failed: %s", error)
            raise commands.UserFeedbackCheckFailure(
                f"AI API error ({error.status}): {error.body}",
            )

        report_id = (data or {}).get("report_id")
        report_url = (data or {}).get("report_url")
        result.update(
            {
                "report_id": report_id,
                "report_url": report_url,
                "status": status,
                "cached": bool((data or {}).get("cached")),
            },
        )

        cache = await self.config.guild(guild).ai_reports()
        cache[ticket_key] = {
            "report_id": report_id,
            "report_url": report_url,
            "cached": bool(result["cached"]),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        await self.config.guild(guild).ai_reports.set(cache)
        return result

    @staticmethod
    def _report_line(result: dict[str, Any], done: bool = False) -> str:
        if result.get("cached") and result.get("status") == 200:
            return _("✅ Raport AI (z cache, gotowy)")
        if done:
            return _("✅ Raport AI gotowy")
        return _("⏳ Raport AI w trakcie generowania…")

    @staticmethod
    def _report_link(result: dict[str, Any]) -> str:
        report_url = result.get("report_url")
        if report_url:
            return f"🔗 {report_url}"
        report_id = result.get("report_id")
        if report_id:
            return f"ID: `{report_id}`"
        return _("(brak linku do raportu)")

    async def _update_cache_status(
        self,
        guild_id: int,
        ticket_key: str,
        report_id: str,
        done: bool = True,
    ) -> None:
        cache = await self.config.guild_from_id(guild_id).ai_reports()
        entry = (cache or {}).get(ticket_key)
        if entry and entry.get("report_id") == report_id:
            entry["status"] = "done" if done else "error"
            await self.config.guild_from_id(guild_id).ai_reports.set(cache)

    def _spawn(self, key: str, coro: Any) -> None:
        active = self._ai_pollers.get(key)
        if active is not None and not active.done():
            return
        task = asyncio.create_task(coro)

        def _done(task_: asyncio.Task) -> None:
            if self._ai_pollers.get(key) is task_:
                self._ai_pollers.pop(key, None)

        task.add_done_callback(_done)
        self._ai_pollers[key] = task

    async def _ai_wait_until_ready(
        self,
        guild_id: int,
        ticket_key: str,
        report_id: str,
        finalize: Callable[[], Any] | None = None,
    ) -> None:
        guild = self.bot.get_guild(guild_id)
        deadline = time.monotonic() + _AI_POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                if guild is None:
                    status = 404
                else:
                    status = await self._ai_get_report_status(guild, report_id)
            except AiApiError:
                status = 202
            if status == 200:
                await self._update_cache_status(guild_id, ticket_key, report_id, done=True)
                if finalize is not None:
                    try:
                        await finalize()
                    except (discord.HTTPException, discord.Forbidden) as error:
                        log.warning("AI report finalize failed: %s", error)
                return
            if status == 404:
                break
            await asyncio.sleep(_AI_POLL_INTERVAL)

    async def _notify_done(self, ctx, msg, result: dict[str, Any]) -> None:
        guild = ctx.guild
        ticket_key = result["ticket_key"]
        report_id = result["report_id"]
        if report_id:
            cache = await self.config.guild(guild).ai_reports()
            entry = cache.get(ticket_key)
            if entry and entry.get("report_id") == report_id:
                result["report_url"] = entry.get("report_url") or result["report_url"]
        content = f"{self._report_line(result, done=True)}\n{self._report_link(result)}"
        if msg is not None and getattr(ctx, "interaction", None) is None:
            try:
                await msg.edit(content=content)
                return
            except (discord.HTTPException, discord.Forbidden):
                pass
        if getattr(ctx, "interaction", None) is not None:
            try:
                await ctx.send(content, ephemeral=True)
            except (discord.HTTPException, discord.Forbidden):
                pass

    async def _run_aireport(self, ctx, refresh: bool = False) -> None:
        if ctx.interaction is None:
            try:
                await ctx.message.delete()
            except (discord.HTTPException, discord.NotFound):
                pass

        ticket = self._get_ticket_by_channel(ctx.guild, ctx.channel)
        if ticket is None:
            raise commands.UserFeedbackCheckFailure(
                _("This command must be used inside a ticket channel."),
            )
        if not await self._can_use_ai_reports(ctx.author, ctx.guild):
            raise commands.UserFeedbackCheckFailure(
                _("You are not allowed to use AI reports."),
            )

        result = await self._prepare_report(ctx.guild, ticket, refresh=refresh)
        content = f"{self._report_line(result)}\n{self._report_link(result)}"

        msg = None
        if getattr(ctx, "interaction", None) is not None:
            msg = await ctx.send(content, ephemeral=True)
        else:
            msg = await ctx.author.send(content)

        result["ticket_key"] = f"TKT-{ctx.guild.id}-{ticket.id}"
        if result["status"] == 202 and result["report_id"]:
            self._spawn(
                f"cmd-{result['report_id']}",
                self._ai_wait_until_ready(
                    ctx.guild.id,
                    result["ticket_key"],
                    result["report_id"],
                    finalize=lambda: self._notify_done(ctx, msg, result),
                ),
            )

    async def _run_aireport_button(
        self,
        interaction: discord.Interaction,
        ticket,
        refresh: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._can_use_ai_reports(interaction.user, interaction.guild):
            raise commands.UserFeedbackCheckFailure(_("You are not allowed to use AI reports."))
        result = await self._prepare_report(interaction.guild, ticket, refresh=refresh)
        content = f"{self._report_line(result)}\n{self._report_link(result)}"
        try:
            await interaction.followup.send(content, ephemeral=True)
        except (discord.HTTPException, discord.Forbidden):
            pass

        result["ticket_key"] = f"TKT-{interaction.guild.id}-{ticket.id}"
        if result["status"] == 202 and result["report_id"]:
            self._spawn(
                f"btn-{result['report_id']}",
                self._ai_wait_until_ready(
                    interaction.guild.id,
                    result["ticket_key"],
                    result["report_id"],
                ),
            )

    async def _auto_aireport(self, ticket) -> None:
        guild = getattr(ticket, "guild", None)
        if guild is None:
            return
        if not await self.config.guild(guild).ai_auto():
            return
        try:
            result = await self._prepare_report(guild, ticket)
        except (commands.UserFeedbackCheckFailure, AiApiError) as error:
            log.info("Auto AI report skipped: %s", error)
            return
        channel = ticket.channel
        if channel is None:
            return
        content = f"{self._report_line(result)}\n{self._report_link(result)}"
        try:
            msg = await channel.send(content)
        except (discord.HTTPException, discord.Forbidden) as error:
            log.warning("Could not post auto AI report: %s", error)
            return
        result["ticket_key"] = f"TKT-{guild.id}-{ticket.id}"
        if result["status"] == 202 and result["report_id"]:

            def _finalize(m=msg) -> Any:
                return m.edit(
                    content=f"✅ Raport AI gotowy.\n{self._report_link(result)}",
                )

            self._spawn(
                f"auto-{result['report_id']}",
                self._ai_wait_until_ready(
                    guild.id,
                    result["ticket_key"],
                    result["report_id"],
                    finalize=_finalize,
                ),
            )

    @commands.Cog.listener()
    async def on_ticket_create(self, ticket) -> None:
        await self._auto_aireport(ticket)

    @commands.Cog.listener()
    async def on_ticket_reopene(self, ticket) -> None:
        await self._auto_aireport(ticket)
