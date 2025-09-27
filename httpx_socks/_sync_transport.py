import ssl
import typing

import httpcore

from httpx import BaseTransport, Request, Response, SyncByteStream, Limits

# noinspection PyProtectedMember
from httpx._config import DEFAULT_LIMITS, create_ssl_context
# noinspection PyProtectedMember
from httpx._transports.default import ResponseStream, map_httpcore_exceptions

from ._sync_proxy import SyncProxy
from python_socks import ProxyType, parse_proxy_url

# Import httpx_tls for JA3 modification
try:
    from httpx_tls.mocks import SSLContextProxy
    HTTPX_TLS_AVAILABLE = True
except ImportError:
    HTTPX_TLS_AVAILABLE = False


class SyncProxyTransport(BaseTransport):
    def __init__(
        self,
        *,
        proxy_type: ProxyType,
        proxy_host: str,
        proxy_port: int,
        username=None,
        password=None,
        rdns=None,
        proxy_ssl: ssl.SSLContext = None,
        verify=True,
        cert=None,
        trust_env: bool = True,
        limits: Limits = DEFAULT_LIMITS,
        tls_config=None,  # Add support for TLS configuration
        **kwargs,
    ):
        ssl_context = create_ssl_context(
            verify=verify,
            cert=cert,
            trust_env=trust_env,
        )

        # Use httpx_tls SSLContextProxy if available and tls_config provided
        if HTTPX_TLS_AVAILABLE and tls_config is not None:
            ssl_context = SSLContextProxy(ssl_context, tls_config)

        # Store h2_config for later use and remove it from kwargs
        self._h2_config = kwargs.pop('h2_config', None)

        self._pool = SyncProxy(
            proxy_type=proxy_type,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            username=username,
            password=password,
            rdns=rdns,
            proxy_ssl=proxy_ssl,
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            **kwargs,
        )

    def handle_request(self, request: Request) -> Response:
        assert isinstance(request.stream, SyncByteStream)

        # Add h2_config to request extensions if available
        extensions = request.extensions.copy()
        if self._h2_config is not None:
            extensions['h2_profile'] = self._h2_config

        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=extensions,
        )

        with map_httpcore_exceptions():
            resp = self._pool.handle_request(req)

        assert isinstance(resp.stream, typing.Iterable)

        return Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=ResponseStream(resp.stream),
            extensions=resp.extensions,
        )

    @classmethod
    def from_url(cls, url, tls_config=None, **kwargs):
        proxy_type, host, port, username, password = parse_proxy_url(url)
        return cls(
            proxy_type=proxy_type,
            proxy_host=host,
            proxy_port=port,
            username=username,
            password=password,
            tls_config=tls_config,
            **kwargs,
        )

    def close(self) -> None:
        self._pool.close()  # pragma: no cover

    def __enter__(self):
        self._pool.__enter__()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        with map_httpcore_exceptions():
            self._pool.__exit__(exc_type, exc_value, traceback)
