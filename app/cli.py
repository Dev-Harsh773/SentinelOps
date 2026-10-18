"""Standalone command-line launcher for SentinelOps backend server."""

from __future__ import annotations

import argparse
import sys
import uvicorn

from app.common.config import config


def main() -> int:
    """Parse command-line arguments and launch uvicorn ASGI server."""
    parser = argparse.ArgumentParser(description="SentinelOps Backend Server")
    parser.add_argument(
        "--host",
        default=config.host,
        help=f"Bind host address (default: {config.host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.port,
        help=f"Bind port number (default: {config.port})",
    )
    parser.add_argument(
        "--env",
        dest="app_env",
        default=config.app_env,
        help=f"Application environment mode (default: {config.app_env})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload on code change (development only)",
    )

    args = parser.parse_args()

    # Pass environment override if specified
    import os
    if args.app_env:
        os.environ["APP_ENV"] = args.app_env
    from app.common import config as config_module
    config_module.config = config_module.AppConfig.from_env()
    effective = config_module.config
    if effective.production and args.reload:
        parser.error("Production does not support reload; run one worker")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not effective.operator_token:
        parser.error("Non-local binding requires SENTINELOPS_OPERATOR_TOKEN")

    print(f"Starting SentinelOps server on {args.host}:{args.port} (env: {args.app_env})")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=effective.log_level.lower(),
        workers=1,
        proxy_headers=False,
        access_log=not effective.production,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
