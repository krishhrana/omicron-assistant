from __future__ import annotations

from abc import ABC
from typing import Generic, Sequence, TypeVar

from agents import Agent, Tool


TContext = TypeVar("TContext")


class BaseAgent(ABC, Generic[TContext]):
    def __init__(
        self,
        *,
        name: str,
        instructions: str,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
        handoff_description: str | None = None,
        handoffs: Sequence[str] | None = None,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.tools = list(tools) if tools else []
        self.model = model
        self.handoff_description = handoff_description
        self.handoffs = handoffs

    def build(self) -> Agent[TContext]:
        return Agent(
            name=self.name,
            instructions=self.instructions,
            tools=list(self.tools),
            model=self.model,
            handoff_description=self.handoff_description,
            handoffs=self.handoffs
        )
