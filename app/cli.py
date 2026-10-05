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

    print(f"Starting SentinelOps server on {args.host}:{args.port} (env: {args.app_env})")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=config.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
