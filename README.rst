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
[p]repo add cogdesmond https://github.com/<your-user>/CogDesmond
[p]cog install cogdesmond vcounter
[p]load vcounter
[p]vcounter set online <voice_channel>
[p]vcounter toggle online
```

## License

MIT. The `vcounter` cog is derived from
[YamiCogs InfoChannel](https://github.com/yamikaitou/YamiCogs) (MIT, YamiKaitou & Bobloy).
