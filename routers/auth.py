import logging
import secrets
from typing import Optional, Tuple

from fastapi import HTTPException, Request


# Home Assistant's ingress proxy is the only peer permitted to pre-authenticate
# a request. A client-provided X-Ingress-Path header alone is not trustworthy.
HOME_ASSISTANT_INGRESS_PROXY_HOST = "172.30.32.2"


def is_proxy_authenticated_request(request: Request) -> bool:
    """Accept Home Assistant ingress pre-authentication only from its proxy."""
    ingress_path = request.headers.get("x-ingress-path", "").strip()
    client = request.client
    client_host = str(client.host or "").strip() if client else ""
    return bool(ingress_path) and client_host == HOME_ASSISTANT_INGRESS_PROXY_HOST


def extract_secret(request: Request, body_secret: Optional[str] = None) -> Tuple[str, str]:
    """Extract secret from header, query, and optionally body."""
    header_secret = request.headers.get("x-job-secret", "").strip()
    if header_secret:
        return header_secret, "header"

    query_secret = request.query_params.get("secret", "").strip()
    if query_secret:
        return query_secret, "query"

    if body_secret:
        body_secret = str(body_secret).strip()
        if body_secret:
            return body_secret, "body"

    return "", "missing"


def ensure_request_authorized(
    request: Request,
    job_secret: str,
    logger: logging.Logger,
    *,
    body_secret: Optional[str] = None,
    context_path: str = "",
) -> str:
    """
    Validate direct requests using a shared secret.

    Home Assistant ingress is pre-authenticated only when the request reached
    the app from the documented Supervisor ingress proxy host. Direct access
    always requires a configured secret; a client-supplied ingress header is
    never sufficient to bypass that requirement.
    """
    endpoint = context_path or request.url.path

    if is_proxy_authenticated_request(request):
        logger.debug("Auth bypass on %s via ingress", endpoint)
        return "ingress"

    ingress_path = request.headers.get("x-ingress-path", "").strip()
    if ingress_path:
        client = request.client
        client_host = str(client.host or "").strip() if client else "unknown"
        logger.warning("Rejected untrusted ingress auth header on %s (client=%s)", endpoint, client_host)

    configured_secret = str(job_secret or "").strip()
    if not configured_secret:
        logger.warning("Unauthorized on %s (source=missing, reason=job_secret_required)", endpoint)
        raise HTTPException(status_code=401, detail="Unauthorized")

    provided, source = extract_secret(request, body_secret=body_secret)
    # Compare bytes so valid UTF-8 secrets do not make compare_digest raise.
    try:
        provided_bytes = provided.encode("utf-8")
        configured_secret_bytes = configured_secret.encode("utf-8")
    except UnicodeEncodeError:
        logger.warning("Unauthorized on %s (source=%s, reason=invalid_secret_encoding)", endpoint, source)
        raise HTTPException(status_code=401, detail="Unauthorized") from None

    if not secrets.compare_digest(provided_bytes, configured_secret_bytes):
        logger.warning("Unauthorized on %s (source=%s)", endpoint, source)
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.debug("Auth OK on %s (source=%s)", endpoint, source)
    return source
