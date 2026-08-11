PlayerStats
===========

Generate a line chart of the players online on the Eadventure server, from the `logs.eadventure.pl` API, using Plotly.

Commands
--------

- ``[p]playerstats [time_range]`` — Send the chart. An optional ``time_range`` (e.g. ``24h``, ``7d``, ``14d``) overrides the configured range for this call.

Settings
--------

- ``[p]setplayerstats range`` — The time range used by default (default: ``24h``).
- ``[p]setplayerstats title`` — The title displayed at the top of the chart.
