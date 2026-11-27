"""Tests for feed_url validation and the RSS feed collector."""

from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import yaml

from van_article_publishing_system.collection import feeds
from van_article_publishing_system.collection.feeds import (
    FeedCollectionError,
    FeedErrorKind,
    collect_rss_feeds,
    fetch_url,
    parse_rss,
)
from van_article_publishing_system.sources.registry import Source, load_source_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RSS_OK = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Example</title>
    <item>
      <title> First </title>
      <link>https://example.com/a</link>
      <guid>a-1</guid>
      <pubDate>Mon, 02 Nov 2026 09:00:00 GMT</pubDate>
      <dc:creator>Kim</dc:creator>
      <description>&lt;p&gt;summary&lt;/p&gt;</description>
      <content:encoded>full text</content:encoded>
    </item>
    <item><title>Second</title></item>
  </channel>
</rss>"""


def make_source(source_id: str = "s1", **overrides: object) -> Source:
    values: dict[str, object] = dict(
        source_id=source_id, name="Example", url="https://example.com/",
        source_type="foreign_media", region_language=None, collection_method="rss",
        priority=1, poll_interval_seconds=300, active=True, approved=True,
        usage_terms_confirmed=True, feed_url=f"https://example.com/{source_id}.xml",
    )
    values.update(overrides)
    return Source(**values)  # type: ignore[arg-type]


class RegistryFeedUrlTests(unittest.TestCase):
    def load(self, entries: list[dict]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.yaml"
            path.write_text(yaml.safe_dump({"sources": entries}), encoding="utf-8")
            return load_source_registry(path)

    def entry(self, **overrides: object) -> dict:
        entry = {
            "id": "s1", "name": "Example", "url": "https://example.com/",
            "feed_url": "https://example.com/feed.xml", "source_type": "foreign_media",
            "region_language": "English", "collection_method": "rss", "priority": 1,
            "poll_interval_seconds": 300, "active": True, "approved": True,
            "usage_terms_confirmed": True,
        }
        entry.update(overrides)
        return entry

    def test_planned_sources_still_load_without_feed_url(self) -> None:
        registry = load_source_registry(PROJECT_ROOT / "config" / "sources.yaml")
        self.assertEqual(registry.issues, ())
        self.assertEqual(len(registry.sources), 336)

    def test_feed_url_is_loaded(self) -> None:
        registry = self.load([self.entry()])
        self.assertEqual(registry.issues, ())
        self.assertEqual(registry.sources[0].feed_url, "https://example.com/feed.xml")

    def test_bad_feed_urls_are_rejected(self) -> None:
        for bad in ("file:///etc/passwd", "ftp://example.com/feed", "https://u:p@example.com/f",
                    "https://example.com/a b", "https://example.com/a\nb", "", 5):
            with self.subTest(feed_url=bad):
                registry = self.load([self.entry(feed_url=bad)])
                self.assertFalse(registry.sources)
                self.assertTrue(any("feed_url" in issue.message for issue in registry.issues))

    def test_active_rss_source_requires_feed_url(self) -> None:
        registry = self.load([self.entry(feed_url=None)])
        self.assertFalse(registry.sources)
        self.assertTrue(any("feed_url" in issue.message for issue in registry.issues))

    def test_inactive_source_may_omit_feed_url(self) -> None:
        registry = self.load([self.entry(feed_url=None, active=False)])
        self.assertEqual(registry.issues, ())


class ParseTests(unittest.TestCase):
    def test_items_are_returned_as_raw_text(self) -> None:
        items = parse_rss("s1", RSS_OK)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(
            (first.source_id, first.title, first.link, first.guid, first.author, first.content),
            ("s1", "First", "https://example.com/a", "a-1", "Kim", "full text"),
        )
        self.assertEqual(first.summary, "<p>summary</p>")
        self.assertIsNone(items[1].link)

    def test_empty_channel_is_valid(self) -> None:
        self.assertEqual(parse_rss("s1", b"<rss><channel></channel></rss>"), ())

    def test_item_limit(self) -> None:
        self.assertEqual(len(parse_rss("s1", RSS_OK, max_items=1)), 1)

    def test_non_http_links_are_dropped(self) -> None:
        body = b"<rss><channel><item><link>javascript:alert(1)</link></item></channel></rss>"
        self.assertIsNone(parse_rss("s1", body)[0].link)

    def test_invalid_documents(self) -> None:
        documents = {
            "not xml": b"<html><body>oops",
            "atom": b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>',
            "no channel": b"<rss></rss>",
            "empty": b"",
            "entity bomb": b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
                           b"<rss><channel><item><title>&b;</title></item></channel></rss>",
            "external entity": b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                               b"<rss><channel><item><title>&x;</title></item></channel></rss>",
        }
        for name, body in documents.items():
            with self.subTest(name=name):
                with self.assertRaises(FeedCollectionError) as ctx:
                    parse_rss("s1", body)
                self.assertEqual(ctx.exception.kind, FeedErrorKind.INVALID_FORMAT)


class CollectTests(unittest.TestCase):
    def test_valid_feed_returns_items(self) -> None:
        results = collect_rss_feeds([make_source()], fetch=lambda url: RSS_OK)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        self.assertEqual(len(results[0].items), 2)

    def test_sources_that_are_not_eligible_are_never_requested(self) -> None:
        requested: list[str] = []
        sources = [
            make_source("inactive", active=False),
            make_source("unapproved", approved=False),
            make_source("terms", usage_terms_confirmed=False),
            make_source("no-priority", priority=None),
            make_source("inactive-api", active=False, collection_method="api"),
        ]
        results = collect_rss_feeds(sources, fetch=lambda url: requested.append(url) or RSS_OK)
        self.assertEqual(requested, [])
        self.assertEqual(results, ())

    def test_non_rss_method_is_unsupported_and_not_requested(self) -> None:
        requested: list[str] = []
        results = collect_rss_feeds(
            [make_source("api-1", collection_method="api")],
            fetch=lambda url: requested.append(url) or RSS_OK,
        )
        self.assertEqual(requested, [])
        self.assertEqual(results[0].failure.kind, FeedErrorKind.UNSUPPORTED_METHOD)

    def test_missing_feed_url_is_reported(self) -> None:
        results = collect_rss_feeds([make_source(feed_url=None)], fetch=lambda url: RSS_OK)
        self.assertEqual(results[0].failure.kind, FeedErrorKind.INVALID_URL)

    def test_one_failing_feed_does_not_stop_the_others(self) -> None:
        def fetch(url: str) -> bytes:
            if url.endswith("net.xml"):
                raise FeedCollectionError(FeedErrorKind.NETWORK, "boom")
            if url.endswith("bad.xml"):
                return b"<html>not a feed"
            if url.endswith("bug.xml"):
                raise RuntimeError("unexpected")
            return RSS_OK

        sources = [make_source(name) for name in ("net", "bad", "bug", "good")]
        with self.assertLogs(feeds.logger, level="ERROR"):
            results = collect_rss_feeds(sources, fetch=fetch)
        self.assertEqual(
            [(r.source_id, r.failure.kind if r.failure else None) for r in results],
            [
                ("net", FeedErrorKind.NETWORK),
                ("bad", FeedErrorKind.INVALID_FORMAT),
                ("bug", FeedErrorKind.INTERNAL),
                ("good", None),
            ],
        )
        self.assertEqual(len(results[3].items), 2)
        self.assertNotIn("unexpected", results[2].failure.message)


class UrlGuardTests(unittest.TestCase):
    def resolve_to(self, *addresses: str):
        infos = [(2, 1, 6, "", (address, 0)) for address in addresses]
        return mock.patch.object(feeds.socket, "getaddrinfo", return_value=infos)

    def test_bad_schemes_and_credentials_are_blocked(self) -> None:
        for url in ("file:///etc/passwd", "ftp://example.com/x", "https://u:p@example.com/x", "http:///x"):
            with self.subTest(url=url):
                with self.assertRaises(FeedCollectionError) as ctx:
                    fetch_url(url)
                self.assertEqual(ctx.exception.kind, FeedErrorKind.INVALID_URL)

    def test_non_public_addresses_are_blocked(self) -> None:
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "172.16.0.1",
                        "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1"):
            with self.subTest(address=address), self.resolve_to(address):
                with self.assertRaises(FeedCollectionError) as ctx:
                    fetch_url("https://feeds.example.com/rss")
                self.assertEqual(ctx.exception.kind, FeedErrorKind.INVALID_URL)

    def test_one_private_address_among_public_ones_blocks_the_host(self) -> None:
        with self.resolve_to("93.184.216.34", "10.0.0.5"):
            with self.assertRaises(FeedCollectionError):
                feeds._ensure_public_url("https://feeds.example.com/rss")

    def test_public_address_is_allowed(self) -> None:
        with self.resolve_to("93.184.216.34"):
            feeds._ensure_public_url("https://feeds.example.com/rss")

    def test_dns_failure_is_a_network_error(self) -> None:
        with mock.patch.object(feeds.socket, "getaddrinfo", side_effect=OSError("no such host")):
            with self.assertRaises(FeedCollectionError) as ctx:
                feeds._ensure_public_url("https://feeds.example.com/rss")
        self.assertEqual(ctx.exception.kind, FeedErrorKind.NETWORK)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence test output
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(RSS_OK)
        elif self.path == "/err":
            self.send_response(500)
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 5000)
        elif self.path == "/redirect-ok":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", "/private")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


class HttpFetchTests(unittest.TestCase):
    """Real HTTP against a local server; the address guard is replaced so localhost is reachable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        def guard(url: str) -> None:
            if url.endswith("/private"):
                raise FeedCollectionError(FeedErrorKind.INVALID_URL, "blocked")

        patcher = mock.patch.object(feeds, "_ensure_public_url", side_effect=guard)
        patcher.start()
        self.addCleanup(patcher.stop)

    def error_kind(self, path: str, **kwargs: object) -> FeedErrorKind:
        with self.assertRaises(FeedCollectionError) as ctx:
            fetch_url(self.base + path, **kwargs)
        return ctx.exception.kind

    def test_success(self) -> None:
        self.assertEqual(fetch_url(self.base + "/ok"), RSS_OK)

    def test_redirect_is_followed(self) -> None:
        self.assertEqual(fetch_url(self.base + "/redirect-ok"), RSS_OK)

    def test_redirect_to_blocked_address_is_refused(self) -> None:
        self.assertEqual(self.error_kind("/redirect-private"), FeedErrorKind.INVALID_URL)

    def test_redirect_loop_is_a_network_error(self) -> None:
        self.assertEqual(self.error_kind("/loop"), FeedErrorKind.NETWORK)

    def test_http_error_status_is_a_network_error(self) -> None:
        self.assertEqual(self.error_kind("/err"), FeedErrorKind.NETWORK)
        self.assertEqual(self.error_kind("/missing"), FeedErrorKind.NETWORK)

    def test_oversized_response_is_rejected(self) -> None:
        self.assertEqual(self.error_kind("/big", max_bytes=1000), FeedErrorKind.INVALID_FORMAT)

    def test_connection_refused_is_a_network_error(self) -> None:
        with self.assertRaises(FeedCollectionError) as ctx:
            fetch_url("http://127.0.0.1:9/feed", timeout=2)
        self.assertEqual(ctx.exception.kind, FeedErrorKind.NETWORK)

    def test_collector_end_to_end(self) -> None:
        sources = [
            make_source("good", feed_url=self.base + "/ok"),
            make_source("down", feed_url=self.base + "/err"),
            make_source("good2", feed_url=self.base + "/redirect-ok"),
        ]
        results = collect_rss_feeds(sources)
        self.assertEqual([r.ok for r in results], [True, False, True])
        self.assertEqual(results[1].failure.kind, FeedErrorKind.NETWORK)


if __name__ == "__main__":
    unittest.main()
