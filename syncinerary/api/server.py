"""Production container entrypoint for the HTTP API."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "syncinerary.api.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
