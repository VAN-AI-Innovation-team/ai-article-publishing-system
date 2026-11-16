# Issue #11 — Editorial Review State Management

Standalone Python reference module for article editing, approval, rejection and revision history.
No external dependencies. Does not modify existing repository files.

## Run tests

From this folder:

```bash
python -m unittest discover -s tests -v
```

## Usage

```python
from editorial_review import Article, ReviewService

service = ReviewService()
service.add(Article('news-1', 'Title', 'Lead', 'Body', 'Summary'))
service.edit('news-1', 'alice', 'editor', 1, title='Updated title')
service.decide('news-1', 'bob', 'approver', 2, 'approve')
assert service.eligible_for_cms('news-1')
```

## Integration notes

- This is a **prototype**, not a production approval gate. Storage and event history are in-memory and disappear on restart.
- Actor roles are supplied by the caller. A trusted authentication/authorization layer must derive them from authenticated identities.
- Production persistence must atomically update article state and append audit events in one transaction.
- CMS upload must independently re-check the persisted approved revision at upload time.
- No API, database, or CMS interface is assumed; agree on interfaces with the other developers before integration.
- This module does not publish or upload anything to The Sheerit.
