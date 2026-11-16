"""Collect raw items from registered RSS feeds.

Scope (issue #2): request the feed of every eligible RSS source and return its
items. Items are returned as found in the feed; cleaning and a common format
are a separate step. Scheduling, storage, retries and de-duplication are also
separate steps.

Safety rules enforced here:
* Only sources that are active, approved and have confirmed usage terms are
  requested (``Source.eligible_for_collection``).
* Only RSS is supported. Other methods are reported as unsupported; no site is
  crawled.
* Feed URLs must point to public internet hosts (blocks requests to internal
  networks), including after every redirect.
* Response size and total download time are limited.
* XML is parsed with ``defusedxml`` (no DTDs, entities or external references).
* One failing source never stops the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import islice
from typing import Callable, Iterable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urljoin, urlsplit
import http.client
import ipaddress
import logging
import socket
import time

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeElementTree

from .sources import Source

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_ITEMS_PER_FEED = 500
MAX_REDIRECTS = 3
USER_AGENT = "van-article-publishing-system/0.1 (RSS collector)"

_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"


class FeedErrorKind(str, Enum):
    """Why a source's feed could not be collected."""

    NETWORK = "network"  # DNS, connection, timeout or HTTP error
    INVALID_FORMAT = "invalid_format"  # not a valid RSS 2.0 document, or too large
    UNSUPPORTED_METHOD = "unsupported_method"  # collection method is not rss
    INVALID_URL = "invalid_url"  # missing, malformed or non-public feed URL
    INTERNAL = "internal"  # unexpected bug; details are in the log


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One raw RSS item. Values are the feed's own text; nothing is cleaned."""

    source_id: str
    title: str | None
    link: str | None
    guid: str | None
    published: str | None
    author: str | None
    summary: str | None
    content: str | None


@dataclass(frozen=True, slots=True)
class FeedFailure:
    kind: FeedErrorKind
    message: str


@dataclass(frozen=True, slots=True)
class FeedResult:
    """Collection outcome for one source: items on success, a failure otherwise."""

    source_id: str
    items: tuple[FeedItem, ...] = ()
    failure: FeedFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


class FeedCollectionError(Exception):
    """A classified, expected failure while collecting one feed."""

    def __init__(self, kind: FeedErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def _ensure_public_url(url: str) -> None:
    """Raise unless ``url`` is HTTP(S) and every address its host resolves to is public."""

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FeedCollectionError(FeedErrorKind.INVALID_URL, "Feed URL is malformed.") from exc

    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise FeedCollectionError(
            FeedErrorKind.INVALID_URL,
            "Feed URL must be an absolute HTTP(S) URL without credentials.",
        )

    default_port = 443 if parts.scheme == "https" else 80
    try:
        infos = socket.getaddrinfo(parts.hostname, port or default_port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FeedCollectionError(FeedErrorKind.NETWORK, f"DNS lookup failed: {exc}") from exc

    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise FeedCollectionError(FeedErrorKind.NETWORK, "DNS lookup returned no addresses.")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise FeedCollectionError(
                FeedErrorKind.INVALID_URL, "Feed host resolved to an unreadable address."
            ) from exc
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise FeedCollectionError(
                FeedErrorKind.INVALID_URL, "Feed host resolves to a non-public address."
            )


class _SafeRedirectHandler(urlrequest.HTTPRedirectHandler):
    """Follow a few redirects, re-checking every target with ``_ensure_public_url``."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _ensure_public_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> bytes:
    """Download ``url`` and return the body, enforcing the safety limits above."""

    _ensure_public_url(url)
    opener = urlrequest.build_opener(_SafeRedirectHandler)
    request = urlrequest.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
        },
    )
    deadline = time.monotonic() + total_timeout
    chunks: list[bytes] = []
    size = 0
    try:
        with opener.open(request, timeout=timeout) as response:
            while True:
                chunk = response.read(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise FeedCollectionError(
                        FeedErrorKind.INVALID_FORMAT, "Feed response exceeds the size limit."
                    )
                if time.monotonic() > deadline:
                    raise FeedCollectionError(FeedErrorKind.NETWORK, "Feed download took too long.")
    except FeedCollectionError:
        raise
    except urlerror.HTTPError as exc:
        exc.close()
        raise FeedCollectionError(FeedErrorKind.NETWORK, f"Feed server returned HTTP {exc.code}.") from exc
    except (urlerror.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as exc:
        raise FeedCollectionError(FeedErrorKind.NETWORK, f"Request failed: {exc}") from exc
    return b"".join(chunks)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _child_text(element, *tags: str) -> str | None:  # noqa: ANN001
    for tag in tags:
        child = element.find(tag)
        if child is not None:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _http_link_or_none(value: str | None) -> str | None:
    """Keep only http(s) links so values like ``javascript:`` never travel downstream."""

    if value is None:
        return None
    try:
        return value if urlsplit(value).scheme in {"http", "https"} else None
    except ValueError:
        return None


def parse_rss(
    source_id: str, data: bytes, *, max_items: int = DEFAULT_MAX_ITEMS_PER_FEED
) -> tuple[FeedItem, ...]:
    """Parse an RSS 2.0 document into raw items; raise ``FeedCollectionError`` if invalid."""

    try:
        root = SafeElementTree.fromstring(data, forbid_dtd=True)
    except (SafeElementTree.ParseError, DefusedXmlException) as exc:
        raise FeedCollectionError(FeedErrorKind.INVALID_FORMAT, f"Feed is not valid XML: {exc}") from exc

    if root.tag != "rss":
        raise FeedCollectionError(
            FeedErrorKind.INVALID_FORMAT, "Feed is not an RSS 2.0 document (root element is not <rss>)."
        )
    channel = root.find("channel")
    if channel is None:
        raise FeedCollectionError(FeedErrorKind.INVALID_FORMAT, "RSS feed has no <channel> element.")

    return tuple(
        FeedItem(
            source_id=source_id,
            title=_child_text(item, "title"),
            link=_http_link_or_none(_child_text(item, "link")),
            guid=_child_text(item, "guid"),
            published=_child_text(item, "pubDate"),
            author=_child_text(item, "author", f"{_DC_NS}creator"),
            summary=_child_text(item, "description"),
            content=_child_text(item, f"{_CONTENT_NS}encoded"),
        )
        for item in islice(channel.findall("item"), max_items)
    )


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------


def collect_rss_feeds(
    sources: Iterable[Source],
    *,
    fetch: Callable[[str], bytes] | None = None,
    max_items_per_feed: int = DEFAULT_MAX_ITEMS_PER_FEED,
) -> tuple[FeedResult, ...]:
    """Collect the feed of every eligible source, one source after another.

    Sources that are not eligible (inactive, not approved, usage terms not
    confirmed, or incomplete settings) are skipped without any request and have
    no entry in the result. Each remaining source gets exactly one FeedResult.
    ``fetch`` can be replaced in tests; it must return the response body.
    """

    fetcher = fetch or fetch_url
    results: list[FeedResult] = []

    for source in sources:
        if not source.eligible_for_collection:
            continue

        if source.collection_method != "rss":
            results.append(
                _failure(
                    source,
                    FeedErrorKind.UNSUPPORTED_METHOD,
                    f"Collection method '{source.collection_method}' is not supported yet.",
                )
            )
            continue

        if not source.feed_url:
            results.append(_failure(source, FeedErrorKind.INVALID_URL, "No feed_url is configured."))
            continue

        try:
            body = fetcher(source.feed_url)
            items = parse_rss(source.source_id, body, max_items=max_items_per_feed)
            results.append(FeedResult(source.source_id, items=items))
        except FeedCollectionError as exc:
            results.append(_failure(source, exc.kind, exc.message))
        except Exception:  # noqa: BLE001 - last resort so one source cannot stop the rest
            logger.exception("Unexpected error while collecting source %s", source.source_id)
            results.append(
                _failure(source, FeedErrorKind.INTERNAL, "Unexpected error while collecting the feed.")
            )

    return tuple(results)


def _failure(source: Source, kind: FeedErrorKind, message: str) -> FeedResult:
    return FeedResult(source.source_id, failure=FeedFailure(kind, message))
