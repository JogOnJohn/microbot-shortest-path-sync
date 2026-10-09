import unittest
from pathlib import Path

from transport_sync.sync import Table, apply_overrides, read_tsv


class ContractLadderOverridesTest(unittest.TestCase):
    def test_contract_ladders_survive_generation_with_their_runtime_ids(self):
        path = Path(__file__).resolve().parents[1] / "transport_sync/local_overrides.tsv"
        overrides = read_tsv(path).rows
        origins = {"2616 3315 0", "2616 3315 1", "1766 3620 0",
                   "1766 3620 1", "1787 3592 0", "1787 3592 1"}
        ladders = [row for row in overrides if row["Category"] == "transports.tsv"
                   and row["Origin"] in origins]
        table = Table(["Origin", "Destination", "menuOption menuTarget objectID", "Duration"], [])
        apply_overrides({"transports.tsv": table}, ladders)
        self.assertEqual(6, len(table.rows))
        expected_ids = {"2616 3315 0": "16683", "2616 3315 1": "16679",
                        "1766 3620 0": "11794", "1766 3620 1": "11802",
                        "1787 3592 0": "11794", "1787 3592 1": "11802"}
        for row in table.rows:
            x, y, plane = row["Origin"].split()
            self.assertEqual(f"{x} {y} {1 - int(plane)}", row["Destination"])
            action = "Climb-up" if plane == "0" else "Climb-down"
            self.assertEqual(f"{action} Ladder {expected_ids[row['Origin']]}",
                             row["menuOption menuTarget objectID"])
            self.assertEqual("2", row["Duration"])
