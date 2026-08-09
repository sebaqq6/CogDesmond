import json
from pathlib import Path

from .banrole import BanRole

with (Path(__file__).parent / "info.json").open() as infofile:
    __red_end_user_data_statement__ = json.load(infofile)["end_user_data_statement"]


async def setup(bot):
    await bot.add_cog(BanRole(bot))
