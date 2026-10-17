"""Keep transport URLs/headers out of notification diagnostics, task-locally.

HTTPX INFO logs contain complete webhook URLs. HTTPCore DEBUG logs can contain
headers. Our delivery logs provide IDs, status and latency instead. Other HTTP
traffic retains its existing logging behavior, including in concurrent tasks.
"""
from contextvars import ContextVar
import logging

_private_transport = ContextVar("notification_private_transport", default=False)


class _TransportFilter(logging.Filter):
    def filter(self, record):
        return not _private_transport.get()


def install_filter():
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
                 "httpcore.proxy", "httpcore.socks"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _TransportFilter) for f in logger.filters):
            logger.addFilter(_TransportFilter())


async def private_post(client, *args, **kwargs):
    install_filter()
    token = _private_transport.set(True)
    try:
        return await client.post(*args, **kwargs)
    finally:
        _private_transport.reset(token)
