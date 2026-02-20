import logging
from typing import Optional, Tuple

from fastapi import HTTPException, Request


def is_proxy_authenticated_request(request: Request) -> bool:
    """Detect whether the request comes from a proxy with pre-auth."""
    return bool(request.headers.get("x-ingress-path", "").strip())


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
    Validate auth using a shared secret.
    If the request comes through a pre-authenticated proxy, skip duplicate validation.
    """
    endpoint = context_path or request.url.path
    if not job_secret:
        return "not_required"

    if is_proxy_authenticated_request(request):
        logger.debug("Auth bypass on %s via ingress", endpoint)
        return "ingress"

    provided, source = extract_secret(request, body_secret=body_secret)
    if provided != job_secret:
        logger.warning("Unauthorized on %s (source=%s)", endpoint, source)
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.debug("Auth OK on %s (source=%s)", endpoint, source)
    return source
