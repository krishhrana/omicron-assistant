import os
import uvicorn
from app.main import app



if __name__ == "__main__":
    # Dev-only: allow OAuth over http://localhost for local testing.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    uvicorn.run(
        "app.main:app",
        log_level="info",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
