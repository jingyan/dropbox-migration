from dropbox_to_gdrive.proxy import (
    apply_proxy_to_session,
    proxy_mapping,
    resolve_proxy_url,
)


def test_resolve_proxy_url_prefers_google_proxy(monkeypatch):
    monkeypatch.setenv("GOOGLE_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert resolve_proxy_url() == "http://127.0.0.1:9999"


def test_resolve_proxy_url_strips_quotes(monkeypatch):
    monkeypatch.delenv("GOOGLE_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", '"http://127.0.0.1:7890"')
    assert resolve_proxy_url() == "http://127.0.0.1:7890"


def test_apply_proxy_to_session_disables_trust_env():
    import requests

    session = requests.Session()
    apply_proxy_to_session(session, "http://127.0.0.1:7890")
    assert session.proxies == proxy_mapping("http://127.0.0.1:7890")
    assert session.trust_env is False


def test_resolve_proxy_url_checks_all_proxy(monkeypatch):
    for key in (
        "GOOGLE_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:7891")
    assert resolve_proxy_url() == "socks5h://127.0.0.1:7891"
