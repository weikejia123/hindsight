"""Tests for the mental model refresh dry run and the keep_trace flag.

Both features exist to answer the same question — "why did this refresh produce
that document?" — from two directions:

- ``dry_run_refresh_mental_model`` runs the real pipeline and reports what it
  would do, before it does it. Its contract is that it changes nothing, so a
  delta dry run reads the same window the next real refresh will.
- ``trigger.keep_trace`` records the same reasoning on every real refresh,
  which is the only way to see how a cron- or consolidation-driven refresh
  reached its result after the fact.

These are deterministic tests: reflect and the delta LLM call are both patched,
so what is under test is the refresh's own branching and reporting, not model
behaviour.
"""

import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio

from hindsight_api import MemoryEngine, RequestContext
from hindsight_api.engine.mental_model_refresh import MentalModelRefreshOverrides
from hindsight_api.engine.response_models import ReflectResult


def _reflect_result(
    text: str,
    *,
    facts: list[dict[str, Any]] | None = None,
    retrieved: list[dict[str, Any]] | None = None,
) -> ReflectResult:
    """Build a ReflectResult with a tool trace.

    ``facts`` become ``based_on`` (what the agent declared it used); ``retrieved``
    become a recall tool call's output (what retrieval actually returned). The
    two are deliberately independent so tests can drive them apart.
    """
    return ReflectResult.model_validate(
        {
            "text": text,
            "based_on": {
                "observation": facts or [],
                "world": [],
                "experience": [],
                "mental-models": [],
                "directives": [],
            },
            "tool_trace": [
                {
                    "tool": "recall",
                    "input": {"query": "anything"},
                    "output": {"memories": retrieved if retrieved is not None else (facts or [])},
                    "duration_ms": 12,
                    "iteration": 1,
                }
            ],
            "llm_trace": [{"scope": "agent_1", "duration_ms": 34}],
        }
    )


@pytest.fixture
def patch_reflect(monkeypatch):
    """Patch reflect_async with a canned result, recording the kwargs it was called with."""

    def _install(
        memory: MemoryEngine,
        *,
        text: str,
        facts: list[dict[str, Any]] | None = None,
        retrieved: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        async def fake_reflect_async(**kwargs):
            calls.append(kwargs)
            return _reflect_result(text, facts=facts, retrieved=retrieved)

        monkeypatch.setattr(memory, "reflect_async", fake_reflect_async)
        return calls

    return _install


@pytest.fixture
def patch_delta_llm(monkeypatch):
    """Patch the structured-delta LLM call with canned operations, or an exception."""

    def _install(memory: MemoryEngine, *, returns: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        async def fake_call(*, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            if isinstance(returns, Exception):
                raise returns
            return returns

        monkeypatch.setattr(memory._reflect_llm_config, "call", fake_call)
        return calls

    return _install


async def _make_bank(memory: MemoryEngine, request_context: RequestContext, prefix: str) -> str:
    bank_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    await memory.get_bank_profile(bank_id, request_context=request_context)
    return bank_id


class TestDryRunPersistsNothing:
    """The dry run's core contract: it is a read."""

    async def test_dry_run_leaves_the_model_untouched(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-noop")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal content.",
            trigger={"mode": "full"},
            request_context=request_context,
        )
        before = await memory.get_mental_model(bank_id, mm["id"], request_context=request_context)

        patch_reflect(memory, text="# Team\n\nCompletely rewritten.")
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result is not None
        assert result.preview_content == "# Team\n\nCompletely rewritten."
        assert result.would_persist is True

        after = await memory.get_mental_model(bank_id, mm["id"], request_context=request_context)
        assert after["content"] == before["content"], "dry run must not write content"
        assert after["last_refreshed_at"] == before["last_refreshed_at"], (
            "dry run must not advance last_refreshed_at, or the next real refresh would "
            "read a window that skips memories the dry run consumed"
        )

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_dry_run_reports_a_diff_against_current_content(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-diff")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nAlice leads backend.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nBob leads backend.")
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert "-Alice leads backend." in result.diff
        assert "+Bob leads backend." in result.diff
        assert result.current_content == "# Team\n\nAlice leads backend."

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_dry_run_returns_none_for_unknown_model(self, memory: MemoryEngine, request_context: RequestContext):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-404")
        result = await memory.dry_run_refresh_mental_model(bank_id, "does-not-exist", request_context=request_context)
        assert result is None
        await memory.delete_bank(bank_id, request_context=request_context)


class TestDryRunExplainsTheModeDecision:
    """Delta silently degrades to full in several ways. The dry run names which."""

    async def test_delta_without_baseline_reports_no_baseline_content(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect, patch_delta_llm
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-nobase")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="",
            trigger={"mode": "delta"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nFresh synthesis.")
        delta_calls = patch_delta_llm(memory, returns='{"operations": []}')

        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.requested_mode == "delta"
        assert result.effective_mode == "full"
        assert result.mode_fallback_reason == "no_baseline_content"
        assert delta_calls == [], "no baseline means the delta LLM call is skipped entirely"
        assert result.window.created_after is None, "a full fallback must read the unbounded window"

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_source_query_override_reports_source_query_changed(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect, patch_delta_llm
    ):
        """Overriding the query is exactly the condition delta refuses to edit through."""
        bank_id = await _make_bank(memory, request_context, "test-dryrun-querychg")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nEstablished content.",
            trigger={"mode": "delta"},
            request_context=request_context,
        )
        # Give the model a delta baseline by recording the query it last refreshed on.
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            last_refreshed_source_query="Tell me about the team",
            request_context=request_context,
        )

        reflect_calls = patch_reflect(memory, text="# Team\n\nDifferent topic entirely.")
        patch_delta_llm(memory, returns='{"operations": []}')

        result = await memory.dry_run_refresh_mental_model(
            bank_id,
            mm["id"],
            overrides=MentalModelRefreshOverrides(source_query="What are the team's hiring plans?"),
            request_context=request_context,
        )

        assert result.effective_mode == "full"
        assert result.mode_fallback_reason == "source_query_changed"
        assert reflect_calls[0]["query"] == "What are the team's hiring plans?"

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_delta_ops_failure_warns_that_older_content_is_dropped(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect, patch_delta_llm
    ):
        """A failed delta call falls back to a candidate built from a delta-scoped
        recall, so writing it whole would drop everything grounded in older
        memories. The dry run has to say so — this is invisible in the result."""
        bank_id = await _make_bank(memory, request_context, "test-dryrun-deltafail")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nYears of accumulated detail.",
            trigger={"mode": "delta"},
            request_context=request_context,
        )
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            last_refreshed_source_query="Tell me about the team",
            request_context=request_context,
        )

        patch_reflect(
            memory,
            text="# Team\n\nOnly the newest fact.",
            facts=[{"id": "f1", "text": "Carol joined", "fact_type": "observation"}],
        )
        patch_delta_llm(memory, returns=RuntimeError("provider exploded"))

        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.effective_mode == "full"
        assert result.mode_fallback_reason == "delta_ops_failed"
        assert any("not carried over" in w or "not applied" in w for w in result.warnings), result.warnings

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_mode_override_forces_full_on_a_delta_model(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect, patch_delta_llm
    ):
        """The point of the override: compare what full would produce without
        editing the model's stored trigger."""
        bank_id = await _make_bank(memory, request_context, "test-dryrun-modeovr")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nEstablished content.",
            trigger={"mode": "delta"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nFull rebuild.")
        delta_calls = patch_delta_llm(memory, returns='{"operations": []}')

        result = await memory.dry_run_refresh_mental_model(
            bank_id, mm["id"], overrides=MentalModelRefreshOverrides(mode="full"), request_context=request_context
        )

        assert result.requested_mode == "full"
        assert result.effective_mode == "full"
        assert result.mode_fallback_reason is None, "an explicit full run is not a fallback"
        assert delta_calls == []

        await memory.delete_bank(bank_id, request_context=request_context)


class TestDryRunReportsRetrievalHealth:
    """The most common refresh complaint is 'it didn't pick up my memories'."""

    async def test_retrieved_and_used_counts_are_reported_separately(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-counts")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(
            memory,
            text="# Team\n\nRewritten.",
            facts=[{"id": "f1", "text": "used one", "fact_type": "observation"}],
            retrieved=[
                {"id": "f1", "text": "used one", "fact_type": "observation"},
                {"id": "f2", "text": "ignored", "fact_type": "observation"},
                {"id": "f3", "text": "also ignored", "fact_type": "world"},
            ],
        )

        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.facts.retrieved == {"observation": 2, "world": 1}
        assert result.facts.used == {"observation": 1}

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_retrieval_returning_nothing_is_called_out(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-empty")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nNothing to say.", facts=[], retrieved=[])
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.facts.retrieved == {}
        assert any("no facts" in w.lower() for w in result.warnings), result.warnings

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_facts_retrieved_but_unused_is_called_out(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-unused")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(
            memory,
            text="# Team\n\nGeneric prose.",
            facts=[],
            retrieved=[{"id": "f1", "text": "off topic", "fact_type": "observation"}],
        )
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert any("used none" in w for w in result.warnings), result.warnings

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_empty_candidate_reports_the_failing_outcome(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        """A real refresh raises here. The dry run reports it instead, and says
        the stored content would survive."""
        bank_id = await _make_bank(memory, request_context, "test-dryrun-emptycand")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nStill here.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="   ")
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.outcome == "refresh_failed_empty_candidate"
        assert result.would_persist is False
        assert result.preview_content == "# Team\n\nStill here."
        assert result.diff == "", "nothing would change, so there is nothing to diff"

        await memory.delete_bank(bank_id, request_context=request_context)


class TestDryRunScopeResolution:
    """A model's stored tags are not what filters memories; the resolved scope is."""

    async def test_stored_tags_resolve_to_all_strict(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-scope")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            tags=["team-a"],
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nRewritten.")
        result = await memory.dry_run_refresh_mental_model(bank_id, mm["id"], request_context=request_context)

        assert result.scope.tags == ["team-a"]
        assert result.scope.tags_match == "all_strict", (
            "tagged models default to all_strict for isolation — untagged memories are excluded, "
            "which is the usual reason a tagged model looks starved"
        )
        assert mm["id"] in result.scope.exclude_mental_model_ids

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_tags_match_override_changes_the_resolved_scope(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-scopeovr")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            tags=["team-a"],
            trigger={"mode": "full"},
            request_context=request_context,
        )

        reflect_calls = patch_reflect(memory, text="# Team\n\nRewritten.")
        result = await memory.dry_run_refresh_mental_model(
            bank_id, mm["id"], overrides=MentalModelRefreshOverrides(tags_match="any"), request_context=request_context
        )

        assert result.scope.tags_match == "any"
        assert reflect_calls[0]["tags_match"] == "any", "the override must reach reflect, not just the report"

        stored = await memory.get_mental_model(bank_id, mm["id"], request_context=request_context)
        assert (stored["trigger"] or {}).get("tags_match") is None, "an override must not edit the model"

        await memory.delete_bank(bank_id, request_context=request_context)


class TestKeepTrace:
    """``trigger.keep_trace`` records on real refreshes what the dry run returns."""

    async def test_trace_is_absent_by_default(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-trace-off")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nRewritten.")
        refreshed = await memory.refresh_mental_model(
            bank_id=bank_id, mental_model_id=mm["id"], request_context=request_context
        )

        assert "trace" not in (refreshed.get("reflect_response") or {})

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_trace_is_recorded_when_enabled(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        bank_id = await _make_bank(memory, request_context, "test-trace-on")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full", "keep_trace": True},
            request_context=request_context,
        )

        patch_reflect(
            memory,
            text="# Team\n\nRewritten.",
            facts=[{"id": "f1", "text": "used", "fact_type": "observation"}],
            retrieved=[
                {"id": "f1", "text": "used", "fact_type": "observation"},
                {"id": "f2", "text": "unused", "fact_type": "observation"},
            ],
        )
        refreshed = await memory.refresh_mental_model(
            bank_id=bank_id, mental_model_id=mm["id"], request_context=request_context
        )

        trace = (refreshed.get("reflect_response") or {}).get("trace")
        assert trace is not None
        assert trace["effective_mode"] == "full"
        assert trace["outcome"] == "content_written"
        assert trace["facts"]["retrieved"] == {"observation": 2}
        assert trace["facts"]["used"] == {"observation": 1}
        assert trace["scope"]["tags_match"] == "any"
        assert trace["window"]["created_before"] is not None
        assert [tc["tool"] for tc in trace["tool_calls"]] == ["recall"]
        assert trace["tool_calls"][0]["result_count"] == 2
        assert "output" not in trace["tool_calls"][0], "tool outputs must not be persisted verbatim"
        assert [lc["scope"] for lc in trace["llm_calls"]] == ["agent_1"]

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_trace_records_a_failed_refresh(
        self, memory: MemoryEngine, request_context: RequestContext, patch_reflect
    ):
        """The failure case is the one worth recording: a refresh that raised
        leaves nothing else behind to inspect."""
        from hindsight_api.engine.memory_engine import MentalModelRefreshError

        bank_id = await _make_bank(memory, request_context, "test-trace-fail")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nStill here.",
            trigger={"mode": "full", "keep_trace": True},
            request_context=request_context,
        )

        patch_reflect(memory, text="")
        with pytest.raises(MentalModelRefreshError):
            await memory.refresh_mental_model(
                bank_id=bank_id, mental_model_id=mm["id"], request_context=request_context
            )

        stored = await memory.get_mental_model(bank_id, mm["id"], request_context=request_context)
        assert stored["content"] == "# Team\n\nStill here."
        trace = (stored.get("reflect_response") or {}).get("trace")
        assert trace is not None
        assert trace["outcome"] == "refresh_failed_empty_candidate"

        await memory.delete_bank(bank_id, request_context=request_context)


@pytest_asyncio.fixture
async def api_client(memory: MemoryEngine):
    """FastAPI test client over the same engine the other tests drive directly."""
    from hindsight_api.api.http import create_app

    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestDryRunRefreshEndpoint:
    """HTTP surface of the dry run: routing, body handling, and the 404 path."""

    async def test_endpoint_returns_the_preview(
        self,
        memory: MemoryEngine,
        request_context: RequestContext,
        api_client: httpx.AsyncClient,
        patch_reflect,
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-http")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nRewritten.")
        response = await api_client.post(
            f"/v1/default/banks/{bank_id}/mental-models/{mm['id']}/dry-run-refresh",
            json={},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_content"] == "# Team\n\nRewritten."
        assert body["effective_mode"] == "full"
        assert body["would_persist"] is True
        assert "trace" in body

        stored = await memory.get_mental_model(bank_id, mm["id"], request_context=request_context)
        assert stored["content"] == "# Team\n\nOriginal.", "the endpoint must not persist"

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_endpoint_accepts_overrides(
        self,
        memory: MemoryEngine,
        request_context: RequestContext,
        api_client: httpx.AsyncClient,
        patch_reflect,
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-http-ovr")
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team Info",
            source_query="Tell me about the team",
            content="# Team\n\nOriginal.",
            tags=["team-a"],
            trigger={"mode": "full"},
            request_context=request_context,
        )

        patch_reflect(memory, text="# Team\n\nRewritten.")
        response = await api_client.post(
            f"/v1/default/banks/{bank_id}/mental-models/{mm['id']}/dry-run-refresh",
            json={"tags_match": "any"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["scope"]["tags_match"] == "any"

        await memory.delete_bank(bank_id, request_context=request_context)

    async def test_endpoint_404s_for_unknown_model(
        self,
        memory: MemoryEngine,
        request_context: RequestContext,
        api_client: httpx.AsyncClient,
    ):
        bank_id = await _make_bank(memory, request_context, "test-dryrun-http-404")
        response = await api_client.post(
            f"/v1/default/banks/{bank_id}/mental-models/nope/dry-run-refresh",
            json={},
        )
        assert response.status_code == 404, response.text
        await memory.delete_bank(bank_id, request_context=request_context)
