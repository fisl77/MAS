"""Public action schemas contain syntax constraints, never hidden biological rules."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RULE_VERSION = "farm-1.0"
PROMPT_VERSION = "farm-agent-1.2"


def water(value: str | int) -> Fraction:
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d.as_tuple().exponent < -3:
            raise ValueError("Water must be nonnegative with at most three decimal places.")
        return Fraction(d)
    except InvalidOperation as exc:
        raise ValueError("Invalid water amount.") from exc


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Config(Strict):
    agent_count: int = Field(default=2, ge=2, le=5, strict=True)
    profiles: list[Literal["short_term", "reciprocal"]] = Field(default_factory=list)
    controller: Literal["test", "ollama"] = "test"
    scenario: Literal["balanced", "scarcity", "returns", "insolvency"] = "balanced"
    model: str = "llama3.2:3b"
    communication: bool = False
    seed: int = 42
    test_mode: bool = True
    rounds: int = Field(default=20, ge=1, le=1000, strict=True)
    start_agent: int = Field(default=0, ge=0, strict=True)
    temperature: float = Field(default=0, ge=0, le=2)
    context_tokens: int = Field(default=16384, ge=4096, le=131072)
    output_tokens: int = Field(default=2048, ge=256, le=8192)
    timeout_seconds: int = Field(default=180, ge=10, le=1800)
    output_directory: str = "data/exports"

    @model_validator(mode="after")
    def coherent(self):
        if not self.test_mode and self.rounds != 1000:
            raise ValueError("Regular research games must contain 1,000 rounds.")
        if self.controller == "test" and not self.test_mode:
            raise ValueError("Scripted agents are only available in technical test mode.")
        if self.start_agent >= self.agent_count:
            raise ValueError("Starting agent must exist.")
        if not self.profiles:
            self.profiles = (["short_term", "reciprocal"] if self.agent_count == 2
                             else ["short_term"] * ((self.agent_count + 1) // 2)
                             + ["reciprocal"] * (self.agent_count // 2))
        if len(self.profiles) != self.agent_count:
            raise ValueError("Choose one profile per agent.")
        return self


class NewPlants(Strict):
    count: int = Field(ge=1, strict=True)
    water_per_plant: str

    @field_validator("water_per_plant")
    @classmethod
    def valid_water(cls, v):
        water(v)
        return v


class Irrigation(NewPlants):
    group_id: str


class Limit(Strict):
    agent_id: str
    max_request: int | None = Field(default=None, ge=0, strict=True)
    max_net: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.max_request is None and self.max_net is None:
            raise ValueError("Specify at least one limit.")
        if self.max_net is not None:
            water(self.max_net)
        return self


class ContractAction(Strict):
    kind: Literal["propose", "accept", "reject", "cancel"]
    contract_id: str | None = None
    replaces: str | None = None
    start_round: int | None = Field(default=None, ge=1, strict=True)
    end_round: int | None = Field(default=None, ge=1, strict=True)
    limits: list[Limit] = Field(default_factory=list)


class Decision(Strict):
    """One bounded decision; memory and recall are always private."""
    memory: str | None = Field(default=None, max_length=4000)
    recall_query: str = Field(default="", max_length=200)
    request: int | None = Field(default=None, ge=0, strict=True)
    new_plants: list[NewPlants] = Field(default_factory=list)
    irrigation: list[Irrigation] = Field(default_factory=list)
    message: str = Field(default="", max_length=2000)
    contracts: list[ContractAction] = Field(default_factory=list, max_length=10)
    pass_turn: bool = True


class PrivateNotes(Strict):
    memory: str | None = Field(default=None, max_length=4000)
    recall_query: str = Field(default="", max_length=200)


class WaterRequest(PrivateNotes):
    request: int = Field(ge=0, strict=True)


class FarmWork(PrivateNotes):
    new_plants: list[NewPlants] = Field(default_factory=list)
    irrigation: list[Irrigation] = Field(default_factory=list)


class PrivateReflection(PrivateNotes):
    pass_turn: bool = True


class PublicDiscussion(PrivateReflection):
    message: str = Field(default="", max_length=2000)
    contracts: list[ContractAction] = Field(default_factory=list, max_length=10)


def response_model(phase, communication):
    """Expose only actions available now, not the complete internal union."""
    if phase == 1:
        return PrivateNotes
    if phase == 3:
        return WaterRequest
    if phase == 4:
        return FarmWork
    if phase in (2, 7):
        return PublicDiscussion if communication else PrivateReflection
    raise ValueError("This phase has no agent decisions.")
