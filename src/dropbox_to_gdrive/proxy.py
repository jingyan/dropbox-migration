"""Proxy configuration shared by Google API clients."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import httplib2
import requests
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

_PROXY_ENV_KEYS = (
    "GOOGLE_PROXY",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def resolve_proxy_url() -> str | None:
    """Return the first configured proxy URL from environment variables."""

    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def proxy_mapping(proxy_url: str) -> dict[str, str]:
    """Build a requests-compatible proxies dict."""

    return {"http": proxy_url, "https": proxy_url}


def apply_proxy_to_session(session: requests.Session, proxy_url: str | None) -> None:
    """Configure a requests session to route traffic through proxy_url."""

    if not proxy_url:
        return
    session.proxies.update(proxy_mapping(proxy_url))
    session.trust_env = False


def build_refresh_request(proxy_url: str | None = None) -> Request:
    """Build a google-auth Request that uses an explicitly configured proxy."""

    proxy_url = proxy_url if proxy_url is not None else resolve_proxy_url()
    session = requests.Session()
    apply_proxy_to_session(session, proxy_url)
    return Request(session=session)


def build_requests_session(proxy_url: str | None = None) -> requests.Session:
    """Build a plain requests session with optional proxy settings."""

    proxy_url = proxy_url if proxy_url is not None else resolve_proxy_url()
    session = requests.Session()
    apply_proxy_to_session(session, proxy_url)
    return session


def log_proxy_usage(proxy_url: str | None) -> None:
    if not proxy_url:
        logger.debug("No proxy configured for Google API requests")
        return
    parsed = urlparse(proxy_url)
    host = parsed.hostname or "unknown"
    port = parsed.port or (7890 if parsed.scheme.startswith("http") else 1080)
    scheme = parsed.scheme or "http"
    logger.info("Using %s proxy for Google API requests at %s:%s", scheme, host, port)


def httplib2_proxy_info(proxy_url: str) -> httplib2.ProxyInfo:
    """Build httplib2 ProxyInfo, including SOCKS proxies used by many VPN clients."""

    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid proxy URL: {proxy_url!r}")

    port = parsed.port
    if scheme in {"socks5", "socks5h"}:
        port = port or 1080
        return httplib2.ProxyInfo(
            proxy_type=httplib2.socks.PROXY_TYPE_SOCKS5,
            proxy_host=host,
            proxy_port=port,
            proxy_rdns=scheme == "socks5h",
        )
    if scheme == "socks4":
        port = port or 1080
        return httplib2.ProxyInfo(
            proxy_type=httplib2.socks.PROXY_TYPE_SOCKS4,
            proxy_host=host,
            proxy_port=port,
        )

    port = port or 8080
    return httplib2.ProxyInfo(
        proxy_type=httplib2.socks.PROXY_TYPE_HTTP,
        proxy_host=host,
        proxy_port=port,
    )
