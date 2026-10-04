# Shortest-path update and sync workflow

This is the maintainer handoff for updating Microbot from the official
`osrs-pathfinding/shortest-path-tooling` and `Skretzo/shortest-path` repositories. The safe unit of
adoption is the pinned tooling commit, its exact data submodule commit, the paired collision map,
and the generated transport payload—not any one of those in isolation.

## Repositories and branches

- Public converter: `JogOnJohn/microbot-shortest-path-sync`, branch `main`.
- Playable Microbot: `JogOnJohn/Microbot`, branch `playable/shortest-path`.
- Data-sync Microbot spike: `JogOnJohn/Microbot`, branch `spike/shortest-path-data-sync`.
- Microbot-specific behavior fixes: `transport_sync/local_overrides.tsv` in this repository and
  the matching vendored `scripts/transport_sync/local_overrides.tsv` in Microbot.

Never perform branch promotion from a dirty worktree. Confirm `git worktree list`, `git status
--short --branch`, branch heads, remotes, and `JogOnJohn` author configuration first.

## 1. Find the new official pair

Fetch the two official repositories and record:

```powershell
git fetch https://github.com/osrs-pathfinding/shortest-path-tooling.git master
git fetch https://github.com/Skretzo/shortest-path.git master
```

The tooling commit pins a gitlink named `shortest-path`. Verify that its gitlink commit is the data
commit being adopted. Review every commit and changed path between the old and new pins. A
collision-only update still requires the complete validation process.

Update these three fields together in `transport_sync/sync_manifest.json`:

```json
"tooling_commit": "<40-character tooling commit>",
"data_commit": "<40-character data commit>",
"collision_map_sha256": "<SHA-256 of data/src/main/resources/collision-map.zip>"
```

Mirror the same manifest into each Microbot spike's `scripts/transport_sync/sync_manifest.json`.

## 2. Generate and review before adoption

Run from this repository:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\sync-shortest-path.ps1 `
  -MicrobotRoot C:\path\to\Microbot-shortestpath-sync
```

The wrapper checks out the exact pins, runs Python tests, creates a provenance-hashed payload, and
passes that exact staging directory to Microbot's Java parser/collision validator and golden-route
tests. Do not use `-SkipMicrobotValidation` for an adoption candidate.

Review:

- `build/transport-sync/report/summary.md`
- `build/transport-sync/report/semantic-diff.json`
- `build/transport-sync/generated/sync-provenance.properties`
- every generated category reported as changed

Classify semantic changes by category, requirements, duration, endpoints, adjacency, and handler
type. Do not infer safety from a raw directory diff or a zero-delta converter result.

## 3. Adopt deliberately

- Copy `build/transport-sync/generated/collision-map.zip` with the same pin update.
- Adopt only reviewed changed TSV categories; do not replace the entire resource directory blindly.
- Preserve Microbot-only files (`blocked_edges.tsv`, `dangerous_tiles.tsv`, `npcs.tsv`, and
  `restrictions.tsv`) and all applicable local overrides.
- If an official row conflicts with a local behavior fix, update the stable override identity and
  explain the decision in its `Reason` field.

After adoption, rerun the wrapper. The desired steady state is zero semantic drift and identical
baseline/candidate collision hashes.

## 4. Validate and promote

Required gates:

```powershell
python -m unittest discover -s tests -p "test_*.py"
.\gradlew.bat :client:validateTransportSync `
  -PtransportSyncGeneratedDir=C:\path\to\generated --console=plain
.\gradlew.bat :client:runUnitTests `
  --tests net.runelite.client.plugins.microbot.shortestpath.ShortestPathGoldenRouteBaselineTest `
  --tests net.runelite.client.plugins.microbot.shortestpath.TransportResourceLoadTest `
  --console=plain
.\gradlew.bat :client:compileJava --console=plain
```

Run the same converter/JVM gates against both Microbot spike worktrees. Merge or cherry-pick the
reviewed update into `spike/shortest-path-data-sync` only after the playable spike is green.

Build `:client:microbotReleaseJar` only when no Microbot client is running. Packaging proves the
artifact was assembled; live walking remains a separate verification step.

## 5. Commit, push, and hand off

Keep commits reviewable:

1. Public tool pin and guide update.
2. Playable-spike pin, collision map, and reviewed TSV adoption.
3. Data-sync-spike promotion/merge.

Push the converter `main` and both Microbot spike branches. Record exact commits, collision hash,
semantic counts, test results, jar status, known failures, and anything deliberately not adopted in
Microbot's `docs/SHORTEST_PATH_DATA_SYNC_HANDOFF.md`.

All public commits must use:

```text
JogOnJohn <223066319+JogOnJohn@users.noreply.github.com>
```
