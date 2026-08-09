import json
from pathlib import Path

from .banstrip import BanStrip

with (Path(__file__).parent / "info.json").open() as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot):
    cog = BanStrip(bot)
    await bot.add_cog(cog)
