"""Tests for the source registry loader and eligibility rules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from van_article_publishing_system.sources import load_source_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SourceRegistryTests(unittest.TestCase):
    def load_entries(self, entries: list[dict[str, object]]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.yaml"
            path.write_text(yaml.safe_dump({"sources": entries}), encoding="utf-8")
            return load_source_registry(path)

    def valid_source(self, **overrides: object) -> dict[str, object]:
        source: dict[str, object] = {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com/news",
            "source_type": "foreign_media",
            "region_language": "English",
            "collection_method": "rss",
            "priority": 1,
            "poll_interval_seconds": 300,
            "active": True,
            "approved": True,
            "usage_terms_confirmed": True,
        }
        source.update(overrides)
        return source

    def test_planned_sources_load_as_inactive_pending_entries(self) -> None:
        registry = load_source_registry(PROJECT_ROOT / "config" / "sources.yaml")

        self.assertEqual(registry.issues, ())
        self.assertEqual(len(registry.sources), 336)
        self.assertEqual(registry.eligible_sources, ())
        self.assertTrue(all(not source.active for source in registry.sources))
        self.assertTrue(all(not source.usage_terms_confirmed for source in registry.sources))

    def test_configured_approved_source_is_eligible(self) -> None:
        registry = self.load_entries([self.valid_source()])

        self.assertEqual(registry.issues, ())
        self.assertEqual([source.source_id for source in registry.eligible_sources], ["source-1"])

    def test_source_needs_all_approval_conditions_to_be_eligible(self) -> None:
        for override in (
            {"active": False},
            {"approved": False},
            {"usage_terms_confirmed": False},
            {"collection_method": "unsupported"},
            {"priority": 4},
            {"poll_interval_seconds": 0},
        ):
            with self.subTest(override=override):
                registry = self.load_entries([self.valid_source(**override)])
                self.assertFalse(registry.eligible_sources)

    def test_invalid_source_has_source_specific_errors_without_hiding_valid_sibling(self) -> None:
        invalid = self.valid_source(id="bad-source", url="file:///etc/passwd", collection_method="scrape")
        registry = self.load_entries([invalid, self.valid_source(id="good-source")])

        self.assertEqual([source.source_id for source in registry.sources], ["good-source"])
        self.assertTrue(any(issue.source_id == "bad-source" and "url" in issue.message for issue in registry.issues))
        self.assertTrue(any(issue.source_id == "bad-source" and "collection_method" in issue.message for issue in registry.issues))

    def test_url_with_embedded_credentials_is_rejected(self) -> None:
        registry = self.load_entries([self.valid_source(url="https://user:secret@example.com/feed")])

        self.assertFalse(registry.sources)
        self.assertTrue(any("url" in issue.message for issue in registry.issues))

    def test_unsafe_yaml_python_tag_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.yaml"
            path.write_text(
                'sources: !!python/object/apply:os.system ["echo unsafe"]\n',
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_source_registry(path)


if __name__ == "__main__":
    unittest.main()
