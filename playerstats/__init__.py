import importlib
import sys

from redbot.core import errors

try:
    import AAA3A_utils
except ModuleNotFoundError:
    raise errors.CogLoadError(
        "The needed utils to run the cog were not found. Please execute the command `[p]pipinstall git+https://github.com/AAA3A-AAA3A/AAA3A_utils.git`. A restart of the bot isn't necessary.",
    )
modules = sorted(
    [module for module in sys.modules if module.split(".")[0] == "AAA3A_utils"],
    reverse=True,
)
for module in modules:
    try:
        importlib.reload(sys.modules[module])
    except ModuleNotFoundError:
        pass
del AAA3A_utils

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement

from .playerstats import PlayerStats

__red_end_user_data_statement__ = get_end_user_data_statement(file=__file__)


async def setup(bot: Red) -> None:
    cog = PlayerStats(bot)
    await bot.add_cog(cog)
