#!/usr/bin/env python3
"""Deterministically stage pinned upstream transport data for Microbot review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CANONICAL_ALIASES = {
    "Item IDs": "Items",
    "Display Info": "Display info",
    "Varplayers": "VarPlayers",
}
PARSER_COLUMNS = {
    "Origin",
    "Destination",
    "menuOption menuTarget objectID",
    "Currency",
    "Skills",
    "Items",
    "Item IDs",
    "Quests",
    "Duration",
    "Display info",
    "Display Info",
    "Consumable",
    "Wilderness level",
    "isMembers",
    "Varbits",
    "Varplayers",
    "VarPlayers",
}
IDENTITY_COLUMNS = ("Origin", "Destination", "menuOption menuTarget objectID")
OVERRIDE_METADATA = {"Category", "Match interaction", "Operation", "Reason"}
ITEM_VARIATION_IDS = {
    "AXE=1": "1351 1349 1353 1361 1355 1357 1359 6739 23673 23279 13241 20011",
    "MACHETE=1": "975 6313 6315 6317",
}


class SyncError(RuntimeError):
    pass


@dataclass
class Table:
    headers: list[str]
    rows: list[dict[str, str]]


def canonical_header(header: str) -> str:
    return CANONICAL_ALIASES.get(header, header)


def canonical_row(row: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in row.items():
        canonical = canonical_header(key)
        if canonical not in result or value.strip():
            result[canonical] = value.strip()
    interaction_header = "menuOption menuTarget objectID"
    interaction = result.get(interaction_header, "")
    action, target, object_id = parse_action(interaction)
    if object_id != "0":
        # Microbot accepts both legacy Action;Target;123 and upstream Action Target 123.
        # They are the same parser contract and must not produce thousands of false changes.
        result[interaction_header] = f"{action};{target};{object_id}"
    return result


def read_tsv(path: Path) -> Table:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SyncError(f"Unable to read {path}: {exc}") from exc
    if not lines:
        raise SyncError(f"Empty TSV: {path}")
    header_line = lines[0]
    if not header_line.startswith("#"):
        raise SyncError(f"TSV header must start with '#': {path}")
    header_text = header_line[1:].lstrip(" ")
    # Split raw on tabs: the Java parser never interprets CSV quoting, so neither may we.
    headers = header_text.split("\t")
    if not headers or any(not header for header in headers):
        raise SyncError(f"Invalid header in {path}")
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) > len(headers):
            raise SyncError(
                f"{path}:{line_number}: {len(fields)} fields for {len(headers)} headers"
            )
        fields.extend([""] * (len(headers) - len(fields)))
        rows.append(dict(zip(headers, fields)))
    return Table(headers, rows)


def write_tsv(path: Path, table: Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# " + "\t".join(table.headers) + "\n")
        for row in table.rows:
            fields = [row.get(header, "") for header in table.headers]
            while fields and not fields[-1]:
                fields.pop()
            for field in fields:
                if "\t" in field or "\n" in field or "\r" in field:
                    raise SyncError(f"Field not representable in TSV: {field!r} in {path}")
            handle.write("\t".join(fields) + "\n")


def parse_action(value: str) -> tuple[str, str, str]:
    value = value.strip()
    if not value:
        return "", "", "0"
    local = re.fullmatch(r"([^;]+);([^;]+);(\d+)", value)
    if local:
        return tuple(part.strip() for part in local.groups())  # type: ignore[return-value]
    upstream = re.fullmatch(r"(.+)\s+(\d+)", value)
    if not upstream:
        return "", "", "0"
    action_and_target, object_id = upstream.groups()
    parts = action_and_target.strip().split(maxsplit=1)
    if len(parts) != 2:
        return "", "", "0"
    return parts[0], parts[1], object_id


def identity(category: str, row: dict[str, str]) -> tuple[str, ...]:
    canonical = canonical_row(row)
    action, target, object_id = parse_action(
        canonical.get("menuOption menuTarget objectID", "")
    )
    return (
        category,
        canonical.get("Origin", ""),
        canonical.get("Destination", ""),
        action,
        target,
        object_id,
    )


def sort_key(category: str, row: dict[str, str]) -> tuple[str, ...]:
    key = identity(category, row)
    canonical = canonical_row(row)
    return key + tuple(f"{name}={canonical.get(name, '')}" for name in sorted(canonical))


def git_head(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SyncError(f"Not a Git checkout: {path}")
    return result.stdout.strip()


def locate_upstream(tooling_root: Path, manifest: dict) -> tuple[Path, Path]:
    expected_tooling = manifest["tooling_commit"]
    actual_tooling = git_head(tooling_root)
    if actual_tooling != expected_tooling:
        raise SyncError(
            f"Tooling checkout is {actual_tooling}; expected pinned {expected_tooling}"
        )
    data_root = tooling_root / "shortest-path"
    expected_data = manifest["data_commit"]
    actual_data = git_head(data_root)
    if actual_data != expected_data:
        raise SyncError(f"Data checkout is {actual_data}; expected pinned {expected_data}")
    resources = data_root / "src/main/resources/transports"
    if not resources.is_dir():
        raise SyncError(f"Transport resources not found: {resources}")
    collision_map = data_root / "src/main/resources/collision-map.zip"
    if not collision_map.is_file():
        raise SyncError(f"Collision map not found: {collision_map}")
    return resources, collision_map


def payload_sha256(root: Path, filenames: Iterable[str]) -> str:
    """Hash staged payload names and bytes deterministically, excluding provenance itself."""
    digest = hashlib.sha256()
    for filename in sorted(filenames):
        path = root / filename
        if not path.is_file():
            raise SyncError(f"Missing staged payload: {path}")
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_headers(
    filename: str, table: Table, known_unsupported: dict[str, str]
) -> list[dict[str, object]]:
    unknown = set(table.headers) - PARSER_COLUMNS - set(known_unsupported)
    if unknown:
        raise SyncError(f"{filename}: unknown upstream columns: {sorted(unknown)}")
    findings: list[dict[str, object]] = []
    for header, explanation in known_unsupported.items():
        if header not in table.headers:
            continue
        populated = sum(1 for row in table.rows if row.get(header, "").strip())
        if populated:
            findings.append(
                {
                    "file": filename,
                    "column": header,
                    "populated_rows": populated,
                    "policy": "retained-but-not-consumed",
                    "explanation": explanation,
                }
            )
    return findings


def duplicate_identities(category: str, rows: Iterable[dict[str, str]]) -> list[tuple[str, ...]]:
    counts = Counter(identity(category, row) for row in rows)
    return [key for key, count in counts.items() if count > 1]


def comparison_key(category: str, row: dict[str, str]) -> tuple[str, ...]:
    """Pair conditional variants while keeping the documented stable identity visible."""
    canonical = canonical_row(row)
    requirements = (
        "Currency",
        "Skills",
        "Items",
        "Quests",
        "Varbits",
        "VarPlayers",
        "Consumable",
        "Wilderness level",
        "isMembers",
        "Region override",
        "Display info",
    )
    return identity(category, row) + tuple(canonical.get(field, "") for field in requirements)


def load_overrides(path: Path) -> list[dict[str, str]]:
    table = read_tsv(path)
    required = set(IDENTITY_COLUMNS) | {"Category", "Operation", "Reason"}
    missing = required - set(table.headers)
    if missing:
        raise SyncError(f"Override file missing columns: {sorted(missing)}")
    for index, row in enumerate(table.rows, start=2):
        if not row["Reason"].strip():
            raise SyncError(f"{path}:{index}: every override needs a reason")
    return table.rows


def normalize_runtime_item_requirements(tables: dict[str, Table]) -> None:
    """Translate upstream item-variation syntax into Microbot's numeric runtime schema."""
    for table in tables.values():
        item_header = next(
            (header for header in table.headers if canonical_header(header) == "Items"),
            None,
        )
        if item_header is None:
            continue

        currency_header = next(
            (header for header in table.headers if canonical_header(header) == "Currency"),
            None,
        )
        additions: list[dict[str, str]] = []
        for row in table.rows:
            value = row.get(item_header, "").strip()
            if value in ITEM_VARIATION_IDS:
                row[item_header] = ITEM_VARIATION_IDS[value]
                continue
            if value == "SHANTAY_PASS=1|COINS=5":
                row[item_header] = "1854"
                currency_row = dict(row)
                currency_row[item_header] = ""
                if currency_header is None:
                    table.headers.append("Currency")
                    currency_header = "Currency"
                currency_row[currency_header] = "5 Coins"
                additions.append(currency_row)
        table.rows.extend(additions)


def apply_overrides(
    tables: dict[str, Table], overrides: list[dict[str, str]]
) -> list[dict[str, object]]:
    applied: list[dict[str, object]] = []
    for override in overrides:
        category = override["Category"].strip()
        if category not in tables:
            raise SyncError(f"Override references unknown category: {category}")
        table = tables[category]
        match_row = dict(override)
        match_interaction = override.get("Match interaction", "").strip()
        if match_interaction:
            match_row["menuOption menuTarget objectID"] = match_interaction
        key = identity(category, match_row)
        matches = [row for row in table.rows if identity(category, row) == key]
        operation = override["Operation"].strip().upper() or "PATCH"
        if operation == "DELETE":
            if len(matches) != 1:
                raise SyncError(f"DELETE override matched {len(matches)} rows: {key}")
            table.rows.remove(matches[0])
        elif operation == "PATCH":
            if len(matches) != 1:
                raise SyncError(f"PATCH override matched {len(matches)} rows: {key}")
            target = matches[0]
            for raw_header, value in override.items():
                if raw_header in OVERRIDE_METADATA or raw_header in ("Origin", "Destination"):
                    continue
                if raw_header == "menuOption menuTarget objectID" and not match_interaction:
                    continue
                if not value.strip():
                    continue
                header = next(
                    (h for h in table.headers if canonical_header(h) == canonical_header(raw_header)),
                    None,
                )
                if header is None:
                    table.headers.append(raw_header)
                    header = raw_header
                target[header] = value.strip()
        elif operation == "UPSERT":
            if len(matches) > 1:
                raise SyncError(f"UPSERT override matched multiple rows: {key}")
            target = matches[0] if matches else {}
            for raw_header, value in override.items():
                if raw_header in OVERRIDE_METADATA:
                    continue
                if raw_header not in table.headers:
                    table.headers.append(raw_header)
                if value.strip() or raw_header in IDENTITY_COLUMNS:
                    target[raw_header] = value.strip()
            if not matches:
                table.rows.append(target)
        elif operation == "APPEND":
            if matches:
                raise SyncError(f"APPEND override already exists: {key}")
            target = {}
            for raw_header, value in override.items():
                if raw_header in OVERRIDE_METADATA:
                    continue
                if raw_header not in table.headers:
                    table.headers.append(raw_header)
                if value.strip() or raw_header in IDENTITY_COLUMNS:
                    target[raw_header] = value.strip()
            table.rows.append(target)
        else:
            raise SyncError(f"Unsupported override operation {operation}: {key}")
        applied.append(
            {
                "category": category,
                "identity": list(key),
                "operation": operation,
                "reason": override["Reason"].strip(),
            }
        )
    return applied


def semantic_map(category: str, table: Table) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in table.rows:
        key = comparison_key(category, row)
        canonical = {
            field: value
            for field, value in canonical_row(row).items()
            if value or field in IDENTITY_COLUMNS
        }
        if key in result:
            if result[key] == canonical:
                continue
            raise SyncError(f"{category}: conflicting duplicate semantic row: {key}")
        result[key] = canonical
    return result


def adjacency(row: dict[str, str]) -> str:
    def point(value: str) -> tuple[int, int, int] | None:
        parts = value.split()
        if len(parts) != 3:
            return None
        try:
            return tuple(map(int, parts))  # type: ignore[return-value]
        except ValueError:
            return None

    origin = point(row.get("Origin", ""))
    destination = point(row.get("Destination", ""))
    if origin is None or destination is None or origin[2] != destination[2]:
        return "non-adjacent"
    return "adjacent" if max(abs(origin[0] - destination[0]), abs(origin[1] - destination[1])) <= 1 else "non-adjacent"


def changed_entry(
    transport_type: str, key: tuple[str, ...], before: dict[str, str], after: dict[str, str]
) -> dict[str, object]:
    fields = {
        field: {"before": before.get(field, ""), "after": after.get(field, "")}
        for field in sorted(set(before) | set(after))
        if before.get(field, "") != after.get(field, "")
    }
    return {
        "type": transport_type,
        "identity": list(key),
        "fields": fields,
        "duration_delta": fields.get("Duration"),
        "requirements_changed": any(
            field in fields
            for field in ("Skills", "Items", "Quests", "Varbits", "VarPlayers", "Currency")
        ),
        "adjacency_before": adjacency(before),
        "adjacency_after": adjacency(after),
    }


def semantic_diff(
    baseline_root: Path,
    generated: dict[str, Table],
    categories: dict[str, str],
) -> dict[str, object]:
    added: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    counts: dict[str, dict[str, int]] = {}
    duplicates: dict[str, list[list[str]]] = {}
    identity_width = len(IDENTITY_COLUMNS) + 3  # comparison_key prefix: category+origin+dest+action+target+id
    for filename, transport_type in categories.items():
        baseline = read_tsv(baseline_root / filename)
        candidate = generated[filename]
        duplicate_keys = duplicate_identities(filename, candidate.rows)
        if duplicate_keys:
            duplicates[filename] = [list(key) for key in duplicate_keys]
        old = semantic_map(filename, baseline)
        new = semantic_map(filename, candidate)
        counts[filename] = {"baseline": len(old), "generated": len(new)}
        for key in sorted(old.keys() & new.keys()):
            if old[key] != new[key]:
                changed.append(changed_entry(transport_type, key, old[key], new[key]))

        # A row whose requirement fields changed moves between comparison keys while its
        # stable identity stays put; pair those as CHANGES, not an unrelated removal+addition,
        # so the requirement-delta counter actually fires.
        removed_by_identity: dict[tuple[str, ...], list[tuple[str, ...]]] = defaultdict(list)
        for key in sorted(old.keys() - new.keys()):
            removed_by_identity[key[:identity_width]].append(key)
        unmatched_added: list[tuple[str, ...]] = []
        for key in sorted(new.keys() - old.keys()):
            candidates = removed_by_identity.get(key[:identity_width])
            if candidates:
                changed.append(changed_entry(transport_type, key, old[candidates.pop(0)], new[key]))
            else:
                unmatched_added.append(key)
        unmatched_removed = [key for keys in removed_by_identity.values() for key in keys]

        # An interaction that is unique on both sides but moved endpoints is a relocation —
        # the case where adjacency (handler dispatch) can silently flip.
        def interaction_key(key: tuple[str, ...]) -> tuple[str, ...]:
            return (key[0], key[3], key[4], key[5])

        removed_moves: dict[tuple[str, ...], list[tuple[str, ...]]] = defaultdict(list)
        for key in unmatched_removed:
            removed_moves[interaction_key(key)].append(key)
        still_added: list[tuple[str, ...]] = []
        for key in unmatched_added:
            ikey = interaction_key(key)
            rkeys = removed_moves.get(ikey, [])
            movable = ikey[1] and ikey[3] not in ("", "0")
            if movable and len(rkeys) == 1 and sum(1 for a in unmatched_added if interaction_key(a) == ikey) == 1:
                entry = changed_entry(transport_type, key, old[rkeys.pop(0)], new[key])
                entry["endpoint_moved"] = True
                changed.append(entry)
            else:
                still_added.append(key)
        for key in still_added:
            added.append({"type": transport_type, "identity": list(key), "row": new[key]})
        for keys in removed_moves.values():
            for key in keys:
                removed.append({"type": transport_type, "identity": list(key), "row": old[key]})
    return {
        "counts": counts,
        "added": added,
        "removed": removed,
        "changed": changed,
        "duplicates": duplicates,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "duration_deltas": sum(1 for item in changed if item["duration_delta"]),
            "requirement_deltas": sum(1 for item in changed if item["requirements_changed"]),
            "adjacency_deltas": sum(
                1 for item in changed if item["adjacency_before"] != item["adjacency_after"]
            ),
            "endpoint_moves": sum(1 for item in changed if item.get("endpoint_moved")),
        },
    }


def write_summary(
    path: Path,
    manifest: dict,
    diff: dict[str, object],
    overrides: list[dict[str, object]],
    unsupported: list[dict[str, object]],
    parser_inert: list[dict[str, object]],
    baseline_collision_hash: str,
    candidate_collision_hash: str,
) -> None:
    summary = diff["summary"]
    lines = [
        "# Transport sync semantic report",
        "",
        f"- Tooling commit: `{manifest['tooling_commit']}`",
        f"- Data commit: `{manifest['data_commit']}`",
        f"- Baseline collision map SHA-256: `{baseline_collision_hash}`",
        f"- Candidate collision map SHA-256: `{candidate_collision_hash}`",
        f"- Collision map changed: **{baseline_collision_hash != candidate_collision_hash}**",
        f"- Overrides applied: **{len(overrides)}**",
        f"- Added transports: **{summary['added']}**",
        f"- Removed transports: **{summary['removed']}**",
        f"- Changed transports: **{summary['changed']}**",
        f"- Duration deltas: **{summary['duration_deltas']}**",
        f"- Requirement deltas: **{summary['requirement_deltas']}**",
        f"- Adjacency deltas: **{summary['adjacency_deltas']}**",
        f"- Endpoint moves: **{summary['endpoint_moves']}**",
        "",
        "## Known unsupported upstream semantics",
        "",
    ]
    if unsupported:
        for finding in unsupported:
            lines.append(
                f"- `{finding['file']}` / `{finding['column']}`: "
                f"{finding['populated_rows']} populated rows; {finding['policy']}. "
                f"{finding['explanation']}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Parser-inert upstream interactions", ""])
    if parser_inert:
        lines.append(
            "These rows have action/target text but no object ID. The current Microbot parser "
            "retains the transport edge but cannot execute its object interaction. They are "
            "preserved as explicit compatibility debt, not treated as newly valid routes."
        )
        lines.append("")
        for finding in parser_inert:
            lines.append(
                f"- `{finding['file']}` `{finding['origin']}` -> `{finding['destination']}`: "
                f"`{finding['interaction']}`"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Applied local overrides", ""])
    for override in overrides:
        lines.append(
            f"- `{override['category']}` `{override['identity'][1]}` -> "
            f"`{override['identity'][2]}`: {override['reason']}"
        )
    lines.extend(["", "## Category counts", "", "| File | Baseline | Generated |", "|---|---:|---:|"])
    for filename, counts in diff["counts"].items():
        lines.append(f"| `{filename}` | {counts['baseline']} | {counts['generated']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    manifest = json.loads((SCRIPT_DIR / "sync_manifest.json").read_text(encoding="utf-8"))
    upstream_resources, upstream_collision_path = locate_upstream(
        args.upstream_root.resolve(), manifest
    )
    candidate_collision_hash = hashlib.sha256(upstream_collision_path.read_bytes()).hexdigest()
    if candidate_collision_hash != manifest["collision_map_sha256"]:
        raise SyncError(
            f"Pinned upstream collision map hash is {candidate_collision_hash}; expected "
            f"{manifest['collision_map_sha256']}"
        )
    baseline_root = args.baseline_root.resolve()
    collision_path = baseline_root / "collision-map.zip"
    if not collision_path.is_file():
        raise SyncError(f"Missing baseline collision map: {collision_path}")
    baseline_collision_hash = hashlib.sha256(collision_path.read_bytes()).hexdigest()
    output_root = args.output_root.resolve()
    report_root = args.report_root.resolve()
    categories: dict[str, str] = manifest["categories"]
    actual_files = {path.name for path in upstream_resources.glob("*.tsv")}
    expected_files = set(categories)
    if actual_files != expected_files:
        raise SyncError(
            f"Upstream category drift: missing={sorted(expected_files - actual_files)}, "
            f"unexpected={sorted(actual_files - expected_files)}"
        )

    tables: dict[str, Table] = {}
    unsupported: list[dict[str, object]] = []
    parser_inert: list[dict[str, object]] = []
    for filename in sorted(categories):
        table = read_tsv(upstream_resources / filename)
        unsupported.extend(
            validate_headers(filename, table, manifest["known_unsupported_columns"])
        )
        for row in table.rows:
            interaction = row.get("menuOption menuTarget objectID", "").strip()
            if interaction and parse_action(interaction)[2] == "0":
                parser_inert.append(
                    {
                        "file": filename,
                        "origin": row.get("Origin", "").strip(),
                        "destination": row.get("Destination", "").strip(),
                        "interaction": interaction,
                    }
                )
        tables[filename] = table

    upstream_parser_inert = list(parser_inert)
    normalize_runtime_item_requirements(tables)
    overrides = apply_overrides(tables, load_overrides(SCRIPT_DIR / "local_overrides.tsv"))
    parser_inert = []
    for filename, table in tables.items():
        for row in table.rows:
            interaction = row.get("menuOption menuTarget objectID", "").strip()
            if interaction and parse_action(interaction)[2] == "0":
                parser_inert.append(
                    {
                        "file": filename,
                        "origin": row.get("Origin", "").strip(),
                        "destination": row.get("Destination", "").strip(),
                        "interaction": interaction,
                    }
                )
    for filename, table in tables.items():
        table.rows.sort(key=lambda row, name=filename: sort_key(name, row))
        # Conditional variants may intentionally share a stable identity (for example, the
        # paid/free Kathy Corkat boat rows). They remain loud in the semantic report, while an
        # override targeting an ambiguous identity still fails in apply_overrides().

    if output_root.exists():
        shutil.rmtree(output_root)
    for filename, table in tables.items():
        write_tsv(output_root / filename, table)
    for filename in manifest["local_only_resources"]:
        source = baseline_root / filename
        if not source.is_file():
            raise SyncError(f"Missing local-only resource: {source}")
        shutil.copy2(source, output_root / filename)
    shutil.copy2(upstream_collision_path, output_root / "collision-map.zip")

    payload_files = list(categories) + list(manifest["local_only_resources"]) + ["collision-map.zip"]
    generated_payload_hash = payload_sha256(output_root, payload_files)
    manifest_hash = hashlib.sha256(
        (SCRIPT_DIR / "sync_manifest.json").read_bytes()
    ).hexdigest()
    provenance = {
        "tooling_commit": manifest["tooling_commit"],
        "data_commit": manifest["data_commit"],
        "manifest_sha256": manifest_hash,
        "baseline_collision_map_sha256": baseline_collision_hash,
        "candidate_collision_map_sha256": candidate_collision_hash,
        "generated_payload_sha256": generated_payload_hash,
    }
    (output_root / "sync-provenance.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in provenance.items()),
        encoding="utf-8",
    )

    diff = semantic_diff(baseline_root, tables, categories)
    report_root.mkdir(parents=True, exist_ok=True)
    report = {
        "tooling_commit": manifest["tooling_commit"],
        "data_commit": manifest["data_commit"],
        "collision_map_sha256": candidate_collision_hash,
        "baseline_collision_map_sha256": baseline_collision_hash,
        "candidate_collision_map_sha256": candidate_collision_hash,
        "collision_map_changed": baseline_collision_hash != candidate_collision_hash,
        "generated_payload_sha256": generated_payload_hash,
        "overrides": overrides,
        "known_unsupported": unsupported,
        "upstream_parser_inert_interactions": upstream_parser_inert,
        "parser_inert_interactions": parser_inert,
        **diff,
    }
    (report_root / "semantic-diff.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_summary(
        report_root / "summary.md", manifest, diff, overrides, unsupported, parser_inert,
        baseline_collision_hash, candidate_collision_hash
    )
    print(json.dumps(diff["summary"], sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--upstream-root",
        required=True,
        type=Path,
        help="Pinned shortest-path-tooling checkout containing the shortest-path submodule",
    )
    result.add_argument(
        "--baseline-root",
        required=True,
        type=Path,
        help="Existing Microbot shortest-path resource directory used as the semantic baseline",
    )
    result.add_argument(
        "--output-root", type=Path, default=PROJECT_ROOT / "build/transport-sync/generated"
    )
    result.add_argument(
        "--report-root", type=Path, default=PROJECT_ROOT / "build/transport-sync/report"
    )
    return result


def main() -> int:
    try:
        return run(parser().parse_args())
    except SyncError as exc:
        print(f"transport-sync: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
