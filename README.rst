CogDesmond
==========

Personal Red-DiscordBot cogs repo by Desmond.

## Cogs

### vcounter

Update the names of **your own existing voice channels** with live server counts.
Forked and reduced from
[YamiKaitou's InfoChannel](https://github.com/yamikaitou/YamiCogs) — unlike the
original it does **not** create its own channels or a "Server Stats" category;
it edits the channels you point it at, in place.

One counter per type, each bound to a channel of your choice:

- count `members`, `humans`, `boosters`, `bots`, `online` or `offline`
- custom name template per counter with `{count}` (e.g. `Online: {count}`)
- respects Discord's channel-rename rate limit (2 per 10 min)

Installation:

```
[p]repo add cogdesmond https://github.com/sebaqq6/CogDesmond
[p]cog install cogdesmond vcounter
[p]load vcounter
[p]vcounter set online <voice_channel>
[p]vcounter toggle online
```

### verify

Fork of [Sharky The King's Verify](https://github.com/SharkyTheKing/Sharky)
with a fix: `ctx.message.delete()` is wrapped in a guard so verification still
proceeds/logs when invoked from a button (mocked context) instead of aborting.

Installation:

```
[p]cog install cogdesmond verify
[p]load verify
```

### tickets

Fork of [AAA3A's Tickets](https://github.com/AAA3A-AAA3A/AAA3A-cogs) with a
**Polish translation** (`pl-PL.po`/`pl-PL.mo`, all 175 strings). Set the bot
locale to Polish with `[p]set locale pl` and reload the cog.

Installation:

```
[p]cog install cogdesmond tickets
[p]load tickets
[p]settickets setup
```

## License

MIT. The `vcounter` cog is derived from
[YamiCogs InfoChannel](https://github.com/yamikaitou/YamiCogs) (MIT, YamiKaitou & Bobloy).
