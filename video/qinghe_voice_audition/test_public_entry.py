from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
import bootstrap


class PublicEntryTests(unittest.TestCase):
    def test_example_is_inert_and_safe_trigger_can_be_validated(self):
        d=json.loads((Path(__file__).parent/'execute_once.example.json').read_text())
        with self.assertRaises(ValueError):bootstrap.validate_trigger(d,datetime.now(timezone.utc))
        d.update(zero_added_cost_confirmed=True,cost_evidence_utc=datetime.now(timezone.utc).isoformat())
        bootstrap.validate_trigger(d,datetime.now(timezone.utc))

    def test_no_public_media_or_private_content_fields(self):
        r=Path(__file__).parent;s=(r/'workflow.qinghe_voice_audition_once.yml').read_text()
        self.assertNotIn('upload-artifact',s)
        self.assertIn('timeout-minutes: 10',s)
        self.assertNotIn('drive.google.com',s)
        self.assertNotIn('speaker',json.loads((r/'execute_once.example.json').read_text()))


if __name__=='__main__':unittest.main()
