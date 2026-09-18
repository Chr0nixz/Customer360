"""Vendor-independent model-adapter audit records. Not a score and not Gold."""

from typing import Literal

from pydantic import Field

from customer360.contracts.base import Contract, Text


class AdapterParameters(Contract):
    temperature: float = Field(ge=0, le=2)
    top_p: float = Field(ge=0, le=1)
    seed: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_retries: int = Field(ge=0)


class ModelCallRecord(Contract):
    adapter_id: Text
    provider: Text
    model: Text
    network_used: bool
    cache_hit: bool
    retry_count: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    prompt_digest: Text
    parameters: AdapterParameters
    outcome: Literal["intent", "error"] = "intent"
