"""Central operator boundary and bounded single-process abuse protection."""
from collections import OrderedDict
import hmac
import re
import threading
import time
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from app.common.config import config

INGRESS = re.compile(r"/connectors/[A-Za-z0-9_.-]+/ingest")
PUBLIC = {("GET", "/health"), ("GET", "/live"), ("GET", "/ready")}


class WindowLimiter:
    """Fixed windows; full key table rejects new keys instead of evicting active limits."""
    def __init__(self, max_keys=4096, clock=time.monotonic):
        self.max_keys = max_keys
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, limit):
        now = self.clock()
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[0] <= now:
                self.entries.popitem(last=False)
            expiry, count = self.entries.get(key, (now + 60, 0))
            if key not in self.entries and len(self.entries) >= self.max_keys:
                return False
            if count >= limit:
                return False
            self.entries[key] = (expiry, count + 1)
            return True


class OperatorAccessMiddleware:
    def __init__(self, app, settings=None, limiter=None):
        self.app = app
        self.settings = settings or config
        self.limiter = limiter or WindowLimiter(self.settings.rate_limit_keys)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        if (method, path) in PUBLIC:
            await self.app(scope, receive, send)
            return
        cfg = self.settings
        # Never accept client-supplied forwarded IP headers for security decisions.
        client = (scope.get("client") or ("unknown",))[0]
        ingress = method == "POST" and INGRESS.fullmatch(path) is not None
        async def reject(code, detail):
            headers = {"Retry-After":"60"} if code == 429 else {"WWW-Authenticate":"Bearer"}
            await JSONResponse({"detail":detail},status_code=code,headers=headers)(scope,receive,send)
        if not ingress and cfg.operator_token:
            authorization = Headers(scope=scope).get("authorization", "")
            scheme, _, supplied = authorization.partition(" ")
            valid = scheme.lower() == "bearer" and hmac.compare_digest(supplied.encode(), cfg.operator_token.encode())
            if not valid:
                if not self.limiter.allow(("auth",client),cfg.rate_limit_auth):
                    await reject(429,"Too many authentication attempts")
                else:
                    await reject(401,"Valid operator bearer token required")
                return
        # Local anonymous ergonomics remain local. Production config always requires a token.
        enabled = cfg.production or bool(cfg.operator_token)
        if enabled and ingress and not self.limiter.allow(("ingest",client),cfg.rate_limit_ingest):
            await reject(429,"Telemetry rate limit exceeded")
            return
        if enabled and method == "POST" and any(part in path for part in
                ("investigat", "remediation", "reindex", "/github", "/collect")):
            if not self.limiter.allow(("expensive",client),cfg.rate_limit_expensive):
                await reject(429,"Operation rate limit exceeded")
                return
        await self.app(scope,receive,send)
