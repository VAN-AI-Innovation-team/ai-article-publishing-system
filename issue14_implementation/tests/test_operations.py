import tempfile
import unittest
from pathlib import Path
from operations import OperationsStore, OperationError

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'events.sqlite'
        self.store = OperationsStore(self.path)
    def tearDown(self): self.tmp.cleanup()
    def test_persists_history_across_restart(self):
        self.store.record('a1', 'edited', actor_id='editor1')
        self.store.record('a1', 'approved', actor_id='chief')
        self.assertEqual([e['event_type'] for e in OperationsStore(self.path).history('a1')], ['edited','approved'])
    def test_upload_failure_creates_alert(self):
        self.store.record('a1', 'upload_failed', outcome='failure', error_type='timeout', error_message='CMS timeout')
        alerts = self.store.pending_alerts()
        self.assertEqual(len(alerts),1)
        self.store.mark_alert_delivered(alerts[0]['alert_id'])
        self.assertEqual(self.store.pending_alerts(),[])
    def test_sensitive_alert_has_evidence(self):
        with self.assertRaises(OperationError): self.store.record('a1','sensitive_flagged')
        self.store.record('a1','sensitive_flagged',evidence_ref='report:17')
        self.assertEqual(self.store.pending_alerts()[0]['evidence_ref'],'report:17')
    def test_secret_like_message_rejected(self):
        with self.assertRaises(OperationError):
            self.store.record('a1','upload_failed',outcome='failure',error_type='auth',error_message='token=secret')
        self.assertEqual(self.store.history('a1'),[])
    def test_invalid_event_rejected(self):
        with self.assertRaises(OperationError): self.store.record('a1','anything')
    def test_article_separation(self):
        self.store.record('a1','edited')
        self.store.record('a2','rejected')
        self.assertEqual(len(self.store.history('a1')),1)
if __name__=='__main__': unittest.main()
