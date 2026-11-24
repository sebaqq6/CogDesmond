import logging

import discord
from redbot.core.i18n import Translator, set_contextual_locales_from_guild

from ..abc import MixinMeta

log = logging.getLogger("red.vrt.ideaboard.views.sticky")
_ = Translator("IdeaBoard", __file__)

# One fixed custom_id: the same persistent view serves the sticky message of every guild
STICKY_CUSTOM_ID = "ideaboard:sticky:submit"
TITLE_MAX = 100
CONTENT_MAX = 1500


class SuggestModal(discord.ui.Modal):
    def __init__(self, cog: MixinMeta):
        super().__init__(title=_("Submit a suggestion"), timeout=900)
        self.cog = cog
        self.title_input = discord.ui.TextInput(
            label=_("Title"),
            placeholder=_("In a few words – what is your idea about?"),
            style=discord.TextStyle.short,
            max_length=TITLE_MAX,
            required=True,
        )
        self.content_input = discord.ui.TextInput(
            label=_("Your idea"),
            placeholder=_("Describe your idea. The more detail, the better."),
            style=discord.TextStyle.paragraph,
            max_length=CONTENT_MAX,
            required=True,
        )
        self.add_item(self.title_input)
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild, member = interaction.guild, interaction.user
        set_contextual_locales_from_guild(self.cog.bot, guild)
        prefix = (await self.cog.bot.get_valid_prefixes(guild))[0]
        # Re-validate: the state may have changed while the user was typing
        if error := await self.cog.validate_suggester(guild, member, prefix):
            return await interaction.followup.send(error, ephemeral=True)
        title = self.title_input.value.strip()
        content = self.content_input.value.strip()
        number, message, embed = await self.cog.post_suggestion(guild, member, title, content)
        txt = self.cog.posted_text(number, message, member)
        await interaction.followup.send(txt, embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("Error in suggestion modal", exc_info=error)
        txt = _("Something went wrong while posting your suggestion.")
        if interaction.response.is_done():
            await interaction.followup.send(txt, ephemeral=True)
        else:
            await interaction.response.send_message(txt, ephemeral=True)


class StickyView(discord.ui.View):
    """Persistent view with the 'Submit suggestion' button."""

    def __init__(self, cog: MixinMeta):
        super().__init__(timeout=None)
        self.cog = cog
        button = discord.ui.Button(
            style=discord.ButtonStyle.success,
            emoji="📝",
            label=_("Submit suggestion"),
            custom_id=STICKY_CUSTOM_ID,
        )
        button.callback = self.on_click
        self.add_item(button)

    async def on_click(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return
        set_contextual_locales_from_guild(self.cog.bot, guild)
        prefix = (await self.cog.bot.get_valid_prefixes(guild))[0]
        # Fail early so the user does not type a whole idea just to be rejected
        if error := await self.cog.validate_suggester(guild, interaction.user, prefix):
            return await interaction.response.send_message(error, ephemeral=True)
        await interaction.response.send_modal(SuggestModal(self.cog))
