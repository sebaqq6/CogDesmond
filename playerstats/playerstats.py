import io
import math
import re
import typing

import aiohttp
import discord
import plotly.graph_objects as go
from AAA3A_utils import Cog, Settings

from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n

# Credits:
# General repo credits.

_: Translator = Translator("PlayerStats", __file__)

RANGE_PATTERN: re.Pattern[str] = re.compile(r"\d+[smhdw]")

WIDTH: int = 1600
HEIGHT: int = 420


class RangeConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> str:
        if not RANGE_PATTERN.fullmatch(argument):
            raise commands.BadArgument(
                _("Invalid range. Use something like `24h`, `7d` or `14d`."),
            )
        return argument


@cog_i18n(_)
class PlayerStats(Cog):
    """Generate a line chart of the players online, from the Eadventure logs API!"""

    def __init__(self, bot: Red) -> None:
        super().__init__(bot=bot)

        self.config: Config = Config.get_conf(
            self,
            identifier=660080498880664614152121381047,
            force_registration=True,
        )
        self.config.register_guild(
            range="24h",
            title="Liczba graczy online w czasie",
        )

        _settings: dict[str, dict[str, typing.Any]] = {
            "range": {
                "converter": RangeConverter,
                "description": "The time range of the chart (e.g. `24h`, `7d` or `14d`).",
            },
            "title": {
                "converter": str,
                "description": "The title displayed at the top of the chart.",
            },
        }
        self.settings: Settings = Settings(
            bot=self.bot,
            cog=self,
            config=self.config,
            group=self.config.GUILD,
            settings=_settings,
            global_path=[],
            use_profiles_system=False,
            can_edit=True,
            commands_group=self.setplayerstats,
        )

        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        await super().cog_load()
        await self.settings.add_commands()
        self._session: aiohttp.ClientSession = aiohttp.ClientSession(raise_for_status=True)

    async def cog_unload(self) -> None:
        await super().cog_unload()
        if self._session is not None:
            await self._session.close()

    async def get_stats(self, time_range: str) -> list[dict[str, typing.Any]]:
        async with self._session.get(
            "https://logs.eadventure.pl/api/player-stats",
            params={"range": time_range},
            headers={"User-Agent": "Red-DiscordBot/PlayerStats"},
        ) as response:
            return await response.json()

    def _generate_chart_bytes(
        self,
        data: list[dict[str, typing.Any]],
        time_range: str,
        title: str,
    ) -> bytes:
        times = [item["time"] for item in data]
        online_players = [item["online_players"] for item in data]
        max_players = max(online_players, default=0)
        dynamic_tick = math.ceil(max_players / 10) if max_players > 20 else 1
        tickformat = "%d.%m %H:%M" if time_range.endswith("h") else "%d.%m"

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=times,
                y=online_players,
                mode="lines",
                name=_("Liczba graczy online"),
                line={"shape": "linear", "color": "#8b00ff"},
                marker={"color": "#8b00ff"},
                fill="tozeroy",
                fillcolor="rgba(139, 0, 255, 0.3)",
                hovertemplate=_("%{y} graczy<extra></extra>"),
            ),
        )
        fig.update_layout(
            title={"text": title, "font": {"color": "#fff", "size": 20}},
            xaxis={
                "title": {"text": _("Czas"), "font": {"color": "#fff", "size": 16}},
                "type": "date",
                "tickformat": tickformat,
                "tickfont": {"color": "#fff", "size": 14},
            },
            yaxis={
                "title": {
                    "text": _("Liczba graczy online"),
                    "font": {"color": "#fff", "size": 16},
                },
                "rangemode": "tozero",
                "fixedrange": True,
                "dtick": dynamic_tick,
                "tickmode": "linear",
                "tickfont": {"color": "#fff", "size": 14},
                "gridcolor": "#444",
            },
            paper_bgcolor="#2c2c2c",
            plot_bgcolor="#333",
            margin={"l": 50, "r": 20, "t": 50, "b": 60},
            width=WIDTH,
            height=HEIGHT,
            autosize=False,
        )
        return fig.to_image(format="png", width=WIDTH, height=HEIGHT, scale=1)

    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.guild)
    @commands.hybrid_command(name="playerstats")
    async def playerstats(
        self,
        ctx: commands.Context,
        time_range: str | None = None,
    ) -> None:
        """Generate a line chart of the online players, from the Eadventure logs API.

        `time_range` is optional and overrides the configured range for this call.
        """
        if time_range is not None:
            time_range = await RangeConverter().convert(ctx, time_range)
        else:
            time_range = await self.config.guild(ctx.guild).range()
        title = await self.config.guild(ctx.guild).title()

        try:
            data = await self.get_stats(time_range)
        except aiohttp.ClientError as error:
            await ctx.send(
                _("Failed to fetch the data from the API: {error}").format(error=error),
            )
            return
        if not data:
            await ctx.send(
                _("No data was returned for the range `{time_range}`.").format(
                    time_range=time_range,
                ),
            )
            return

        async with ctx.typing():
            chart_bytes = await self.bot.loop.run_in_executor(
                None,
                self._generate_chart_bytes,
                data,
                time_range,
                title,
            )
        file = discord.File(io.BytesIO(chart_bytes), filename="chart.png")
        await ctx.send(file=file)

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_group(name="setplayerstats")
    async def setplayerstats(self, ctx: commands.Context) -> None:
        """Configure PlayerStats."""
