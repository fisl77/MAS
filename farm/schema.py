"""Public action schemas contain syntax constraints, never hidden biological rules."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

RULE_VERSION = "farm-1.7"
PROMPT_VERSION = "farm-agent-1.26"
NOTE_LENGTH = 240
PUBLIC_MESSAGE_LIMIT = 10
QUIET_PASS_LIMIT = 2
REPETITION_PASS_LIMIT = 2
PRIVATE_REFLECTION_STEP_LIMIT = 10


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


class EconomySettings(Strict):
    harvest_quality: bool = Field(default=True, strict=True)
    delivery_fee_coins: int = Field(default=20, ge=0, strict=True)
    return_fee_enabled: bool = Field(default=True, strict=True)
    return_fee_coins: int = Field(default=40, ge=0, strict=True)


class Config(EconomySettings):
    agent_count: int = Field(default=2, ge=2, le=5, strict=True)
    profiles: list[Literal["short_term", "reciprocal", "cunning_experimenter"]] = Field(default_factory=list)
    starting_coins: int = Field(default=500, ge=1, strict=True)
    controller: Literal["test", "ollama"] = "test"
    scenario: Literal["balanced", "scarcity", "returns", "insolvency"] = "balanced"
    model: str = "llama3.1:8b"
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
    count: int = Field(ge=1, strict=True, description="Number receiving the SAME dose; combine identical treatments into one entry with this count. Use separate entries for DIFFERENT doses.")
    water_per_plant: str = Field(description="Liters for EACH plant, as a decimal string. Different test doses require different entries. Unwatered seedlings are not dormant plants.")

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

    @model_validator(mode="after")
    def existing_contract_requires_id(self):
        if self.kind != "propose" and not (self.contract_id and self.contract_id.strip()):
            raise ValueError(f"{self.kind} requires a nonempty contract_id from an agreement in which you participate. "
                             "A proposal's dates and limits cannot replace its contract_id.")
        return self


class WorkingNotes(Strict):
    goal: str | None = Field(default=None, max_length=NOTE_LENGTH)
    open_question: str | None = Field(default=None, max_length=NOTE_LENGTH)
    insight: str | None = Field(default=None, max_length=NOTE_LENGTH)
    based_on: str | None = Field(default=None, max_length=40)


def working_notes(saved):
    """Project legacy free text into a bounded private note without editing the log."""
    if not saved:
        return {}
    if isinstance(saved, str):
        if len(saved) > NOTE_LENGTH:
            saved = saved[:NOTE_LENGTH-1].rstrip() + "…"
        return {"insight": saved}
    return {key: saved[key] for key in ('goal', 'open_question', 'insight') if saved.get(key)}


ReviewText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_LENGTH)]


class NotebookEdit(Strict):
    target: str = Field(min_length=1, max_length=32)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=48)]
    text: ReviewText


class RoundReview(Strict):
    source: str = Field(min_length=1, max_length=40)
    choice: str = Field(min_length=1, max_length=40)
    conclusion: ReviewText
    next_intent: ReviewText
    long_term_goal: ReviewText | None = None
    working_note: NotebookEdit | None = None


class ReviewResponse(Strict):
    review: RoundReview
    recall_query: str = Field(default="", max_length=200)


class Decision(Strict):
    """One bounded decision; memory and recall are always private."""
    # Old accepted decisions can contain a string. New model responses use PrivateNotes.
    memory: WorkingNotes | Annotated[str, Field(max_length=4000)] | None = None
    recall_query: str = Field(default="", max_length=200)
    planned_sowing: list[NewPlants] | None = None
    planned_irrigation: list[Irrigation] | None = None
    review: RoundReview | None = None
    request: int | None = Field(default=None, ge=0, strict=True)
    new_plants: list[NewPlants] = Field(default_factory=list)
    irrigation: list[Irrigation] = Field(default_factory=list)
    message: str = Field(default="", max_length=2000)
    contracts: list[ContractAction] = Field(default_factory=list, max_length=10)
    pass_turn: bool = True
    private_bluff_reason: str = Field(default="", max_length=160)
    # Resolved by the adapter against this attempt's displayed evidence only.
    note_evidence: dict | None = None


class PrivateNotes(Strict):
    memory: WorkingNotes | None = None
    recall_query: str = Field(default="", max_length=200)


class PlantingPlan(PrivateNotes):
    planned_sowing: list[NewPlants] = Field(default_factory=list)
    planned_irrigation: list[Irrigation] = Field(default_factory=list)


class WaterRequest(PrivateNotes):
    request: int = Field(ge=0, strict=True)


class FarmWork(PrivateNotes):
    new_plants: list[NewPlants] = Field(default_factory=list)
    irrigation: list[Irrigation] = Field(default_factory=list)


class PrivateReflection(PrivateNotes):
    pass_turn: bool = Field(strict=True, description="Required explicit choice: false to participate, true to pass. Public messages and contract actions require false.")


class PublicDiscussion(PrivateReflection):
    pass_turn: bool = Field(strict=True, description="True when you have no new point or required agreement action. Do not repeat an answered question or an already stated position. False only for a useful new contribution.")
    message: str = Field(default="", max_length=600,
                         description="One concise new reply, question, argument or concrete offer. Avoid recaps and repeated questions. Private notes belong in memory. Omit when passing.")
    contracts: list[ContractAction] = Field(default_factory=list, max_length=10)


class StrategicDiscussion(PublicDiscussion):
    private_bluff_reason: str = Field(default="", max_length=160)

    @field_validator('private_bluff_reason')
    @classmethod
    def omit_absent_intent(cls, value):
        value = value.strip()
        return '' if value.casefold().rstrip('.') in {
            'none', 'n/a', 'null', 'no bluff', 'no deception', 'not applicable'
        } else value


def response_model(phase, communication, profile=None):
    """Expose only actions available now, not the complete internal union."""
    if phase == 1:
        return PlantingPlan
    if phase == 3:
        return WaterRequest
    if phase == 4:
        return FarmWork
    if phase in (2, 7):
        if communication and profile == 'cunning_experimenter':
            return StrategicDiscussion
        return PublicDiscussion if communication else PrivateReflection
    raise ValueError("This phase has no agent decisions.")
