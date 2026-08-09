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

### banrole

Fork of [palmtree5's BanRole](https://github.com/palmtree5/palmtree5-cogs) (GPL-3.0)
cleaned up for Red 3.5 / Python 3.10: deprecated `checks` import replaced with
`commands.admin_or_permissions`, a bug in `red_delete_data_for_user` fixed, and
`info.json` metadata added.

Bans/unbans every member holding a given role and remembers who was banned via
which role so `[p]unbanrole` can restore them.

```
[p]cog install cogdesmond banrole
[p]load banrole
[p]banrole <role>
[p]unbanrole <role>
```

### banstrip

Custom cog: strips **all** roles from a member when a configured BAN role is
applied (only the BAN role remains active), and runs a configurable command
(default: the Verify cog's `[p]verify` flow) when the BAN role is removed, so
the standard roles come back. Includes automated ban management:

- `[p]banstrip ban <member> [days] [reason]` — apply the BAN role (strips roles);
  `days` optional, `0`/empty = permanent, auto-expires after `days` days.
- `[p]banstrip unban <member>` — remove the BAN role and run the restore command.
- `[p]banstrip banlist` — list banned members with reason and remaining duration.
- `[p]banstrip role <role>` / `[p]banstrip toggle` / `[p]banstrip restorecommand <cmd>`
- `[p]banstrip perms ban|unban|view <role>` — who may ban, unban, or view the list
  (empty list = admins only).

Command output (ban/unban/banlist) is **ephemeral** for slash invocations, so it
is only visible to the user who ran it.

**Polish translation** (`locales/pl-PL.po`/`pl-PL.mo`). Set the bot locale to
Polish with `[p]set locale pl-PL` and reload the cog.

Setup:

```
[p]cog install cogdesmond banstrip
[p]load banstrip
[p]banstrip role <ban_role>
[p]banstrip restorecommand verify
[p]banstrip toggle true
```

Note: roles are restored via the configured restore command's own logic (by
default Verify's autoroles), so a role that command does not grant is not given
back.

## License

MIT. The `vcounter` cog is derived from
[YamiCogs InfoChannel](https://github.com/yamikaitou/YamiCogs) (MIT, YamiKaitou & Bobloy).
The `banrole` cog is GPL-3.0 (palmtree5).
