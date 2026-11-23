# Issue #14 — durable operations log (reference implementation)

SQLite-backed event history, upload error classification, and a mock notification outbox. No external dependencies.

Run: `python -m unittest discover -s tests -v` from this folder.

## Integration notes
- This is a separate prototype. It does not yet hook into Issue #11's `ReviewService` or The Sheerit CMS.
- The Issue #11 service still uses in-memory state and caller-supplied roles; a trusted authentication layer and transactional persistence are prerequisites to production deployment.
- Never log raw HTTP headers, request bodies, access tokens, or unsanitized exception strings. Use controlled error codes and safe messages. The basic secret-string filter is defense in depth, not a comprehensive secret detector.
- Use a production outbox dispatcher for real notifications; this prototype only creates pending events and supports acknowledging delivery.
- Alert thresholds and channels, CMS API fields, and sensitive-article classification criteria require stakeholder confirmation.
- RSS normalization is Issue #3 (closed); main branch currently exposes `feeds.py` with raw `FeedItem`, not a normalized module. Confirm whether Issue #3 changes live on another branch before duplicating work.
