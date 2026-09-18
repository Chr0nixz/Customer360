"""Trusted-only contracts. Never pass these objects to an Agent."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.public import AgentRequest, RefusalCode
from customer360.contracts.semantic import SemanticSpec


class AnswerOracle(Contract):
    expected_action: Literal["answer"] = "answer"
    semantic_spec: SemanticSpec


class SlotReply(Contract):
    slot: Identifier
    reply: Text


class ClarificationTurn(Contract):
    """One hidden user turn: slots the Agent must request, then scripted replies."""

    expected_slots: tuple[Identifier, ...] = Field(min_length=1)
    replies: tuple[SlotReply, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_and_aligned(self) -> "ClarificationTurn":
        if len(set(self.expected_slots)) != len(self.expected_slots):
            raise ValueError("duplicate expected slot")
        reply_slots = tuple(item.slot for item in self.replies)
        if len(set(reply_slots)) != len(reply_slots):
            raise ValueError("duplicate oracle slot")
        if set(self.expected_slots) != set(reply_slots):
            raise ValueError("turn slots must match replies")
        return self


class ClarificationOracle(Contract):
    expected_action: Literal["clarification_needed"] = "clarification_needed"
    replies: tuple[SlotReply, ...] = Field(min_length=1)
    completed_spec: SemanticSpec
    turns: tuple[ClarificationTurn, ...] | None = None

    @model_validator(mode="after")
    def unique_slots(self) -> "ClarificationOracle":
        if len({item.slot for item in self.replies}) != len(self.replies):
            raise ValueError("duplicate oracle slot")
        if self.turns is None:
            return self
        script_slots = [slot for turn in self.turns for slot in turn.expected_slots]
        if len(set(script_slots)) != len(script_slots):
            raise ValueError("duplicate slot across turns")
        if set(script_slots) != {item.slot for item in self.replies}:
            raise ValueError("script slots must match replies")
        top_replies = {item.slot: item.reply for item in self.replies}
        script_replies = {item.slot: item.reply for turn in self.turns for item in turn.replies}
        if top_replies != script_replies:
            raise ValueError("conflicting slot replies")
        return self

    def replay_script(self) -> tuple[ClarificationTurn, ...]:
        if self.turns is not None:
            return self.turns
        return (
            ClarificationTurn(
                expected_slots=tuple(item.slot for item in self.replies),
                replies=self.replies,
            ),
        )


class RefusalOracle(Contract):
    expected_action: Literal["refuse"] = "refuse"
    accepted_reason_codes: tuple[RefusalCode, ...] = Field(min_length=1)


CaseOracle = Annotated[
    AnswerOracle | ClarificationOracle | RefusalOracle, Field(discriminator="expected_action")
]


class PrivateCase(Contract):
    request: AgentRequest
    oracle: CaseOracle
    task_version: Literal["fixture-0.1", "human-0.1", "generated-0.1", "hidden-0.1"] = "fixture-0.1"
