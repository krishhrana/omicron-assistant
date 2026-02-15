import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "browser_session_controller.main:app",
        host="0.0.0.0",
        port=8090,
        log_level="info",
        reload=False,
    )

