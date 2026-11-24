# AGENTS.md — IdeaBoard

Cog do Red-DiscordBot (`IdeaBoard`, v0.7.13): sugestie użytkowników z zatwierdzaniem przez moderatorów, anonimowością, głosowaniem przyciskami i statystykami (karma / wins / losses).
Fork z [Vertyco/vrt-cogs](https://github.com/vertyco/vrt-cogs), rozwijany w repo **CogDesmond** (`ideaboard/` to jeden z cogów; pozostałe: assistant, banstrip, tickets, levelup, ...).
**Status: projekt w trakcie rozwoju, nieukończony.** Gałąź `master`.

## Stack
- Python ≥ 3.10 (lokalnie 3.14), Red-DiscordBot ≥ 3.5.3, discord.py (hybrid commands + `discord.ui.View`)
- pydantic `>=2.11,<2.12` (modele konfiguracji), `orjson`
- i18n: `redbot.core.i18n.Translator` + pliki `.po/.pot/.mo`
- Lint/format: ruff (konfiguracja w `../pyproject.toml`, line-length 100, double quotes). Uwaga: kod z upstreamu ma miejscami linie >100.

## Mapa projektu
```
ideaboard/
├── __init__.py        setup(bot) → add_cog(IdeaBoard); end_user_data_statement
├── main.py            klasa IdeaBoard: Config (id 117, global key "db"), cog_load/initialize,
│                      save() (z flagą saving), rejestracja VoteView po restarcie,
│                      red_delete_data_for_user
├── abc.py             CompositeMetaClass + MixinMeta (bot, db, abstract save/fetch_profile)
├── info.json          metadane Red (requirements, min_bot_version)
├── README.md          wygenerowana dokumentacja komend (patrz „Pułapki")
├── common/
│   ├── __init__.py    Base(BaseModel): load() / dump() (exclude_defaults=True!)
│   ├── models.py      Suggestion, Profile, GuildSettings, DB, run_migrations()
│   ├── embeds.py      build_pending_embed, build_decision_embeds, vote_fields (wspólne buildery embedów)
│   ├── listener.py    Listeners: on_message_delete, on_member_remove, integracja z Assistant
│   └── locales/       pl-PL (.po/.mo) + messages.pot
├── commands/
│   ├── __init__.py    Commands = Admin + AdminBase + User (mixiny)
│   ├── user.py        /idea (alias suggest), /ideastats, fetch_profile()
│   ├── adminbase.py   /approve, /reject, /viewvotes, /refresh + autocomplete numeru
│   ├── admin.py       grupa `ideaset` (alias `ideaboard`): ~30 podkomend ustawień, insights, cleanup
│   └── locales/       pl-PL + de, es, fr, hr, ko, pt, ru, tr (upstream)
└── views/
    ├── voteview.py    VoteView (persistent, timeout=None): przyciski up/down, walidacja uprawnień, update embeda
    └── locales/       jak wyżej
```

## Architektura / przepływ
1. **Mixiny**: `IdeaBoard(Commands, Listeners, commands.Cog)`; każdy mixin dziedziczy `MixinMeta` (typy `self.bot`, `self.db`).
2. **Dane**: jeden słownik `db` w Red `Config` (global). `DB.configs[guild_id] → GuildSettings` zawiera ustawienia, `suggestions{numer: Suggestion}`, `counter`, `profiles{user_id: Profile}`. Dostęp: `self.db.get_conf(guild)`, `conf.get_profile(user)`.
3. **Zapis**: po każdej mutacji `await self.save()` (cały `db.dump()`). `dump()` używa `exclude_defaults=True` — wartości domyślne nie trafiają do configu.
4. **/idea**: walidacje (kanał pending, role, wiek konta, czas na serwerze, blacklisty, LevelUp, ArkTools, cooldowny; approverzy bez cooldownu) → `build_pending_embed` → wysłanie z `VoteView` → opcjonalny wątek dyskusji → `conf.suggestions[n]`, `counter++`.
5. **Głosowanie**: `VoteView.upvote/downvote` — przełączanie/cofanie głosu, aktualizacja `Profile` (upvotes/downvotes, *_received), przebudowa embeda (live count + %), `save()`. `custom_id = upvote_<uuid>` / `downvote_<uuid>`; po restarcie `initialize()` rejestruje view dla każdej sugestii (`bot.add_view(view, message_id=...)`).
6. **/approve, /reject**: wymagają roli z `conf.approvers`; usuwają wiadomość pending, zamykają/usuwają wątek, wysyłają 2 embedy (`build_decision_embeds`: propozycja + szczegóły z decyzją/powodem) na kanał approved/rejected, liczą wins/losses, DM do autora (`conf.dm`), kasują sugestię z configu.
7. **Listenery**: usunięcie wiadomości pending ⇒ sprzątanie sugestii i statystyk; `on_member_remove` ⇒ czyszczenie głosów. `on_assistant_cog_add` rejestruje funkcję `get_user_suggestion_stats` dla cogu Assistant.
8. **Integracje opcjonalne** (przez `bot.get_cog`): `LevelUp` (min level), `ArkTools` (min playtime; komenda `ideaset minplaytime` usuwana, jeśli bot nie jest na liście ID w `main.initialize`).
9. **Migracje**: `run_migrations()` w `models.py` (obecnie tylko 0.6.0); wersje zapisywane w `DB.migrations`.

## Konwencje
- Teksty użytkownika zawsze przez `_("...")` (`Translator("IdeaBoard", __file__)`), klasy komend z `@cog_i18n(_)`. Nie sklejaj tłumaczonych fragmentów (historia: „untranslated English fragments leaking into Polish").
- Nowe embedy → `common/embeds.py`, nie inline.
- Komendy to `hybrid_command` (prefix + slash); numer sugestii ma wspólny autocomplete w `adminbase.py`.
- Nowe pola modeli muszą mieć wartości domyślne (kompatybilność configu) i ewentualnie wpis w `run_migrations`.
- Commity: krótkie, angielskie, w stylu „Add/Fix/Move ..." (zob. `git log -- ideaboard`).

## Workflow i18n
Generowanie szablonów (komentarz w `main.py`):
`redgettext -D views/voteview.py commands/user.py commands/admin.py --command-docstring` — uwaga: w historii pot-y były regenerowane także dla `commands/adminbase.py` i `common/listener.py`, `common/embeds.py`; uwzględnij je wszystkie.
Aktywne tłumaczenie własne: **pl-PL** (utrzymywane, plik `.mo` jest commitowany — po zmianie `.po` skompiluj `msgfmt`). Pozostałe języki pochodzą z upstreamu i mogą być nieaktualne.

## Testy
Brak testów automatycznych. Weryfikacja ręczna na botcie Red (`[p]load ideaboard`). Szybki check składni/lint: `ruff check ideaboard` i `python -m compileall ideaboard`.

## Znane pułapki / do dokończenia
- `README.md` jest wygenerowany z upstreamu i **nie opisuje** zmian forka (nowe embedy itd.); regeneruj narzędziem docs Red/Vertyco, nie edytuj ręcznie.
- `VoteView.check`: sprawdzanie blacklist (user/role) przy głosowaniu jest **zakomentowane** — blacklisty działają tylko przy `/idea`. Decyzja do podjęcia.
- Statystyki mogą zejść poniżej zera / rozjechać się (`suggestions_made -= 1`, `upvotes -= 1` przy usuwaniu); `cleanup` koryguje tylko część przypadków.
- `approve`/`reject` sprawdzają `manage_channels` na kanale approved (prawdopodobnie pozostałość po wątkach) i mają `mod_or_permissions(manage_messages)` **oraz** wymóg roli approvera — dwie warstwy uprawnień.
- `ideaset resetall` czeka na `wait_for("message")` bez timeoutu.
- `run_migrations` 0.6.0: `guild.get_channel` bez sprawdzenia `guild is None`.
- `Suggestion.created` używa `datetime.now()` (naive), a w kodzie porównania z `.astimezone()` — uważaj na strefy czasowe.
- `info.json` nadal wskazuje autora/URL upstreamu (Vertyco) — do uzupełnienia pod fork.
- `__pycache__` i `.directory` nie są wersjonowane (`.gitignore`).
