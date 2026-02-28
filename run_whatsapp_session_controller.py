import uvicorn

from whatsapp_session_controller.core.settings import get_controller_settings


if __name__ == "__main__":
    settings = get_controller_settings()
    uvicorn.run(
        "whatsapp_session_controller.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )

