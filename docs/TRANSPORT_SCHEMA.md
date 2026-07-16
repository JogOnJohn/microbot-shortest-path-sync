# Transport data contract and upstream mapping

This document owns the file-format contract for Microbot shortest-path transports and the mapping
from the pinned upstream data. Runtime truth remains the parser in
`net.runelite.client.plugins.microbot.shortestpath.Transport`.

## Pinned upstream

| Component | Repository | Commit |
|---|---|---|
| Tooling | `osrs-pathfinding/shortest-path-tooling` | `86fbe2197c2dd192db33896c7ca47ab5cef14929` |
| Data submodule | `Skretzo/shortest-path` | `7e7e5bf94bbb155c2454bcdf8c1036dec0fd9a79` |

The paired Microbot `collision-map.zip` SHA-256 is
`3e1658cf4bd1ad34832b42c3896df61a7fe6421f96758d046e4a8aa39cbbc40a`. This upstream revision
changes only the collision archive: all 25 transport TSVs are unchanged from the previous pin.
The converter verifies the paired local hash while collision compatibility remains independently
validated by the endpoint ratchet and golden routes.

At this pin, upstream uses the combined `menuOption menuTarget objectID` column. The earlier split
column format mentioned in the planning document is not present in this revision. All 25
upstream-managed TSVs match the current playable spike byte-for-byte except six Gate 190 rows in
`transports.tsv`; those rows are represented in `scripts/transport_sync/local_overrides.tsv`.

## File mechanics

- UTF-8, tab-separated text.
- The first row is the header and starts with `#` or `# `.
- Later blank lines and lines starting with `#` are ignored.
- Headers select fields; column position has no meaning beyond its header.
- A blank Origin means an originless teleport. A blank Destination is used by permutation networks.
- A non-coordinate Origin or Destination becomes the internal permutation sentinel.
- Rows are one-way. Two-way travel requires both directions or a permutation pair.

## Accepted fields

| Canonical field | Accepted headers | Syntax and runtime meaning | Default |
|---|---|---|---|
| Origin | `Origin` | `x y plane`; blank for originless teleports; other nonblank text means a permutation endpoint | `null` |
| Destination | `Destination` | `x y plane`; blank/non-coordinate semantics mirror Origin | `null` |
| Object interaction | `menuOption menuTarget objectID` | `Action Target 123` or legacy `Action;Target;123`; the first word is the action and the final integer is the object ID | no interaction metadata |
| Currency | `Currency` | `<amount> <name>`; currently only the first name token is retained | none |
| Skills | `Skills` | `level Skill;level Skill`; every listed skill is required | level 0 |
| Items | `Items`, `Item IDs` | Semicolon separates requirement groups; whitespace or `||` separates alternatives inside a group; `id=count` counts are parsed but current runtime stores IDs only | none |
| Quests | `Quests` | `Quest name` means FINISHED; `Quest name=STATE` selects a `QuestState`; semicolon separates requirements | none |
| Duration | `Duration` | Integer game ticks. It affects path cost and object-transport landing wait | 0; teleports forced to at least 1 |
| Display info | `Display info`, `Display Info` | Destination label or selection text used by transport-specific handlers | `null` |
| Consumable | `Consumable` | `T` or case-insensitive `yes` | false |
| Wilderness level | `Wilderness level` | Maximum wilderness level for use | -1 |
| Members | `isMembers` | `Y` or case-insensitive `yes` | false |
| Varbits | `Varbits` | Semicolon-separated `id<op>value`; operators: `>`, `<`, `=`, `&` bit-set, `@` cooldown-minutes | none |
| Varplayers | `Varplayers`, `VarPlayers` | Same operators and separators as Varbits | none |

Malformed varbit/varplayer/item tokens are currently logged and skipped. The sync validator treats
unknown columns and structural errors as failures so a refresh cannot rely on that permissiveness.

## Execution-sensitive semantics

- `Duration` is protected local behavior. `Rs2Walker` waits
  `max(5000ms, Duration * 600ms + 2000ms)` after an object transport. Upstream Duration never
  overwrites a local override without review.
- Origin-to-destination Chebyshev distance at most one on the same plane is an adjacent transport.
  Adjacency changes which `Rs2Walker` branch owns the interaction.
- The resource filename assigns `TransportType`; moving an identical row between files can change
  its runtime handler.
- Grapple shortcuts are derived from AGILITY_SHORTCUT rows requiring Ranged or Strength above 1.
- Teleport classification forces Duration to at least one and affects availability/cost logic.
- `PathfinderConfig.useTransport` and its `tp_audit` rejection describer must keep the same gate
  order whenever a requirement field is added.
- Collision resources are versioned separately. Transport endpoints must be checked against the
  shipped `collision-map.zip` before category adoption.

## Upstream column mapping

| Upstream column | Classification | Microbot handling |
|---|---|---|
| Origin, Destination | Direct | Parsed as coordinates, null endpoints, or permutation sentinels |
| `menuOption menuTarget objectID` | Direct | Combined action/target/object parser |
| Skills, Quests, Duration, Consumable, Wilderness level, Varbits | Direct | Same header and syntax |
| Items | Alias-compatible | Parser also accepts the older `Item IDs` name |
| Display info | Alias-compatible | Parser also accepts `Display Info` |
| VarPlayers | Alias-compatible | Parser also accepts `Varplayers` |
| Region override | Known unsupported | Retained and reported. Six seasonal rows use it at this pin; Microbot does not yet model League-region availability |

Unknown future columns fail the converter. Known unsupported columns are never silently removed.

## Category mapping

| Upstream file(s) | Microbot `TransportType` |
|---|---|
| `transports.tsv` | TRANSPORT |
| `agility_shortcuts.tsv` | AGILITY_SHORTCUT, with runtime GRAPPLE_SHORTCUT derivation |
| `boats.tsv`, `canoes.tsv`, `charter_ships.tsv`, `ships.tsv` | BOAT, CANOE, CHARTER_SHIP, SHIP |
| `fairy_rings.tsv`, `gnome_gliders.tsv`, `spirit_trees.tsv`, `quetzals.tsv` | Matching network type |
| `minecarts.tsv`, `magic_carpets.tsv`, `hot_air_balloons.tsv`, `magic_mushtrees.tsv` | Matching network type |
| `quetzal_whistle.tsv`, `teleportation_items.tsv` | TELEPORTATION_ITEM |
| `teleportation_boxes.tsv`, `teleportation_portals.tsv`, `teleportation_portals_poh.tsv` | TELEPORTATION_PORTAL |
| `teleportation_levers.tsv` | TELEPORTATION_LEVER |
| `teleportation_minigames.tsv` | TELEPORTATION_MINIGAME |
| `teleportation_spells.tsv`, `teleportation_spells_home.tsv` | TELEPORTATION_SPELL |
| `wilderness_obelisks.tsv` | WILDERNESS_OBELISK |
| `seasonal_transports.tsv` | SEASONAL_TRANSPORT |

`blocked_edges.tsv`, `dangerous_tiles.tsv`, `npcs.tsv`, and `restrictions.tsv` are Microbot-local
resources at this pin. `collision-map.zip` stays outside the transport converter. Runtime-generated
POH/W330 transports are also outside this sync.

## Local override contract

`scripts/transport_sync/local_overrides.tsv` is a patch table applied after upstream normalization.
Its stable identity is:

`(category, origin, destination, action, target, object ID)`

Operations are:

- `PATCH`: exactly one upstream row must match; nonblank non-identity fields replace upstream values.
- `Match interaction`: when an object ID is being repaired, this optional field identifies the old
  interaction while `menuOption menuTarget objectID` supplies its replacement.
- `UPSERT`: update one match or add a complete new row.
- `DELETE`: exactly one upstream row must match and is removed.

Every override requires a reason. Missing/ambiguous targets fail the sync. The generated catalog is
staged under `build/transport-sync/generated`; it does not replace live resources automatically.
