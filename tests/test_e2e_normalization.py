from typing import Literal

import anyio
import pytest

from agent.contracts import Gap, GapId, QuestionKey, SourceSpan
from agent.essay_llm import GenerationError
from agent.stage_analysis_models import AnalysisOutput
from agent.stage_structure_models import StructureOutput
from tests.e2e_normalization_support import analysis_pair, structure_pair
from tests.llm_support import completion, provider


def test_real_sdk_unique_quote_offsets_are_server_computed() -> None:
    payload, output = analysis_pair()
    wrong = output.facts[0].model_copy(update={"span": SourceSpan(start=1, end=2)})
    proposal = output.model_copy(update={"facts": (wrong, *output.facts[1:])})

    async def run() -> None:
        reply = completion(proposal.model_dump_json())
        async with provider((reply, reply)) as harness:
            result = await harness.adapter.generate("analyze_context", payload, AnalysisOutput)
            assert result.output.facts == output.facts
            assert len(harness.requests) == 1
            assert result.usage.attempts[0].total_tokens == 18

    anyio.run(run)


@pytest.mark.parametrize("case", ["ambiguous", "missing", "wrong_source", "kind", "version"])
def test_real_sdk_alignment_preserves_strict_evidence_rejections(
    case: Literal["ambiguous", "missing", "wrong_source", "kind", "version"],
) -> None:
    payload, output = analysis_pair()
    fact = output.facts[0].model_copy(update={"span": SourceSpan(start=1, end=2)})
    if case == "ambiguous":
        source = payload.sources[0]
        payload = payload.model_copy(
            update={
                "sources": (
                    source.model_copy(update={"text": source.text + source.text}),
                    *payload.sources[1:],
                )
            }
        )
    elif case == "missing":
        fact = fact.model_copy(update={"quote": "not in any supplied source"})
    elif case == "wrong_source":
        fact = fact.model_copy(update={"source_id": output.facts[1].source_id})
    elif case == "kind":
        fact = fact.model_copy(update={"source_kind": output.facts[-1].source_kind})
    else:
        source = payload.sources[0].model_copy(update={"evidence_version": "wrong-version"})
        payload = payload.model_copy(update={"sources": (source, *payload.sources[1:])})
    proposal = output.model_copy(update={"facts": (fact, *output.facts[1:])})

    async def run() -> None:
        reply = completion(proposal.model_dump_json())
        async with provider((reply, reply)) as harness:
            with pytest.raises(GenerationError):
                _ = await harness.adapter.generate("analyze_context", payload, AnalysisOutput)
            assert len(harness.requests) == 2

    anyio.run(run)


def test_already_valid_ambiguous_span_is_preserved() -> None:
    payload, output = analysis_pair()
    source = payload.sources[0]
    payload = payload.model_copy(
        update={
            "sources": (
                source.model_copy(update={"text": source.text + source.text}),
                *payload.sources[1:],
            )
        }
    )
    parsed = AnalysisOutput.model_validate(output.model_dump(), context={"payload": payload})
    assert parsed.facts == output.facts


def test_real_sdk_derived_budget_does_not_reject_before_allocator() -> None:
    payload, output = structure_pair()
    policy = payload.request.length_policy.model_copy(
        update={"max_chars": 500, "include_subtitle": True}
    )
    payload = payload.model_copy(
        update={"request": payload.request.model_copy(update={"length_policy": policy})}
    )
    budget = output.outline.budget.model_copy(
        update={"max_chars": 500, "subtitle_reserved_chars": None}
    )
    proposal = output.model_copy(
        update={"outline": output.outline.model_copy(update={"budget": budget})}
    )

    async def run() -> None:
        reply = completion(proposal.model_dump_json())
        async with provider((reply, reply)) as harness:
            result = await harness.adapter.generate("plan_structure", payload, StructureOutput)
            assert result.output.outline.budget.max_chars == 500
            assert result.output.outline.budget.subtitle_reserved_chars is not None
            assert result.output.outline.budget.subtitle_reserved_chars > 0
            assert len(harness.requests) == 1
            assert result.usage.attempts[0].total_tokens == 18

    anyio.run(run)


@pytest.mark.parametrize("case", ["weight", "reference"])
def test_budget_normalization_cannot_repair_semantic_structure(
    case: Literal["weight", "reference"],
) -> None:
    payload, output = structure_pair()
    outline = output.outline
    if case == "weight":
        first = outline.paragraphs[0].model_copy(update={"weight": 7})
        outline = outline.model_copy(update={"paragraphs": (first, *outline.paragraphs[1:])})
    else:
        first = outline.sections[0].model_copy(update={"fact_ids": ("absent-fact",)})
        outline = outline.model_copy(update={"sections": (first, *outline.sections[1:])})
    proposal = output.model_copy(update={"outline": outline})

    async def run() -> None:
        reply = completion(proposal.model_dump_json())
        async with provider((reply, reply)) as harness:
            with pytest.raises(GenerationError):
                _ = await harness.adapter.generate("plan_structure", payload, StructureOutput)
            assert len(harness.requests) == 2

    anyio.run(run)


def test_authoritative_unknown_budget_remains_null() -> None:
    payload, output = structure_pair()
    policy = payload.request.length_policy.model_copy(update={"max_chars": None})
    payload = payload.model_copy(
        update={"request": payload.request.model_copy(update={"length_policy": policy})}
    )
    budget = output.outline.budget.model_copy(
        update={"max_chars": 500, "subtitle_reserved_chars": 20, "usable_body_chars": 480}
    )
    proposal = output.model_copy(
        update={"outline": output.outline.model_copy(update={"budget": budget})}
    )
    result = StructureOutput.model_validate(proposal.model_dump(), context={"payload": payload})
    assert result.outline.budget.max_chars is None
    assert result.outline.budget.subtitle_reserved_chars is None
    assert result.outline.budget.usable_body_chars is None
    assert all(paragraph.target_chars is None for paragraph in result.outline.paragraphs)


@pytest.mark.parametrize("case", ["links", "gaps", "empty", "blank_reason"])
def test_real_sdk_declared_candidate_relations_need_explicit_decisions(
    case: Literal["links", "gaps", "empty", "blank_reason"],
) -> None:
    payload, output = analysis_pair()
    analysis = output.analysis
    if case == "empty":
        analysis = analysis.model_copy(update={"evidence_links": (), "gaps": ()})
    elif case == "blank_reason":
        analysis = analysis.model_copy(
            update={
                "evidence_links": tuple(
                    link.model_copy(update={"reason": " "}) for link in analysis.evidence_links
                )
            }
        )
    elif case == "gaps":
        gaps = tuple(
            Gap(
                gap_id=GapId(f"G-{candidate.candidate_id}-{rid}"),
                question_key=QuestionKey(f"Q-{candidate.candidate_id}-{rid}"),
                requirement_ids=(rid,),
                candidate_id=candidate.candidate_id,
                missing_detail="추가 근거",
                why_it_matters="판단 근거가 부족합니다.",
                priority=1,
                question=None,
                question_status="proposed",
            )
            for candidate in analysis.answer_candidates
            for rid in candidate.requirement_ids
        )
        analysis = analysis.model_copy(update={"evidence_links": (), "gaps": gaps})
    proposal = output.model_copy(update={"analysis": analysis})

    async def run() -> None:
        reply = completion(proposal.model_dump_json())
        async with provider((reply, reply)) as harness:
            if case in ("links", "gaps"):
                result = await harness.adapter.generate("analyze_context", payload, AnalysisOutput)
                assert result.output.facts == output.facts
                assert len(harness.requests) == 1
            else:
                with pytest.raises(GenerationError):
                    _ = await harness.adapter.generate("analyze_context", payload, AnalysisOutput)
                assert len(harness.requests) == 2

    anyio.run(run)
