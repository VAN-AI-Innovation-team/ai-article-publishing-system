
"""Normalize raw RSS feed items into a common article candidate format."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Iterable
from urllib.parse import urlsplit

from ..collection.feeds import FeedItem


_BLOCK_TAGS = {
    "address", "article", "blockquote", "div", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "li", "ol", "p", "section", "table", "tr", "ul",
    "br", "hr",
}

_IGNORED_TAGS = {"script", "style"}


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML while ignoring script and style."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return

        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def clean_text(value: str | None) -> str:
    """Remove HTML markup and normalize unnecessary whitespace.

    Empty or missing values become an empty string.
    """

    if not value:
        return ""

    parser = _HTMLTextExtractor()

    try:
        parser.feed(value)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        # Keep the input readable even if malformed HTML breaks parsing.
        text = value

    return re.sub(r"\s+", " ", text).strip()


def _is_valid_article_url(value: str) -> bool:
    """Check that the article URL is an absolute HTTP(S) URL."""

    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port is not None or (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.port is None
            )
        )
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class NormalizedFeedItem:
    """A common article candidate format independent of RSS structure."""

    source_id: str
    title: str
    original_url: str
    published_at: str
    author: str
    summary: str
    body: str
    guid: str
    full_text_collected: bool


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalization outcome for one raw RSS item."""

    item: NormalizedFeedItem | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.item is not None and not self.errors


def normalize_feed_item(item: FeedItem) -> NormalizationResult:
    """Convert one raw RSS item into the common article format.

    Required fields:
    - source_id
    - title
    - link

    Optional fields are represented as empty strings.

    RSS content is treated as the article body. If content is missing,
    summary is retained separately and full_text_collected is False.
    """

    source_id = clean_text(item.source_id)
    title = clean_text(item.title)
    original_url = (item.link or "").strip()

    errors: list[str] = []

    if not source_id:
        errors.append("Missing required field: source_id.")

    if not title:
        errors.append("Missing required field: title.")

    if not original_url:
        errors.append("Missing required field: link.")
    elif not _is_valid_article_url(original_url):
        errors.append("Invalid article URL: link must be an absolute HTTP(S) URL.")

    if errors:
        return NormalizationResult(item=None, errors=tuple(errors))

    summary = clean_text(item.summary)
    body = clean_text(item.content)

    return NormalizationResult(
        item=NormalizedFeedItem(
            source_id=source_id,
            title=title,
            original_url=original_url,
            published_at=clean_text(item.published),
            author=clean_text(item.author),
            summary=summary,
            body=body,
            guid=clean_text(item.guid),
            full_text_collected=bool(body),
        ),
        errors=(),
    )


def normalize_feed_items(
    items: Iterable[FeedItem],
) -> tuple[NormalizationResult, ...]:
    """Normalize multiple RSS items without stopping on invalid entries."""

    return tuple(normalize_feed_item(item) for item in items)
