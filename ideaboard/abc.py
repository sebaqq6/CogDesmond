from abc import ABC, ABCMeta, abstractmethod

import discord
from discord.ext.commands.cog import CogMeta
from redbot.core.bot import Red

from .common.models import DB


class CompositeMetaClass(CogMeta, ABCMeta):
    """Type detection"""


class MixinMeta(ABC):
    """Type hinting"""

    def __init__(self, *_args):
        self.bot: Red
        self.db: DB

    @abstractmethod
    async def save(self) -> None:
        """Save the config"""
        raise NotImplementedError

    @abstractmethod
    async def validate_suggester(self, guild: discord.Guild, member: discord.Member, prefix: str) -> str | None:
        """Return an error message if the member cannot suggest right now"""
        raise NotImplementedError

    @abstractmethod
    async def post_suggestion(
        self, guild: discord.Guild, member: discord.Member, title: str, content: str
    ) -> tuple[int, discord.Message, discord.Embed]:
        """Post a validated suggestion to the pending channel"""
        raise NotImplementedError

    @abstractmethod
    def posted_text(self, number: int, message: discord.Message, member: discord.Member, kind: str = "suggestion") -> str:
        """Confirmation text for the author"""
        raise NotImplementedError

    @abstractmethod
    def is_sticky_message(self, message: discord.Message) -> bool:
        raise NotImplementedError

    @abstractmethod
    def schedule_sticky(self, guild_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def refresh_sticky(self, guild: discord.Guild) -> None:
        raise NotImplementedError

    @abstractmethod
    async def remove_sticky(self, guild: discord.Guild) -> None:
        raise NotImplementedError

    @abstractmethod
    async def fetch_profile(self, user: discord.Member) -> discord.Embed:
        """Get the user's profile"""
        raise NotImplementedError
