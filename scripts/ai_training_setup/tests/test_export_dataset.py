import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "export_dataset.py"
SPEC = importlib.util.spec_from_file_location("export_dataset", MODULE_PATH)
export_dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_dataset)


class ExportDatasetTests(unittest.TestCase):
    def test_consecutive_user_turns_are_losslessly_roundtripped(self):
        turns = [
            {"role": "user", "content": "原文一\n含分隔符"},
            {"role": "user", "content": "原文二"},
            {"role": "assistant", "content": "历史回复"},
            {"role": "user", "content": "当前追问"},
        ]
        packed, trace = export_dataset.pack_messages(turns)
        self.assertEqual(export_dataset.unpack_messages(packed), turns)
        self.assertTrue(trace[0]["reversible_block"])
        self.assertEqual(trace[0]["source_turn_end_exclusive"], 2)

    def test_target_json_preserves_frozen_semantics(self):
        sample = export_dataset.read_json(export_dataset.CANONICAL / "samples.json")[0]
        record, trace = export_dataset.export_record(sample)
        self.assertEqual(
            __import__("json").loads(record["conversations"][-1]["content"]),
            sample["expected"]["model_output"],
        )
        self.assertTrue(trace["history_roundtrip_verified"])
        self.assertEqual(set(record), {"system", "conversations"})


if __name__ == "__main__":
    unittest.main()
