
"""Tests for RSS item normalization and HTML cleaning."""

from __future__ import annotations

import unittest

from van_article_publishing_system.collection.feeds import FeedItem
from van_article_publishing_system.processing.normalization import (
    clean_text,
    normalize_feed_item,
    normalize_feed_items,
)


def make_item(**overrides: object) -> FeedItem:
    values = {
        "source_id": "source-1",
        "title": "Example Article",
        "link": "https://example.com/article/1",
        "guid": "article-1",
        "published": "Mon, 02 Nov 2026 09:00:00 GMT",
        "author": "Kim",
        "summary": "<p>Article summary</p>",
        "content": "<div>Full article body</div>",
    }
    values.update(overrides)
    return FeedItem(**values)


class CleanTextTests(unittest.TestCase):

    def test_html_tags_are_removed(self) -> None:
        self.assertEqual(
            clean_text("<p>Hello <strong>World</strong></p>"),
            "Hello World",
        )

    def test_html_entities_are_decoded(self) -> None:
        self.assertEqual(
            clean_text("Tom &amp; Jerry"),
            "Tom & Jerry",
        )

    def test_script_and_style_are_removed(self) -> None:
        html = (
            "<p>Article</p>"
            "<script>alert('test')</script>"
            "<style>.hidden { display: none; }</style>"
            "<p>Content</p>"
        )
        self.assertEqual(clean_text(html), "Article Content")

    def test_extra_whitespace_is_normalized(self) -> None:
        self.assertEqual(
            clean_text("  Hello \n\t World   "),
            "Hello World",
        )

    def test_empty_value_returns_empty_string(self) -> None:
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(""), "")


class NormalizeFeedItemTests(unittest.TestCase):

    def test_valid_item_is_normalized(self) -> None:
        result = normalize_feed_item(make_item())

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, ())

        item = result.item
        self.assertIsNotNone(item)

        self.assertEqual(item.source_id, "source-1")
        self.assertEqual(item.title, "Example Article")
        self.assertEqual(
            item.original_url,
            "https://example.com/article/1",
        )
        self.assertEqual(
            item.published_at,
            "Mon, 02 Nov 2026 09:00:00 GMT",
        )
        self.assertEqual(item.author, "Kim")
        self.assertEqual(item.summary, "Article summary")
        self.assertEqual(item.body, "Full article body")
        self.assertEqual(item.guid, "article-1")
        self.assertTrue(item.full_text_collected)

    def test_missing_optional_fields_become_empty_strings(self) -> None:
        result = normalize_feed_item(
            make_item(
                guid=None,
                published=None,
                author=None,
                summary=None,
            )
        )

        self.assertTrue(result.ok)

        item = result.item
        self.assertIsNotNone(item)

        self.assertEqual(item.guid, "")
        self.assertEqual(item.published_at, "")
        self.assertEqual(item.author, "")
        self.assertEqual(item.summary, "")

    def test_missing_full_text_is_marked(self) -> None:
        result = normalize_feed_item(
            make_item(content=None, summary="<p>Only summary</p>")
        )

        self.assertTrue(result.ok)

        item = result.item
        self.assertIsNotNone(item)

        self.assertEqual(item.body, "")
        self.assertEqual(item.summary, "Only summary")
        self.assertFalse(item.full_text_collected)

    def test_empty_full_text_is_marked_as_not_collected(self) -> None:
        result = normalize_feed_item(
            make_item(content="<p>   </p>")
        )

        self.assertTrue(result.ok)
        self.assertFalse(result.item.full_text_collected)
        self.assertEqual(result.item.body, "")

    def test_missing_title_is_an_error(self) -> None:
        result = normalize_feed_item(make_item(title=None))

        self.assertFalse(result.ok)
        self.assertIsNone(result.item)
        self.assertTrue(
            any("title" in error for error in result.errors)
        )

    def test_missing_source_id_is_an_error(self) -> None:
        result = normalize_feed_item(make_item(source_id=""))

        self.assertFalse(result.ok)
        self.assertTrue(
            any("source_id" in error for error in result.errors)
        )

    def test_missing_link_is_an_error(self) -> None:
        result = normalize_feed_item(make_item(link=None))

        self.assertFalse(result.ok)
        self.assertTrue(
            any("link" in error for error in result.errors)
        )

    def test_invalid_url_is_an_error(self) -> None:
        for url in (
            "ftp://example.com/article",
            "javascript:alert(1)",
            "https://user:password@example.com/article",
            "not-a-url",
        ):
            with self.subTest(url=url):
                result = normalize_feed_item(make_item(link=url))
                self.assertFalse(result.ok)
                self.assertIsNone(result.item)

    def test_html_in_title_is_cleaned(self) -> None:
        result = normalize_feed_item(
            make_item(title="<b>Breaking</b> News")
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.item.title, "Breaking News")


class NormalizeFeedItemsTests(unittest.TestCase):

    def test_multiple_items_are_processed_independently(self) -> None:
        items = [
            make_item(title="Article 1"),
            make_item(title=None),
            make_item(title="Article 3"),
        ]

        results = normalize_feed_items(items)

        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertTrue(results[2].ok)

    def test_empty_input_returns_empty_tuple(self) -> None:
        self.assertEqual(normalize_feed_items([]), ())


if __name__ == "__main__":
    unittest.main()
