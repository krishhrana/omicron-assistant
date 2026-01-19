from __future__ import annotations

from app.core.enums import SupportedApps


class AppNotConnectedError(ValueError):
    def __init__(self, app_choice: SupportedApps | str, connected_apps: list[SupportedApps]) -> None:
        choice = app_choice.value if isinstance(app_choice, SupportedApps) else str(app_choice)
        connected = ", ".join(app.value for app in connected_apps) or "none"
        super().__init__(f"Requested app '{choice}' is not connected. Connected apps: {connected}.")
