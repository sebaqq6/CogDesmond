# AGENTS.md — IdeaBoard

Red-DiscordBot cog (`IdeaBoard`, v0.7.13): user suggestions with moderator approval, optional anonymity, button voting and per-user stats (karma / wins / losses).
Fork of [Vertyco/vrt-cogs](https://github.com/vertyco/vrt-cogs), developed inside the **CogDesmond** repo (`ideaboard/` is one cog; others: assistant, banstrip, tickets, levelup, ...).
**Status: work in progress, not finished.** Branch: `master`.

## Stack
- Python ≥ 3.10 (3.14 locally), Red-DiscordBot ≥ 3.5.3, discord.py (hybrid commands + `discord.ui.View`)
- pydantic `>=2.11,<2.12` (config models), `orjson`
- i18n: `redbot.core.i18n.Translator` + `.po/.pot/.mo` files
- Lint/format: ruff (config in `../pyproject.toml`, line-length 100, double quotes). Note: upstream code has some lines >100.

## Project map
```
ideaboard/
├── __init__.py        setup(bot) → add_cog(IdeaBoard); end_user_data_statement
├── main.py            IdeaBoard class: Config (id 117, global key "db"), cog_load/initialize,
│                      save() (with `saving` guard), re-registers VoteViews after restart,
│                      red_delete_data_for_user
├── abc.py             CompositeMetaClass + MixinMeta (bot, db, abstract save/fetch_profile)
├── info.json          Red metadata (requirements, min_bot_version)
├── README.md          generated command docs (see "Pitfalls")
├── common/
│   ├── __init__.py    Base(BaseModel): load() / dump() (exclude_defaults=True!)
│   ├── models.py      Suggestion, Profile, GuildSettings, DB, run_migrations()
│   ├── embeds.py      build_pending_embed, build_decision_embeds, vote_fields (shared embed builders)
│   ├── listener.py    Listeners: on_message_delete, on_member_remove, Assistant integration
│   └── locales/       pl-PL (.po/.mo) + messages.pot
├── commands/
│   ├── __init__.py    Commands = Admin + AdminBase + User (mixins)
│   ├── user.py        /idea (alias suggest), /ideastats, fetch_profile()
│   ├── adminbase.py   /approve, /reject, /viewvotes, /refresh + number autocomplete
│   ├── admin.py       `ideaset` group (alias `ideaboard`): ~30 settings subcommands, insights, cleanup
│   └── locales/       pl-PL + de, es, fr, hr, ko, pt, ru, tr (upstream)
├── views/
│   ├── voteview.py    VoteView (persistent, timeout=None): up/down buttons, permission checks, embed update
│   └── locales/       as above
└── preview/
    └── ideaboard-preview.html   offline Discord-style preview of every message the cog sends
```

## Architecture / flow
1. **Mixins**: `IdeaBoard(Commands, Listeners, commands.Cog)`; every mixin inherits `MixinMeta` (typed `self.bot`, `self.db`).
2. **Data**: a single `db` dict in Red `Config` (global). `DB.configs[guild_id] → GuildSettings` holds settings, `suggestions{number: Suggestion}`, `counter`, `profiles{user_id: Profile}`. Access via `self.db.get_conf(guild)` and `conf.get_profile(user)`.
3. **Saving**: call `await self.save()` after every mutation (dumps the whole `db`). `dump()` uses `exclude_defaults=True` — default values are not persisted.
4. **/idea**: validations (pending channel, roles, account age, join time, blacklists, LevelUp, ArkTools, cooldowns; approvers are exempt from cooldown) → `build_pending_embed` → send with `VoteView` → optional discussion thread → `conf.suggestions[n]`, `counter++`.
5. **Voting**: `VoteView.upvote/downvote` toggles/switches the vote, updates `Profile` (upvotes/downvotes, *_received), rebuilds the embed (live count + %) and saves. `custom_id = upvote_<uuid>` / `downvote_<uuid>`; on restart `initialize()` re-registers a view for every suggestion (`bot.add_view(view, message_id=...)`).
6. **/approve, /reject**: require a role from `conf.approvers`; delete the pending message, close/delete the thread, post two embeds (`build_decision_embeds`: proposal + details with decision/reason) to the approved/rejected channel, update wins/losses, DM the author (`conf.dm`), remove the suggestion from config.
7. **Listeners**: deleting a pending message cleans up the suggestion and stats; `on_member_remove` purges the member's votes. `on_assistant_cog_add` registers `get_user_suggestion_stats` with the Assistant cog.
8. **Optional integrations** (via `bot.get_cog`): `LevelUp` (min level), `ArkTools` (min playtime; the `ideaset minplaytime` command is removed unless the bot ID is in the allow-list in `main.initialize`).
9. **Migrations**: `run_migrations()` in `models.py` (currently only 0.6.0); applied versions are stored in `DB.migrations`.

## Conventions
- All user-facing text goes through `_("...")` (`Translator("IdeaBoard", __file__)`); command classes use `@cog_i18n(_)`. Do not concatenate translated fragments (history: "untranslated English fragments leaking into Polish").
- New embeds belong in `common/embeds.py`, not inline.
- Commands are `hybrid_command` (prefix + slash); the suggestion number has a shared autocomplete in `adminbase.py`.
- New model fields need defaults (config backward compatibility) and, if needed, a `run_migrations` entry.
- Everything pushed to GitHub (code comments, docs, commit messages, this file) is written in **English**. Only the `.po` translation files and the sample message texts in the preview contain Polish.
- Commits: short, imperative English ("Add/Fix/Move ..."); see `git log -- ideaboard`.

## i18n workflow
Template generation (comment in `main.py`):
`redgettext -D views/voteview.py commands/user.py commands/admin.py --command-docstring` — note that past commits also regenerated pots for `commands/adminbase.py`, `common/listener.py` and `common/embeds.py`; include them all.
The actively maintained translation is **pl-PL** (the `.mo` is committed — compile with `msgfmt` after editing the `.po`). Other languages come from upstream and may be outdated.

## Previewing messages
Open `preview/ideaboard-preview.html` in a browser. Texts and sample data are in the `T`, `SAMPLE` and `build()` parts of its `<script>`; reload after editing. It mirrors `common/embeds.py` and the command responses by hand, so keep it in sync when embed layouts change, then port the final result to Python and `pl-PL.po`.

## Testing
No automated tests. Verify manually on a Red bot (`[p]load ideaboard`). Quick checks: `ruff check ideaboard` and `python -m compileall ideaboard`.

## Known pitfalls / TODO
- `README.md` is generated from upstream and **does not** describe the fork's changes (new embeds etc.); regenerate it with the docs tool, do not edit by hand.
- `VoteView.check`: user/role blacklist checks on voting are **commented out** — blacklists only apply to `/idea`. Decision pending.
- Stats can drift below zero (`suggestions_made -= 1`, `upvotes -= 1` on deletion); `cleanup` only fixes some cases.
- `approve`/`reject` check `manage_channels` on the approved channel (probably a leftover from threads) and use `mod_or_permissions(manage_messages)` **and** require an approver role — two permission layers.
- `ideaset resetall` waits on `wait_for("message")` without a timeout.
- `run_migrations` 0.6.0: `guild.get_channel` is called without a `guild is None` check.
- `Suggestion.created` uses naive `datetime.now()`, while other code compares against `.astimezone()` — watch for timezone bugs.
- `info.json` still points to the upstream author/URL (Vertyco) — update for the fork.
- `__pycache__` and `.directory` are not versioned (`.gitignore`).
