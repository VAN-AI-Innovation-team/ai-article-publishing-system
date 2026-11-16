import unittest
from editorial_review import Article, ReviewError, ReviewService


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.s = ReviewService()
        self.s.add(Article('a1', 'Title', 'Lead', 'Body', 'Summary'))

    def test_edit_approve_and_history(self):
        edited = self.s.edit('a1', 'writer', 'editor', 1, title='New title')
        self.assertEqual((edited.status, edited.revision), ('editing', 2))
        self.s.decide('a1', 'chief', 'approver', 2, 'approve')
        self.assertTrue(self.s.eligible_for_cms('a1'))
        self.assertEqual([e.action for e in self.s.history('a1')], ['edit', 'approve'])

    def test_approved_edit_invalidates_approval(self):
        self.s.decide('a1', 'chief', 'approver', 1, 'approve')
        self.s.edit('a1', 'writer', 'editor', 1, body='Changed')
        self.assertFalse(self.s.eligible_for_cms('a1'))
        self.assertIsNone(self.s.get('a1').approved_revision)

    def test_unauthorized_approval_preserves_data(self):
        before = self.s.get('a1')
        with self.assertRaises(ReviewError):
            self.s.decide('a1', 'writer', 'editor', 1, 'approve')
        self.assertEqual(self.s.get('a1'), before)
        self.assertEqual(self.s.history('a1'), ())

    def test_rejection_requires_reason(self):
        with self.assertRaises(ReviewError):
            self.s.decide('a1', 'chief', 'approver', 1, 'reject')
        self.assertEqual(self.s.get('a1').status, 'pending_review')
        rejected = self.s.decide('a1', 'chief', 'approver', 1, 'reject', 'Missing evidence')
        self.assertEqual(rejected.status, 'rejected')

    def test_stale_revision_preserves_data(self):
        self.s.edit('a1', 'writer', 'editor', 1, title='Updated')
        before = self.s.get('a1')
        with self.assertRaises(ReviewError):
            self.s.edit('a1', 'writer', 'editor', 1, title='Stale')
        self.assertEqual(self.s.get('a1'), before)

    def test_invalid_transition(self):
        self.s.decide('a1', 'chief', 'approver', 1, 'approve')
        with self.assertRaises(ReviewError):
            self.s.decide('a1', 'chief', 'approver', 1, 'reject', 'No')
        self.assertTrue(self.s.eligible_for_cms('a1'))

    def test_rejected_article_can_be_revised(self):
        self.s.decide('a1', 'chief', 'approver', 1, 'reject', 'Needs edits')
        revised = self.s.edit('a1', 'writer', 'editor', 1, body='Corrected')
        self.assertEqual(revised.status, 'editing')
        self.s.decide('a1', 'chief', 'approver', 2, 'approve')
        self.assertTrue(self.s.eligible_for_cms('a1'))

    def test_noop_edit_does_not_invalidate_approval(self):
        self.s.decide('a1', 'chief', 'approver', 1, 'approve')
        self.s.edit('a1', 'writer', 'editor', 1, title='Title')
        self.assertTrue(self.s.eligible_for_cms('a1'))


if __name__ == '__main__':
    unittest.main()
