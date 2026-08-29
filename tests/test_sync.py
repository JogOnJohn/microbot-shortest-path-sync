import tempfile
import unittest
from pathlib import Path

from transport_sync.sync import (
    SyncError,
    Table,
    apply_overrides,
    identity,
    normalize_runtime_item_requirements,
    parse_action,
    payload_sha256,
    read_tsv,
    semantic_diff,
    semantic_map,
    write_tsv,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TransportSyncTest(unittest.TestCase):
    def test_normalizes_runtime_item_variations_and_splits_shantay_fare(self):
        headers = [
            "Origin", "Destination", "menuOption menuTarget objectID", "Items", "Currency"
        ]
        tables = {
            "transports.tsv": Table(headers, [
                {"Origin": "1 1 0", "Destination": "1 2 0",
                 "menuOption menuTarget objectID": "Chop-down Jungle Bush 2892",
                 "Items": "MACHETE=1", "Currency": ""},
                {"Origin": "2 2 0", "Destination": "2 1 0",
                 "menuOption menuTarget objectID": "Go-through Shantay pass 4031",
                 "Items": "SHANTAY_PASS=1|COINS=5", "Currency": ""},
            ])
        }

        normalize_runtime_item_requirements(tables)

        rows = tables["transports.tsv"].rows
        self.assertEqual("975 6313 6315 6317", rows[0]["Items"])
        self.assertEqual(3, len(rows))
        self.assertEqual("1854", rows[1]["Items"])
        self.assertEqual("", rows[2]["Items"])
        self.assertEqual("5 Coins", rows[2]["Currency"])

    def test_semantic_diff_ignores_equivalent_interaction_serialization(self):
        with tempfile.TemporaryDirectory() as temp:
            baseline = Path(temp)
            (baseline / "transports.tsv").write_text(
                "# Origin\tDestination\tmenuOption menuTarget objectID\tDuration\n"
                "1 2 0\t1 3 0\tOpen;Tree Gnome Gate;190\t9\n",
                encoding="utf-8",
            )
            generated = {
                "transports.tsv": Table(
                    ["Origin", "Destination", "menuOption menuTarget objectID", "Duration", "Consumable"],
                    [{
                        "Origin": "1 2 0",
                        "Destination": "1 3 0",
                        "menuOption menuTarget objectID": "Open Tree Gnome Gate 190",
                        "Duration": "9",
                        "Consumable": "",
                    }],
                )
            }

            diff = semantic_diff(baseline, generated, {"transports.tsv": "TRANSPORT"})

            self.assertEqual(0, diff["summary"]["added"])
            self.assertEqual(0, diff["summary"]["removed"])
            self.assertEqual(0, diff["summary"]["changed"])

    def test_payload_hash_is_filename_sorted_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "b.tsv").write_bytes(b"two")
            (root / "a.tsv").write_bytes(b"one")
            first = payload_sha256(root, ["b.tsv", "a.tsv"])
            self.assertEqual(first, payload_sha256(root, ["a.tsv", "b.tsv"]))
            (root / "a.tsv").write_bytes(b"changed")
            self.assertNotEqual(first, payload_sha256(root, ["a.tsv", "b.tsv"]))

    def test_parses_multiword_target_and_object_id(self):
        self.assertEqual(("Open", "Tree Gnome Gate", "190"), parse_action("Open Tree Gnome Gate 190"))

    def test_semantic_map_coalesces_identical_duplicate_rows(self):
        row = {
            "Origin": "3081 3421 0",
            "Destination": "1859 5243 0",
            "menuOption menuTarget objectID": "Climb-down;Entrance;20790",
            "Duration": "",
        }
        table = Table(list(row), [row, dict(row)])

        self.assertEqual(1, len(semantic_map("transports.tsv", table)))

    def test_semantic_map_rejects_conflicting_duplicate_rows(self):
        first = {
            "Origin": "3081 3421 0",
            "Destination": "1859 5243 0",
            "menuOption menuTarget objectID": "Climb-down;Entrance;20790",
            "Duration": "1",
        }
        second = dict(first, Duration="2")

        with self.assertRaisesRegex(SyncError, "conflicting duplicate semantic row"):
            semantic_map("transports.tsv", Table(list(first), [first, second]))

    def test_applies_duration_override_without_mutating_other_fields(self):
        table = read_tsv(FIXTURES / "upstream" / "transports.tsv")
        overrides = read_tsv(FIXTURES / "local_overrides.tsv").rows
        applied = apply_overrides({"transports.tsv": table}, overrides)

        self.assertEqual(1, len(applied))
        gate = next(row for row in table.rows if row["menuOption menuTarget objectID"] == "Open Gate 190")
        self.assertEqual("9", gate["Duration"])
        door = next(row for row in table.rows if row["menuOption menuTarget objectID"] == "Open Door 123")
        self.assertEqual("Fixture door", door["Display info"])

    def test_ambiguous_patch_fails_loudly(self):
        table = read_tsv(FIXTURES / "upstream" / "transports.tsv")
        table.rows.append(dict(table.rows[0]))
        overrides = read_tsv(FIXTURES / "local_overrides.tsv").rows
        with self.assertRaisesRegex(SyncError, "matched 2 rows"):
            apply_overrides({"transports.tsv": table}, overrides)

    def test_patch_can_replace_parser_inert_interaction_identity(self):
        table = read_tsv(FIXTURES / "upstream" / "transports.tsv")
        override = {
            "Category": "transports.tsv",
            "Match interaction": "Open Gate 190",
            "Origin": "2461 3385 0",
            "Destination": "2461 3382 0",
            "menuOption menuTarget objectID": "Open Gate 190 190",
            "Operation": "PATCH",
            "Reason": "Fixture object ID repair.",
        }
        apply_overrides({"transports.tsv": table}, [override])
        self.assertEqual("Open Gate 190 190", table.rows[0]["menuOption menuTarget objectID"])

    def test_fields_with_quotes_round_trip_verbatim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "quotes.tsv"
            content = '# Origin\tDestination\tDisplay info\n1 2 0\t3 4 0\tSay "hello" twice\n'
            source.write_text(content, encoding="utf-8")
            table = read_tsv(source)
            self.assertEqual('Say "hello" twice', table.rows[0]["Display info"])
            output = Path(temp_dir) / "out.tsv"
            write_tsv(output, table)
            self.assertEqual(content, output.read_text(encoding="utf-8"))

    def test_write_omits_trailing_empty_columns(self):
        table = Table(["Origin", "Destination", "Duration"], [{
            "Origin": "1 2 0", "Destination": "3 4 0", "Duration": ""
        }])
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "out.tsv"
            write_tsv(output, table)
            self.assertEqual(
                "# Origin\tDestination\tDuration\n1 2 0\t3 4 0\n",
                output.read_text(encoding="utf-8"),
            )

    def test_write_rejects_unrepresentable_fields(self):
        table = Table(["Origin"], [{"Origin": "tab\tinside"}])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(SyncError, "not representable"):
                write_tsv(Path(temp_dir) / "bad.tsv", table)

    def _diff(self, baseline_lines, generated_rows, headers):
        with tempfile.TemporaryDirectory() as temp_dir:
            baseline = Path(temp_dir) / "transports.tsv"
            baseline.write_text("\n".join(baseline_lines) + "\n", encoding="utf-8")
            generated = {"transports.tsv": Table(list(headers), generated_rows)}
            return semantic_diff(Path(temp_dir), generated, {"transports.tsv": "TRANSPORT"})

    def test_requirement_change_reports_as_changed_not_add_remove(self):
        headers = ["Origin", "Destination", "menuOption menuTarget objectID", "Skills", "Duration"]
        baseline = ["# " + "\t".join(headers), "1 1 0\t1 2 0\tOpen Door 123\t10 Agility\t2"]
        generated_rows = [{
            "Origin": "1 1 0", "Destination": "1 2 0",
            "menuOption menuTarget objectID": "Open Door 123",
            "Skills": "20 Agility", "Duration": "2",
        }]
        diff = self._diff(baseline, generated_rows, headers)
        self.assertEqual(0, diff["summary"]["added"])
        self.assertEqual(0, diff["summary"]["removed"])
        self.assertEqual(1, diff["summary"]["changed"])
        self.assertEqual(1, diff["summary"]["requirement_deltas"])

    def test_endpoint_move_reports_adjacency_flip(self):
        headers = ["Origin", "Destination", "menuOption menuTarget objectID"]
        baseline = ["# " + "\t".join(headers), "1 1 0\t1 2 0\tOpen Door 123"]
        generated_rows = [{
            "Origin": "1 1 0", "Destination": "1 9 0",
            "menuOption menuTarget objectID": "Open Door 123",
        }]
        diff = self._diff(baseline, generated_rows, headers)
        self.assertEqual(0, diff["summary"]["added"])
        self.assertEqual(0, diff["summary"]["removed"])
        self.assertEqual(1, diff["summary"]["changed"])
        self.assertEqual(1, diff["summary"]["endpoint_moves"])
        self.assertEqual(1, diff["summary"]["adjacency_deltas"])

    def test_output_is_deterministic(self):
        table = read_tsv(FIXTURES / "upstream" / "transports.tsv")
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.tsv"
            second = Path(temp_dir) / "second.tsv"
            table.rows.sort(key=lambda row: identity("transports.tsv", row))
            write_tsv(first, table)
            write_tsv(second, table)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
