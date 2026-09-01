"""Safe outbound HTTP helpers.

Blocks local/private/link-local destinations and validates every redirect to reduce SSRF risk.
Only HTTP(S) public destinations are allowed.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _resolved_ips(hostname: str, port: int | None = None):
    try:
        infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Host não pôde ser resolvido") from exc
    seen = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            yield ipaddress.ip_address(ip)


def validate_public_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("Somente URLs HTTP/HTTPS são permitidas")
    if parsed.username or parsed.password:
        raise ValueError("Credenciais embutidas na URL não são permitidas")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise ValueError("Destino não permitido")
    port = parsed.port
    if port and port not in {80, 443}:
        raise ValueError("Porta de rede não permitida")
    for ip in _resolved_ips(host, port):
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified
        ):
            raise ValueError("Destino privado/interno não permitido")
    return raw


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def safe_urlopen(url_or_request, timeout=15, max_bytes: int | None = None):
    url = url_or_request.full_url if isinstance(url_or_request, Request) else str(url_or_request)
    validate_public_url(url)
    opener = build_opener(_SafeRedirect())
    response = opener.open(url_or_request, timeout=timeout)
    final_url = response.geturl()
    validate_public_url(final_url)
    return response


def safe_fetch_bytes(url: str, *, timeout=15, headers=None, max_bytes=2_000_000) -> bytes:
    request = Request(url, headers=headers or {})
    with safe_urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Resposta excede o limite permitido")
        return data
