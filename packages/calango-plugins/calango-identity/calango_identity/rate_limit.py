from __future__ import annotations

from functools import partial
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

IPAddress = IPv4Address | IPv6Address


def _is_trusted_proxy(address: IPAddress, trusted_proxies: tuple[str, ...]) -> bool:
    """Return whether an address belongs to one of the explicit proxy entries."""
    for proxy in trusted_proxies:
        try:
            if address == ip_address(proxy):
                return True
        except ValueError:
            try:
                if address in ip_network(proxy, strict=False):
                    return True
            except ValueError:
                continue
    return False


def resolve_client_ip(request: Request, trusted_proxies: tuple[str, ...]) -> str:
    """Resolve a client IP, trusting forwarding data only from known proxy peers."""
    peer = get_remote_address(request)
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return peer

    if not _is_trusted_proxy(peer_address, trusted_proxies):
        return peer

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer

    try:
        forwarded_chain = tuple(ip_address(value.strip()) for value in forwarded_for.split(","))
    except ValueError:
        return peer

    for address in reversed(forwarded_chain):
        if not _is_trusted_proxy(address, trusted_proxies):
            return str(address)
    return str(forwarded_chain[0]) if forwarded_chain else peer


def make_limiter(storage_uri: str, trusted_proxies: tuple[str, ...] = ()) -> Limiter:
    """Create a slowapi Limiter backed by the given storage URI.

    For production: storage_uri = "redis://localhost:6379/0"
    For tests: storage_uri = "memory://"
    """
    return Limiter(
        key_func=partial(resolve_client_ip, trusted_proxies=trusted_proxies),
        storage_uri=storage_uri,
    )


def get_email_key(request: Request) -> str:
    """Key function for per-email rate limiting on login endpoint.

    Falls back to IP address if login_email is not set on request.state.
    """
    email = getattr(request.state, "login_email", None)
    if isinstance(email, str) and (normalized := email.strip().casefold()):
        return normalized
    return get_remote_address(request)


async def capture_login_email(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),  # noqa: B008
) -> OAuth2PasswordRequestForm:
    """Populate the per-email limiter key without retaining the password."""
    request.state.login_email = credentials.username.strip().casefold()
    return credentials
