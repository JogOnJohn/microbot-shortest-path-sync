# Microbot shortest-path sync

Deterministically converts pinned
[`osrs-pathfinding/shortest-path-tooling`](https://github.com/osrs-pathfinding/shortest-path-tooling)
transport data into Microbot-compatible TSV resources.

The tool is intentionally conservative:

- upstream tooling and data commits are pinned;
- upstream checkouts are never modified;
- generated files are staged under `build/`, not copied into Microbot;
- local behavior fixes are applied last through a versioned override table;
- unknown categories or columns fail loudly;
- byte-identical semantic duplicates are coalesced in reports, while conflicting duplicates fail loudly;
- reports compare parsed transport semantics rather than text lines;
- duration, requirement, adjacency, endpoint, and handler-sensitive changes are called out.

The converter uses only the Python standard library. Git and Python 3.10+ are required.

## Quick start on Windows

From PowerShell:

```powershell
git clone https://github.com/JogOnJohn/microbot-shortest-path-sync.git
Set-Location microbot-shortest-path-sync

.\sync-shortest-path.ps1 `
  -MicrobotRoot C:\Users\you\IdeaProjects\Microbot
```

If local PowerShell execution policy blocks scripts:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\sync-shortest-path.ps1 `
  -MicrobotRoot C:\Users\you\IdeaProjects\Microbot
```

The wrapper:

1. clones or refreshes the pinned upstream tooling checkout under `.upstream/`;
2. checks out the exact tooling and data commits from `transport_sync/sync_manifest.json`;
3. runs the Python tests;
4. generates normalized resources plus a hash-pinned provenance record;
5. writes a semantic report;
6. validates that exact staging payload with Microbot's Java parser, paired collision map, local-only
   resource checks, golden routes, and resource loader.

Review:

- `build/transport-sync/report/summary.md`
- `build/transport-sync/report/semantic-diff.json`
- `build/transport-sync/generated/`

Generated files are staging artifacts. Review and adopt changed categories individually.

## Direct Python usage

If the pinned upstream checkout already exists:

```powershell
python -m transport_sync.sync `
  --upstream-root C:\path\to\shortest-path-tooling `
  --baseline-root C:\path\to\Microbot\runelite-client\src\main\resources\net\runelite\client\plugins\microbot\shortestpath
```

Run tests:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

No installation is necessary. An editable install is optional:

```powershell
python -m pip install -e .
microbot-transport-sync --help
```

## How updates work

1. Fetch the tooling and data repositories.
2. Review upstream commits and changed files.
3. Update the pinned commits in `transport_sync/sync_manifest.json`.
4. Update the paired collision archive SHA-256 from the same pinned data commit; the converter stages
   and fingerprints that archive atomically with the transport catalog.
5. Run the wrapper and review the semantic report.
6. Preserve Microbot-specific fixes in `transport_sync/local_overrides.tsv`.
7. Validate staged resources with Microbot's real Java parser and golden-route tests before
   copying anything into a release branch.

This repository owns conversion, provenance, and orchestration. Microbot owns runtime parser validation,
collision endpoint ratchets, local-only resource validation, route tests, and final resource adoption.

See [docs/TRANSPORT_SCHEMA.md](docs/TRANSPORT_SCHEMA.md) for the currently supported Microbot
transport contract, upstream column mapping, and execution-sensitive semantics.

Maintainers should follow [docs/UPDATE_WORKFLOW.md](docs/UPDATE_WORKFLOW.md) for the complete pin,
review, adoption, validation, branch-promotion, and handoff procedure.

## Override identity

Overrides are matched using:

```text
(category, origin, destination, action, target, object ID)
```

They are applied after upstream normalization. Ambiguous or missing matches fail the run.

## Safety boundary

The tool does not:

- alter the upstream checkout;
- overwrite Microbot resources;
- build or launch Microbot;
- decide that a semantic change is safe.

Those boundaries keep upstream refreshes reviewable and independently revertible.

## License

BSD 2-Clause. See [LICENSE](LICENSE).
