"""Load and validate the approved source registry.

This module validates configuration only. It does not fetch source content or
schedule polling jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml


SUPPORTED_COLLECTION_METHODS = frozenset({"rss", "api"})
SUPPORTED_PRIORITIES = frozenset({1, 2, 3})
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SOURCE_FIELDS = frozenset(
    {
        "id",
        "name",
        "url",
        "source_type",
        "region_language",
        "collection_method",
        "priority",
        "poll_interval_seconds",
        "active",
        "approved",
        "usage_terms_confirmed",
    }
)


@dataclass(frozen=True, slots=True)
class Source:
    """A validated source configuration entry."""

    source_id: str
    name: str
    url: str
    source_type: str
    region_language: str | None
    collection_method: str | None
    priority: int | None
    poll_interval_seconds: int | None
    active: bool
    approved: bool
    usage_terms_confirmed: bool

    @property
    def eligible_for_collection(self) -> bool:
        """Whether this registered source is both approved and enabled."""

        return (
            self.active
            and self.approved
            and self.usage_terms_confirmed
            and self.collection_method in SUPPORTED_COLLECTION_METHODS
            and self.priority in SUPPORTED_PRIORITIES
            and self.poll_interval_seconds is not None
            and self.poll_interval_seconds > 0
        )


@dataclass(frozen=True, slots=True)
class SourceIssue:
    """A validation issue, associated with a source ID when available."""

    source_id: str | None
    message: str


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """Validated registry entries and any errors found in the same file."""

    sources: tuple[Source, ...]
    issues: tuple[SourceIssue, ...]

    @property
    def eligible_sources(self) -> tuple[Source, ...]:
        """Return only sources explicitly enabled and approved for use."""

        return tuple(source for source in self.sources if source.eligible_for_collection)


class SourceRegistryLoadError(ValueError):
    """Raised when the registry file cannot be read or parsed as YAML."""


def load_source_registry(path: str | Path) -> SourceRegistry:
    """Load YAML and validate every source entry.

    Valid entries are returned even if other entries are invalid. Validation
    errors identify the affected source ID where one can be read safely.
    """

    registry_path = Path(path)
    try:
        raw_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceRegistryLoadError(f"Cannot read source registry: {exc}") from exc

    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise SourceRegistryLoadError(f"Invalid YAML: {exc}") from exc

    if not isinstance(document, dict):
        return SourceRegistry((), (SourceIssue(None, "Top-level YAML value must be a mapping."),))

    unexpected_top_level = set(document) - {"sources"}
    if unexpected_top_level:
        unexpected_names = ", ".join(sorted(str(key) for key in unexpected_top_level))
        return SourceRegistry(
            (),
            (SourceIssue(None, f"Unsupported top-level field(s): {unexpected_names}."),),
        )

    raw_sources = document.get("sources")
    if not isinstance(raw_sources, list):
        return SourceRegistry((), (SourceIssue(None, "'sources' must be a list."),))

    sources: list[Source] = []
    issues: list[SourceIssue] = []
    seen_ids: set[str] = set()

    for index, raw_source in enumerate(raw_sources):
        fallback_id = f"entry-{index + 1}"
        if not isinstance(raw_source, dict):
            issues.append(SourceIssue(fallback_id, "Source entry must be a mapping."))
            continue

        source_id = raw_source.get("id")
        issue_id = source_id.strip() if isinstance(source_id, str) and source_id.strip() else fallback_id
        entry_issues: list[str] = []

        unexpected_fields = set(raw_source) - _SOURCE_FIELDS
        if unexpected_fields:
            unexpected_names = ", ".join(sorted(str(key) for key in unexpected_fields))
            entry_issues.append(f"Unsupported field(s): {unexpected_names}.")

        required_strings = {
            "id": source_id,
            "name": raw_source.get("name"),
            "url": raw_source.get("url"),
            "source_type": raw_source.get("source_type"),
      
        }
        for field, value in required_strings.items():
            if not isinstance(value, str) or not value.strip():
                entry_issues.append(f"'{field}' must be a non-empty string.")

        region_language = raw_source.get("region_language")
        if region_language is not None and (
            not isinstance(region_language, str) or not region_language.strip()
        ):
            entry_issues.append("'region_language' must be a non-empty string when provided.")

        if isinstance(source_id, str) and source_id.strip():
            if not _SOURCE_ID_PATTERN.fullmatch(source_id.strip()):
                entry_issues.append("'id' may contain letters, digits, underscores, and hyphens only.")
            if source_id.strip() in seen_ids:
                entry_issues.append("'id' is duplicated in the registry.")
            seen_ids.add(source_id.strip())

        url_value = raw_source.get("url")
        if isinstance(url_value, str) and url_value.strip():
            try:
                parsed_url = urlsplit(url_value.strip())
                port = parsed_url.port
                valid_url = (
                    parsed_url.scheme in {"http", "https"}
                    and bool(parsed_url.hostname)
                    and parsed_url.username is None
                    and parsed_url.password is None
                    and (port is None or 0 <= port <= 65535)
                )
            except ValueError:
                valid_url = False
            if not valid_url:
                entry_issues.append("'url' must be an absolute HTTP(S) URL without embedded credentials.")

        collection_method = raw_source.get("collection_method")
        if collection_method is not None:
            if not isinstance(collection_method, str) or collection_method not in SUPPORTED_COLLECTION_METHODS:
                allowed_methods = ", ".join(sorted(SUPPORTED_COLLECTION_METHODS))
                entry_issues.append(f"'collection_method' must be one of: {allowed_methods}.")

        priority = raw_source.get("priority")
        if priority is not None and (type(priority) is not int or priority not in SUPPORTED_PRIORITIES):
            entry_issues.append("'priority' must be an integer from 1 to 3.")

        poll_interval_seconds = raw_source.get("poll_interval_seconds")
        if poll_interval_seconds is not None and (
            type(poll_interval_seconds) is not int or poll_interval_seconds <= 0
        ):
            entry_issues.append("'poll_interval_seconds' must be a positive integer.")

        active = raw_source.get("active")
        if type(active) is not bool:
            entry_issues.append("'active' must be true or false.")

        approved = raw_source.get("approved")
        if type(approved) is not bool:
            entry_issues.append("'approved' must be true or false.")

        usage_terms_confirmed = raw_source.get("usage_terms_confirmed")
        if type(usage_terms_confirmed) is not bool:
            entry_issues.append("'usage_terms_confirmed' must be true or false.")

        if active is True:
            if collection_method is None:
                entry_issues.append("An active source must have a collection_method.")
            if priority is None:
                entry_issues.append("An active source must have a priority.")
            if poll_interval_seconds is None:
                entry_issues.append("An active source must have a poll_interval_seconds value.")

        if entry_issues:
            issues.extend(SourceIssue(issue_id, message) for message in entry_issues)
            continue

        sources.append(
            Source(
                source_id=source_id.strip(),
                name=raw_source["name"].strip(),
                url=raw_source["url"].strip(),
                source_type=raw_source["source_type"].strip(),
                region_language=(region_language.strip() if region_language else None),
                collection_method=collection_method,
                priority=priority,
                poll_interval_seconds=poll_interval_seconds,
                active=active,
                approved=approved,
                usage_terms_confirmed=usage_terms_confirmed,
            )
        )

    return SourceRegistry(tuple(sources), tuple(issues))
