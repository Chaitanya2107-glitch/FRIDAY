"""Public web URLs and bounded extraction. Never evaluate web text as code."""

import ipaddress
import hashlib
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

MAX_HTML_BYTES = 2_000_000
MAX_TEXT_CHARS = 12000
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


def public_url(url: str) -> str:
    if len(url) > 2000 or any(ord(c) <= 32 for c in url) or "\\" in url:
        raise ValueError("Invalid web URL")
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in {None, 80, 443}):
        raise ValueError("Only public HTTP(S) URLs on standard ports are supported")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Local and private network addresses are not supported")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def extract_html(html: str, url: str) -> tuple[str, str]:
    from scrapling.parser import Selector
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("Page exceeds the extraction limit")
    page = Selector(html, url=url, adaptive=False, huge_tree=False)
    # Select text nodes without script/style/hidden ancestry. This is content
    # filtering, not a claim to eliminate prompt injection. Models get data only.
    text = page.xpath("//body//text()[not(ancestor::script or ancestor::style or ancestor::noscript "
                      "or ancestor::template or ancestor::svg or ancestor::head "
                      "or ancestor::nav or ancestor::footer or ancestor::*[@hidden] "
                      "or ancestor::*[@aria-hidden='true'])]").getall()
    cleaned = " ".join(" ".join(str(t).split()) for t in text)
    return str(page.css("title::text").get() or url)[:300], cleaned[:MAX_TEXT_CHARS]


def safe_filename(name: str) -> str:
    name = re.sub(r'[^\w. -]', "_", name).strip(" .")[:100]
    return name if name and name.split(".")[0].upper() not in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10))} else "download.bin"


def download_file(url, directory: Path, stopped):
    """Public GET only; no personal cookies, execution, overwrite or unbounded save."""
    deadline = time.monotonic() + 30
    temporary = None
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                if stopped.is_set() or time.monotonic() >= deadline:
                    raise InterruptedError("Download stopped or timed out")
                url = public_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    if int(response.headers.get("content-length", "0")) > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Download exceeds the size limit")
                    name = safe_filename(urlsplit(url).path.rsplit("/", 1)[-1])
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory / f"{uuid.uuid4().hex[:8]}-{name}"
                    temporary = path.with_suffix(path.suffix + ".part")
                    size, digest = 0, hashlib.sha256()
                    with temporary.open("xb") as handle:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            if stopped.is_set() or time.monotonic() >= deadline:
                                raise InterruptedError("Download stopped or timed out")
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise ValueError("Download exceeds the size limit")
                            handle.write(chunk)
                            digest.update(chunk)
                    if not size or stopped.is_set():
                        raise ValueError("Empty or cancelled download")
                    temporary.replace(path)
                    return path, size, digest.hexdigest()
            raise ValueError("Too many download redirects")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
