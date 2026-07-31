"""Models describing what a mental model refresh did.

A refresh resolves a scope, picks full-vs-delta, runs reflect over a bounded
snapshot, and (in delta mode) applies structured operations to the existing
document. Every one of those steps can quietly produce a document that isn't
what the user expected, and until now the reasoning behind each only ever
reached a log line.

These models carry that reasoning out to callers, so both the dry run (preview,
nothing persisted) and ``trigger.keep_trace`` (recorded on every real refresh,
including the cron- and consolidation-driven ones no human is watching) can
report it.

Kept out of ``response_models`` on purpose: these reference the tag-group types
from ``search.tags``, and ``response_models`` is imported early enough in the
engine's import graph that pulling the search package in from there is a cycle.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .response_models import LLMCallTrace, TokenUsage
from .search.tags import TagGroup, TagsMatch

RefreshMode = Literal["full", "delta"]

ModeFallbackReason = Literal[
    "no_baseline_content",
    "source_query_changed",
    "structured_doc_unreadable",
    "delta_ops_failed",
]

RefreshOutcome = Literal[
    "content_written",
    "content_preserved_no_new_facts",
    "refresh_failed_empty_candidate",
]


class MentalModelRefreshOverrides(BaseModel):
    """Per-run overrides for a mental model refresh.

    Only meaningful for the dry run, which uses them to A/B a candidate
    configuration against the model's stored one without editing the model.
    Every field defaults to None, meaning "use the model's stored setting".
    """

    mode: RefreshMode | None = Field(default=None, description="Override the refresh mode (full or delta).")
    source_query: str | None = Field(default=None, description="Override the query reflect answers.")
    tags: list[str] | None = Field(default=None, description="Override the model's tags.")
    tags_match: TagsMatch | None = Field(default=None, description="Override how tags filter memories.")
    tag_groups: list[TagGroup] | None = Field(
        default=None, description="Override with compound boolean tag expressions."
    )
    fact_types: list[Literal["world", "experience", "observation"]] | None = Field(
        default=None, description="Override which fact types reflect retrieves."
    )
    exclude_mental_models: bool | None = Field(
        default=None, description="Override whether other mental models are excluded from the reflect loop."
    )
    max_tokens: int | None = Field(default=None, description="Override the synthesis token cap.")
    include_chunks: bool | None = Field(
        default=None, description="Override whether the internal recall returns raw chunk text."
    )
    recall_max_tokens: int | None = Field(default=None, description="Override the fact token budget for recall.")
    recall_chunks_max_tokens: int | None = Field(
        default=None, description="Override the raw-chunk token budget for recall."
    )


class MentalModelRefreshScope(BaseModel):
    """The memory scope a refresh actually resolved to.

    A model's stored ``tags`` are not what filters memories — ``tags_match``
    defaults to ``all_strict`` when tags are present, and ``tag_groups``
    override flat tags entirely. This reports the resolved result.
    """

    tags: list[str] | None = Field(default=None, description="Flat tags used to filter memories (null when unused).")
    tags_match: TagsMatch = Field(description="Resolved tag match mode.")
    tag_groups: list[TagGroup] | None = Field(
        default=None, description="Compound tag expressions used instead of flat tags, when set."
    )
    fact_types: list[str] | None = Field(default=None, description="Fact types retrieved (null means all).")
    exclude_mental_models: bool = Field(description="Whether other mental models were excluded from the reflect loop.")
    exclude_mental_model_ids: list[str] = Field(
        default_factory=list, description="Mental models excluded by ID (always includes the model being refreshed)."
    )


class MentalModelRefreshWindow(BaseModel):
    """The time window a refresh read memories from."""

    created_after: datetime | None = Field(
        default=None,
        description=(
            "Lower bound on memory creation time. Set only in delta mode, where it is the model's "
            "last_refreshed_at — so a delta refresh only sees memories newer than the last one."
        ),
    )
    created_before: datetime = Field(
        description=(
            "Database-time snapshot bounding the refresh. Memories committed after this are not read, "
            "so they stay newer than the persisted watermark and are caught by the next refresh."
        )
    )
    watermark: datetime | None = Field(
        default=None,
        description=(
            "The last_refreshed_at a real refresh would persist: the newest in-scope memory visible at "
            "the snapshot, not now(). Null means no in-scope memory was visible."
        ),
    )


class MentalModelFactCounts(BaseModel):
    """Facts the refresh saw, keyed by fact type.

    ``retrieved`` and ``used`` diverging is the single most common cause of a
    disappointing refresh: recall found plenty, but the reflect agent declared
    none of it relevant to the topic, so none of it reached the document.
    """

    retrieved: dict[str, int] = Field(
        default_factory=dict, description="Facts the reflect agent's tool calls returned, by fact type."
    )
    used: dict[str, int] = Field(
        default_factory=dict, description="Facts the agent declared it actually based the answer on, by fact type."
    )


class MentalModelDeltaOperations(BaseModel):
    """Structured operations a delta refresh emitted against the existing document."""

    applied: list[dict[str, Any]] = Field(
        default_factory=list, description="Operations applied to the document, in order."
    )
    skipped: list[dict[str, Any]] = Field(
        default_factory=list, description="Operations dropped as invalid, each with a reason."
    )


class MentalModelTraceToolCall(BaseModel):
    """One reflect tool call made during a refresh.

    Tool *outputs* are deliberately reduced to ``result_count``: a refresh trace
    is persisted on the model row and re-read on every fetch, so embedding full
    recall payloads would bloat it without bound. Raw prompts and responses are
    available separately via LLM request tracing.
    """

    tool: str = Field(description="Tool name: recall, search_observations, get_mental_model, expand, …")
    reason: str | None = Field(default=None, description="The agent's stated reason for the call.")
    input: dict[str, Any] = Field(default_factory=dict, description="Tool input parameters.")
    result_count: int | None = Field(default=None, description="Number of items the tool returned, when countable.")
    duration_ms: int = Field(description="Execution time in milliseconds.")
    iteration: int = Field(default=0, description="Agent loop iteration (1-based) this call belongs to.")


class MentalModelRefreshTrace(BaseModel):
    """Execution trace of a mental model refresh, recorded when trigger.keep_trace is on."""

    recorded_at: datetime | None = Field(default=None, description="When this trace was recorded.")
    effective_mode: RefreshMode = Field(description="Whether the refresh ran as full or delta.")
    mode_fallback_reason: ModeFallbackReason | None = Field(
        default=None, description="Why delta was requested but not applied, if that happened."
    )
    outcome: RefreshOutcome = Field(description="What the refresh did with the document.")
    scope: MentalModelRefreshScope | None = Field(default=None, description="The resolved memory scope.")
    window: MentalModelRefreshWindow | None = Field(default=None, description="The snapshot window read from.")
    facts: MentalModelFactCounts = Field(
        default_factory=MentalModelFactCounts, description="Facts retrieved versus actually used."
    )
    tool_calls: list[MentalModelTraceToolCall] = Field(
        default_factory=list, description="Reflect tool calls made during the refresh."
    )
    llm_calls: list[LLMCallTrace] = Field(default_factory=list, description="LLM calls made during the refresh.")
    delta_operations: MentalModelDeltaOperations | None = Field(
        default=None, description="Structured operations emitted, in delta mode."
    )
    usage: TokenUsage | None = Field(default=None, description="Token usage across the refresh's LLM calls.")
    duration_ms: int = Field(default=0, description="Wall-clock duration of the refresh.")
    warnings: list[str] = Field(
        default_factory=list, description="Conditions worth a human's attention, in plain language."
    )


class MentalModelDryRunRefreshResult(BaseModel):
    """Preview of what a mental model refresh would do, having changed nothing.

    Runs the real pipeline — same scope resolution, same reflect call, same
    delta operations — then reports the result instead of persisting it. The
    model's content, structured content, watermark, and last_refreshed_at are
    all left untouched, so a delta dry run is repeatable: it reads the same
    window the next real refresh would.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mental_model_id": "coding-style",
                "name": "Coding Style",
                "requested_mode": "delta",
                "effective_mode": "full",
                "mode_fallback_reason": "source_query_changed",
                "outcome": "content_written",
                "would_persist": True,
                "facts": {"retrieved": {"observation": 12}, "used": {"observation": 4}},
                "warnings": [],
            }
        }
    )

    mental_model_id: str = Field(description="The mental model previewed.")
    name: str = Field(description="Display name of the mental model.")
    requested_mode: RefreshMode = Field(description="The mode asked for (from the model's trigger, or overridden).")
    effective_mode: RefreshMode = Field(description="The mode the refresh actually ran in.")
    mode_fallback_reason: ModeFallbackReason | None = Field(
        default=None, description="Why delta was requested but not applied, if that happened."
    )
    outcome: RefreshOutcome = Field(description="What a real refresh would do with the document.")
    would_persist: bool = Field(description="Whether a real refresh would write new content.")
    scope: MentalModelRefreshScope = Field(description="The resolved memory scope.")
    window: MentalModelRefreshWindow = Field(description="The snapshot window read from.")
    facts: MentalModelFactCounts = Field(description="Facts retrieved versus actually used.")
    current_content: str = Field(description="The model's content as it stands now.")
    candidate_content: str = Field(description="Raw reflect synthesis, before any delta operations.")
    preview_content: str = Field(
        description="The content a real refresh would store: the delta-edited document, or the candidate in full mode."
    )
    diff: str = Field(description="Unified diff from current_content to preview_content. Empty when identical.")
    delta_operations: MentalModelDeltaOperations | None = Field(
        default=None, description="Structured operations emitted, in delta mode."
    )
    trace: MentalModelRefreshTrace = Field(description="Execution trace of the run, always included for a dry run.")
    usage: TokenUsage = Field(default_factory=TokenUsage, description="Token usage across the run's LLM calls.")
    duration_ms: int = Field(default=0, description="Wall-clock duration of the run.")
    warnings: list[str] = Field(
        default_factory=list, description="Conditions worth a human's attention, in plain language."
    )
