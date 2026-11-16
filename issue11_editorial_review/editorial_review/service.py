"""Standalone editorial review state machine for GitHub issue #11.

In-memory reference implementation; persistence and authentication adapters must be
integrated before production use. No CMS publishing is performed here.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Optional


class ReviewError(Exception):
    pass


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    lead: str
    body: str
    summary: str
    status: str = 'pending_review'
    revision: int = 1
    approved_revision: Optional[int] = None


@dataclass(frozen=True)
class ReviewEvent:
    article_id: str
    action: str
    actor: str
    at: str
    before: Article
    after: Article
    reason: Optional[str] = None


class ReviewService:
    """Atomic in-memory operations with explicit actor roles and revision checks.

    Caller-supplied roles are for testing only; a trusted auth layer must provide
    them in production. State is not durable across process restarts.
    """
    def __init__(self):
        self._articles: dict[str, Article] = {}
        self._events: list[ReviewEvent] = []
        self._lock = RLock()

    def add(self, article: Article):
        with self._lock:
            if not article.id or article.id in self._articles:
                raise ReviewError('Article ID missing or already exists')
            if article.status != 'pending_review' or article.revision != 1 or article.approved_revision is not None:
                raise ReviewError('New article must start pending review at revision 1')
            self._articles[article.id] = article

    def get(self, article_id: str) -> Article:
        with self._lock:
            try:
                return self._articles[article_id]
            except KeyError as exc:
                raise ReviewError('Article not found') from exc

    def history(self, article_id: str) -> tuple[ReviewEvent, ...]:
        with self._lock:
            self.get(article_id)
            return tuple(e for e in self._events if e.article_id == article_id)

    def _require_editor(self, actor: str, role: str):
        if not actor or role not in ('editor', 'approver'):
            raise ReviewError('Editor permission required')

    def _record(self, before: Article, after: Article, action: str, actor: str, reason=None):
        self._articles[before.id] = after
        self._events.append(ReviewEvent(before.id, action, actor,
                                        datetime.now(timezone.utc).isoformat(), before, after, reason))
        return after

    def edit(self, article_id: str, actor: str, role: str, expected_revision: int, **changes):
        with self._lock:
            self._require_editor(actor, role)
            before = self.get(article_id)
            if before.revision != expected_revision:
                raise ReviewError('Revision conflict')
            if before.status not in ('pending_review', 'editing', 'approved', 'rejected'):
                raise ReviewError('Invalid state')
            allowed = {'title', 'lead', 'body', 'summary'}
            if not changes or set(changes) - allowed:
                raise ReviewError('Invalid edit fields')
            if any(not isinstance(v, str) or not v.strip() for v in changes.values()):
                raise ReviewError('Article fields must be non-empty strings')
            if all(getattr(before, k) == v for k, v in changes.items()):
                return before
            after = replace(before, **changes, status='editing',
                            revision=before.revision + 1, approved_revision=None)
            return self._record(before, after, 'edit', actor)

    def decide(self, article_id: str, actor: str, role: str, expected_revision: int,
               decision: str, reason: Optional[str] = None):
        with self._lock:
            if not actor or role != 'approver':
                raise ReviewError('Approver permission required')
            before = self.get(article_id)
            if before.revision != expected_revision:
                raise ReviewError('Revision conflict')
            if before.status not in ('pending_review', 'editing'):
                raise ReviewError('Invalid state transition')
            if decision not in ('approve', 'reject'):
                raise ReviewError('Invalid decision')
            if decision == 'reject' and (not isinstance(reason, str) or not reason.strip()):
                raise ReviewError('Rejection reason required')
            if decision == 'approve':
                after = replace(before, status='approved', approved_revision=before.revision)
            else:
                after = replace(before, status='rejected', approved_revision=None)
            return self._record(before, after, decision, actor, reason)

    def eligible_for_cms(self, article_id: str) -> bool:
        with self._lock:
            article = self.get(article_id)
            return article.status == 'approved' and article.approved_revision == article.revision
