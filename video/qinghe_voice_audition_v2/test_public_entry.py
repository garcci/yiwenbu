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
        r=Path(__file__).parent;s=(r/'workflow.qinghe_voice_audition_v2_once.yml').read_text()
        self.assertNotIn('upload-artifact',s)
        self.assertIn('timeout-minutes: 10',s)
        self.assertNotIn('drive.google.com',s)
        self.assertNotIn('speaker',json.loads((r/'execute_once.example.json').read_text()))

    def test_actual_workflow_supplies_every_v2_package_environment_read_by_bootstrap(self):
        import re
        root=Path(__file__).parent
        source=(root/'bootstrap.py').read_text()
        workflow=(root/'workflow.qinghe_voice_audition_v2_once.yml').read_text()
        required=set(re.findall(r"os\.environ\['(AUDITION_V2_PRIVATE_PACKAGE_(?:ID|SHA256))'\]",source))
        provided=dict(re.findall(r"^          (AUDITION_[A-Z0-9_]+): \$\{\{ secrets\.([A-Z0-9_]+) \}\}$",workflow,re.MULTILINE))
        self.assertEqual(required,{'AUDITION_V2_PRIVATE_PACKAGE_ID','AUDITION_V2_PRIVATE_PACKAGE_SHA256'})
        self.assertTrue(required.issubset(provided))
        self.assertTrue(all(provided[key]==key for key in required))
        self.assertIn('GDRIVE_FOLDER_ID: ${{ secrets.AUDITION_DRIVE_FOLDER_ID }}',workflow)
        self.assertIn('video/qinghe_voice_audition_v2/execute_once.json',workflow)
        self.assertNotIn('video/qinghe_voice_audition/execute_once.json',workflow)


if __name__=='__main__':unittest.main()
