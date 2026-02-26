from __future__ import annotations

from abc import ABC
from typing import Generic, TypeVar

from agents import Agent


TContext = TypeVar("TContext")


class BaseAgent(ABC, Agent[TContext], Generic[TContext]):
    # Class-level capability flags (usable without instantiating the agent).
    CAN_GATHER_USER_DATA: bool = False
    HANDOFF_ENABLED: bool = False

    @property
    def can_gather_user_data(self) -> bool:
        return getattr(self, "_can_gather_user_data", self.CAN_GATHER_USER_DATA)
    
    @property
    def handoff_enabled(self) -> bool: 
        return getattr(self, "_handoff_enabled", self.HANDOFF_ENABLED)

    @can_gather_user_data.setter
    def can_gather_user_data(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("can_gather_user_data must be a bool")
        self._can_gather_user_data = value

    @handoff_enabled.setter
    def handoff_enabled(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("handoff_enabled must be a bool")
        self._handoff_enabled = value
