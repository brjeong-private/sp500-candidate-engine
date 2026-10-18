from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from datetime import date, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from sp500_candidate_engine.llm_preselection.asof import (
    NEW_YORK,
    PublicationBound,
    llm_cutoff,
    publication_bound,
)

SOURCE_DATE_VERSION = "llm-source-page-date-v2"
MAX_PAGE_BYTES = 1_000_000
MAX_REDIRECTS = 3

_URL_DATE = re.compile(r"(?<!\d)(20\d{2})[-/]?(0[1-9]|1[0-2])[-/]?(0[1-9]|[12]\d|3[01])(?!\d)")
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"([a-zA-Z:_-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_PUBLISHED_KEYS = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "pubdate",
    "publishdate",
    "publish-date",
    "date",
    "dc.date.issued",
    "dc.date",
    "parsely-pub-date",
)
_JSON_LD = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_TIME_TAG = re.compile(r"<time\b[^>]*\bdatetime\s*=\s*[\"']([^\"']+)[\"']", re.I)


class SourceDateError(ValueError):
    """A cited page has no usable, in-cutoff publication date."""


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> str: ...


def url_date(url: str) -> date | None:
    path = urlsplit(url).path
    found = None
    for match in _URL_DATE.finditer(path):
        try:
            candidate = date(*map(int, match.groups()))
        except ValueError:
            continue
        found = candidate if found is None else max(found, candidate)
    return found


def _parse_value(raw: str) -> datetime | date | None:
    text = html.unescape(raw).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def page_published(page: str) -> datetime | date | None:
    """First declared publication value; modification stamps are intentionally ignored."""
    candidates: list[str] = []
    for tag in _META.findall(page):
        attrs = {
            key.lower(): (double or single)
            for key, double, single in _ATTR.findall(tag)
        }
        name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if name in _PUBLISHED_KEYS and attrs.get("content"):
            candidates.append(attrs["content"])
    candidates.extend(_JSON_LD.findall(page))
    candidates.extend(_TIME_TAG.findall(page))
    for raw in candidates:
        parsed = _parse_value(raw)
        if parsed is not None:
            return parsed
    publication_dates = BeautifulSoup(page, "html.parser").select(
        "span.evergreen-news-date-text"
    )
    if len(publication_dates) == 1:
        try:
            return datetime.strptime(
                publication_dates[0].get_text(" ", strip=True), "%B %d, %Y"
            ).date()
        except ValueError:
            return None
    return None


def _local_date(value: datetime | date) -> date:
    if isinstance(value, datetime) and value.utcoffset() is not None:
        return value.astimezone(NEW_YORK).date()
    return value.date() if isinstance(value, datetime) else value


def source_bound(url: str, page: str, cutoff_at: datetime) -> tuple[PublicationBound, str]:
    """Earlier New York days pass on the date alone; the analysis day needs a time before 05:30."""
    from_url, from_page = url_date(url), page_published(page)
    if from_url is None and from_page is None:
        raise SourceDateError("SOURCE_DATE_NOT_FOUND")
    chosen: datetime | date
    basis: str
    if from_page is None:
        assert from_url is not None
        chosen, basis = from_url, "URL"
    elif from_url is None or _local_date(from_page) >= from_url:
        chosen, basis = from_page, "PAGE"
    else:
        chosen, basis = from_url, "URL"
    if isinstance(chosen, datetime) and chosen.utcoffset() is None:
        chosen = chosen.date() if _local_date(chosen) < _reference_day(cutoff_at) else chosen
    try:
        return publication_bound(chosen, cutoff_at), basis
    except ValueError as error:
        raise SourceDateError("SOURCE_DATE_OUTSIDE_CUTOFF_OR_UNTIMED") from error


def _reference_day(cutoff_at: datetime) -> date:
    return llm_cutoff(cutoff_at).astimezone(NEW_YORK).date()


def describe(bound: PublicationBound) -> str:
    if bound.precision == "TIMESTAMP":
        return bound.upper_bound_at.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M")
    return bound.local_date.isoformat()


def public_host_allowed(host: str, resolved: list[str]) -> bool:
    if not resolved:
        return False
    for address in resolved:
        if not ipaddress.ip_address(address).is_global:
            return False
    return host not in {"localhost"}


class HttpsPageFetcher:
    """Bounded HTTPS-only fetch of a public cited page; every redirect is revalidated."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def _check(self, url: str) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            raise SourceDateError("SOURCE_URL_NOT_PUBLIC_HTTPS")
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        except OSError as error:
            raise SourceDateError("SOURCE_HOST_UNRESOLVED") from error
        if not public_host_allowed(parts.hostname, [str(info[4][0]) for info in infos]):
            raise SourceDateError("SOURCE_URL_NOT_PUBLIC_HTTPS")

    async def fetch(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; sp500-candidate-engine)"},
        ) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                await self._check(current)
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceDateError("SOURCE_REDIRECT_INVALID")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise SourceDateError("SOURCE_FETCH_FAILED")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_PAGE_BYTES:
                            break
                    return bytes(body[:MAX_PAGE_BYTES]).decode("utf-8", errors="replace")
        raise SourceDateError("SOURCE_REDIRECT_LIMIT")


def citation_urls(raw: dict) -> list[str]:
    urls: list[str] = []
    for item in raw.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            for annotation in content.get("annotations") or []:
                if (
                    isinstance(annotation, dict)
                    and annotation.get("type") == "url_citation"
                    and isinstance(annotation.get("url"), str)
                ):
                    url = annotation["url"].split("#", 1)[0]
                    if url not in urls:
                        urls.append(url)
    return urls


async def inspect_sources(
    urls: list[str], fetcher: PageFetcher, cutoff_at: datetime, *, limit: int
) -> dict[str, dict[str, object]]:
    """Python-side date ledger. Unfetchable or undated pages are recorded as rejected."""
    ledger: dict[str, dict[str, object]] = {}
    for url in urls[:limit]:
        try:
            page = await fetcher.fetch(url)
            bound, basis = source_bound(url, page, cutoff_at)
        except SourceDateError as error:
            ledger[url] = {"status": "REJECTED", "reason": str(error)}
            continue
        except httpx.HTTPError:
            ledger[url] = {"status": "REJECTED", "reason": "SOURCE_FETCH_FAILED"}
            continue
        ledger[url] = {
            "status": "ADMITTED",
            "basis": basis,
            "label": describe(bound),
            "precision": bound.precision,
            "version": SOURCE_DATE_VERSION,
        }
    for url in urls[limit:]:
        ledger[url] = {"status": "REJECTED", "reason": "SOURCE_OVER_BUDGET"}
    return ledger
