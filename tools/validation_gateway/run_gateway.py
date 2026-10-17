"""CLI launcher for validation ingress gateway."""

import argparse
import sys
import uvicorn
from tools.validation_gateway.gateway import create_gateway_app, UPSTREAM_BASE_URL


def main():
    parser = argparse.ArgumentParser(description="SentinelOps Validation Gateway (Restricted Ingress)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--upstream", default=UPSTREAM_BASE_URL, help=f"Upstream SentinelOps URL (default: {UPSTREAM_BASE_URL})")
    args = parser.parse_args()

    app = create_gateway_app(upstream_url=args.upstream)
    print(f"Starting Validation Gateway on http://{args.host}:{args.port} -> Upstream: {args.upstream}")
    print("RESTRICTION: Only POST /connectors/{id}/ingest is accepted.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
