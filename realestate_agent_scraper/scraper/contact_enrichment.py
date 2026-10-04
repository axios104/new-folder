"""Best-effort extraction from an agency's own public website."""
from __future__ import annotations

import html as html_lib
import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from scraper.html_fields import clean_agent_name, clean_job_title

_BLOCK_TAGS = {"address", "article", "br", "div", "h1", "h2", "h3", "h4", "li", "p", "section"}
_DIRECTORY_RE = re.compile(r"\b(?:our\s+team|meet\s+(?:our\s+)?team|team|agents|people|staff)\b", re.I)
_PROFILE_PATH_RE = re.compile(r"/(?:our-team|team|agents|people|staff)/[^/?#]+/?$", re.I)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?61[\s-]?(?:\(0\)[\s-]?)?[2-478]\d{1,2}[\s-]?\d{3}[\s-]?\d{3}|0[2-478][\s-]?\d{4}[\s-]?\d{4}|04\d{2}[\s-]?\d{3}[\s-]?\d{3})(?!\w)")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._anchor: dict[str, str] | None = None
        self._skip_depth = 0
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "a":
            self._anchor = {"href": attrs.get("href", ""), "label": ""}

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "a" and self._anchor is not None:
            self._anchor["label"] = " ".join(self._anchor["label"].split())
            self.anchors.append(self._anchor)
            self._anchor = None
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._anchor is not None:
            self._anchor["label"] += data + " "
        self.text_parts.append(data)

    @property
    def text(self) -> str:
        return "\n".join(
            line.strip()
            for line in html_lib.unescape("".join(self.text_parts)).splitlines()
            if line.strip()
        )


def normalized_person_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z]+", (value or "").casefold()))


def _is_public_http_url(url: str) -> bool:
    candidate = urlsplit(url)
    host = candidate.hostname or ""
    try:
        public_host = ipaddress.ip_address(host).is_global
    except ValueError:
        public_host = host.casefold() not in {"localhost"} and not host.casefold().endswith(
            (".local", ".internal", ".localhost")
        )
    return candidate.scheme in {"http", "https"} and bool(host) and public_host


def _allowed_site_url(url: str, website_url: str) -> bool:
    candidate, root = urlsplit(url), urlsplit(website_url)
    return (
        _is_public_http_url(url)
        and (candidate.hostname or "").casefold().removeprefix("www.")
        == (root.hostname or "").casefold().removeprefix("www.")
    )


def extract_agency_website_url(html: str) -> str:
    """Find the external link explicitly labeled as the agency website."""
    parser = _PageParser()
    parser.feed(html or "")
    for anchor in parser.anchors:
        label = anchor["label"]
        href = html_lib.unescape(anchor["href"]).strip()
        if not href or not re.search(r"(?:agency\s+)?website|visit\s+(?:our\s+)?site", label, re.I):
            continue
        absolute = urljoin("https://www.realestate.com.au/", href)
        if not _is_public_http_url(absolute):
            continue
        if (urlsplit(absolute).hostname or "").casefold().removeprefix("www.") == "realestate.com.au":
            continue
        parsed = urlsplit(absolute)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    return ""


def extract_team_directory_urls(html: str, website_url: str) -> list[str]:
    """Return same-site team-directory links; never follow unrelated domains."""
    parser = _PageParser()
    parser.feed(html or "")
    found: list[str] = []
    root = urlsplit(website_url)
    root_url = urlunsplit((root.scheme, root.netloc, root.path or "/", "", ""))
    found.append(root_url)
    for anchor in parser.anchors:
        href = anchor["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        absolute = urljoin(website_url, href)
        if not _allowed_site_url(absolute, website_url):
            continue
        path = urlsplit(absolute).path
        if not (_DIRECTORY_RE.search(anchor["label"]) or re.search(r"/(?:our-team|team|agents|people|staff)/?$", path, re.I)):
            continue
        clean = urlunsplit((root.scheme, root.netloc, path, "", ""))
        if clean not in found:
            found.append(clean)
    return found


def extract_external_agent_links(html: str, website_url: str) -> dict[str, str]:
    """Index public staff profile links by a conservative normalized name."""
    parser = _PageParser()
    parser.feed(html or "")
    profiles: dict[str, str] = {}
    for anchor in parser.anchors:
        href = anchor["href"].strip()
        if not href or not _PROFILE_PATH_RE.search(urlsplit(href).path):
            continue
        absolute = urljoin(website_url, href)
        if not _allowed_site_url(absolute, website_url):
            continue
        label = anchor["label"].strip()
        name = clean_agent_name(label, absolute)
        key = normalized_person_name(name)
        if not key or _DIRECTORY_RE.fullmatch(label):
            continue
        profiles.setdefault(key, absolute)
    return profiles


def extract_external_agent_details(html: str, expected_name: str) -> dict[str, str]:
    """Extract only public details from a matching agency staff profile."""
    parser = _PageParser()
    parser.feed(html or "")
    lines = [line.strip() for line in parser.text.splitlines() if line.strip()]
    expected = normalized_person_name(expected_name)

    # Require an exact name on the page before using any contact data.
    name_index = next((i for i, line in enumerate(lines) if normalized_person_name(line) == expected), None)
    if name_index is None:
        name_index = next(
            (i for i, line in enumerate(lines) if expected and normalized_person_name(line).startswith(expected + " ")),
            None,
        )
    if name_index is None:
        return {
            "job_title": "", "years_experience": "", "agent_email": "", "phone": "", "agency_address": ""
        }

    nearby = "\n".join(lines[name_index:name_index + 14])
    html_mail = re.search(r"href=[\"']mailto:([^\"'?#]+)", html or "", re.I)
    email = html_lib.unescape(html_mail.group(1)).strip() if html_mail else ""
    if not email:
        email_match = _EMAIL_RE.search(nearby)
        email = email_match.group(0) if email_match else ""

    html_tel = re.search(r"href=[\"']tel:([^\"'?#]+)", html or "", re.I)
    phone = html_lib.unescape(html_tel.group(1)).strip() if html_tel else ""
    if not phone:
        phone_match = _PHONE_RE.search(nearby)
        phone = phone_match.group(0) if phone_match else ""

    job_title = ""
    for line in lines[name_index + 1:name_index + 7]:
        if line == phone or line == email or re.search(r"^(?:contact|enquire|email|call|sell my property)\b", line, re.I):
            continue
        candidate = re.sub(_PHONE_RE, "", line).strip(" |–—-\t")
        candidate = clean_job_title(candidate)
        if candidate and re.search(
            r"\b(?:agent|sales|property|manager|specialist|director|principal|consultant|representative|associate|auctioneer|leasing|licensee|operations|executive|partner)\b",
            candidate,
            re.I,
        ) and not re.search(r"\b(?:in|at)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$", candidate):
            job_title = candidate
            break

    experience_match = re.search(r"\b(\d{1,2})\s*years?\s+(?:of\s+)?experience\b", nearby, re.I)
    years_experience = experience_match.group(1) if experience_match else ""

    address = ""
    for index, line in enumerate(lines):
        if re.search(r"\boffice\s+details\b", line, re.I):
            for candidate in lines[index + 1:index + 5]:
                if re.search(r"\b\d{4}\b", candidate) and re.search(r"\b(?:QLD|NSW|VIC|WA|SA|TAS|NT|ACT)\b", candidate, re.I):
                    address = candidate
                    break
            break
    return {
        "job_title": job_title,
        "years_experience": years_experience,
        "agent_email": email,
        "phone": phone,
        "agency_address": address,
    }
