import os
from copy import deepcopy

import uvicorn
from app.main import app



def _build_log_config() -> dict:
    log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["root"] = {"handlers": ["default"], "level": "INFO"}
    return log_config


if __name__ == "__main__":
    # Dev-only: allow OAuth over http://localhost for local testing.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    uvicorn.run(
        "app.main:app",
        log_level="info",
        log_config=_build_log_config(),
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
