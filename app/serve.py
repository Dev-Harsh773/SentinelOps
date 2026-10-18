"""Single-worker production entry point; configuration comes from environment."""
import uvicorn
from app.common.config import config


def main():
    if not config.operator_token and config.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Non-local binding requires SENTINELOPS_OPERATOR_TOKEN")
    uvicorn.run("app.main:app", host=config.host, port=config.port, workers=1,
                proxy_headers=False, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
