from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import uvicorn

# Support direct execution from `BE/whatsapp_session_controller` via:
# `python ./run.py`
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whatsapp_session_controller.core.settings import get_controller_settings


def main() -> None:
    settings = get_controller_settings()

    log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["root"] = {"handlers": ["default"], "level": "INFO"}

    uvicorn.run(
        "whatsapp_session_controller.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
