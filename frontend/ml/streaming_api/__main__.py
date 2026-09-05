"""
Entry point for `python -m api`.

Starts the streaming service with the host and port from the environment
(`NER_EWS_HOST`, `NER_EWS_PORT`), defaulting to 127.0.0.1:8000.
"""

from __future__ import annotations

import logging

import uvicorn

from .config import SETTINGS


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    uvicorn.run(
        "api.service:app",
        host=SETTINGS.host,
        port=SETTINGS.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
