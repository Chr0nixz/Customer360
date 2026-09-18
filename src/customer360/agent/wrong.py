"""Deterministic negative control, not an oracle-driven Agent."""

from customer360.contracts.public import AgentError


class WrongAgent:
    def respond(self, request, tools):
        return AgentError(reason_code="UNSUPPORTED_REQUEST", message="Negative-control failure")
