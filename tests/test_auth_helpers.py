import logging
import unittest
from typing import Any

try:
    from fastapi import HTTPException
    from starlette.requests import Request

    from routers.auth import ensure_request_authorized, extract_secret

    DEPS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - depende del entorno local
    Request = Any  # type: ignore[assignment]
    DEPS_AVAILABLE = False


def make_request(
    *,
    path: str = "/test",
    headers: dict[str, str] | None = None,
    query: str = "",
) -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "query_string": query.encode("latin-1"),
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/starlette no está instalado en este entorno")
class AuthHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("tests.auth")

    def test_extract_secret_header_priority(self) -> None:
        req = make_request(
            headers={"x-job-secret": "from-header"},
            query="secret=from-query",
        )
        provided, source = extract_secret(req, body_secret="from-body")
        self.assertEqual(provided, "from-header")
        self.assertEqual(source, "header")

    def test_extract_secret_query_fallback(self) -> None:
        req = make_request(query="secret=from-query")
        provided, source = extract_secret(req, body_secret="from-body")
        self.assertEqual(provided, "from-query")
        self.assertEqual(source, "query")

    def test_extract_secret_body_fallback(self) -> None:
        req = make_request()
        provided, source = extract_secret(req, body_secret="from-body")
        self.assertEqual(provided, "from-body")
        self.assertEqual(source, "body")

    def test_ensure_request_authorized_rejects_invalid_secret(self) -> None:
        req = make_request(query="secret=wrong")
        with self.assertRaises(HTTPException) as ctx:
            ensure_request_authorized(req, "correct", self.logger)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_ensure_request_authorized_proxy_bypass(self) -> None:
        req = make_request(headers={"x-ingress-path": "/ingress/test"})
        source = ensure_request_authorized(req, "correct", self.logger)
        self.assertEqual(source, "ingress")


if __name__ == "__main__":
    unittest.main()
