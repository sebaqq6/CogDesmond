CogDesmond
==========

Personal Red-DiscordBot cogs repo by Desmond.

## Cogs

### vcounter

Update the name of a **single, user-chosen existing voice channel** with a live
server count. Forked and reduced from
[YamiKaitou's InfoChannel](https://github.com/yamikaitou/YamiCogs) — unlike the
original it does **not** create its own channels or a "Server Stats" category;
it edits the channel you point it at, in place.

Features:

- set your own existing voice channel (`[p]vcounter channel #glosowy`)
- count `members`, `humans`, `boosters`, `bots`, `online` or `offline`
- custom name template with `{count}` (e.g. `Online: {count}`)
- respects Discord's channel-rename rate limit (2 per 10 min)

Installation:

```
[p]repo add cogdesmond https://github.com/<your-user>/CogDesmond
[p]cog install cogdesmond vcounter
[p]load vcounter
[p]vcounter channel <voice_channel>
[p]vcounter toggle
```

## License

MIT. The `vcounter` cog is derived from
[YamiCogs InfoChannel](https://github.com/yamikaitou/YamiCogs) (MIT, YamiKaitou & Bobloy).
