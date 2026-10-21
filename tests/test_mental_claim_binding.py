from pathlib import Path
from typing import Literal

import anyio
import pytest

from agent import contracts as c
from agent.deps import SupervisorDeps
from agent.essay_llm import Output, Stage
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph_state import EssayState
from agent.stage_composition_nodes import write_sections
from agent.stage_writing_models import WritingOutput
from agent.stage_writing_validation import validate_allocation_sentence
from tests.composition_adversarial_support import prepared_context
from tests.fixtures.cases import ContractCase
from tests.writing_boundary_support import context_for


def stated_context(context: c.ContractContext) -> c.ContractContext:
    text = "I learned to agree on a method before starting."
    source = next(s for s in context.sources if s.source_id == "source-library")
    start = len(source.text) + 1
    return context.model_copy(
        update={
            "sources": tuple(
                s.model_copy(update={"text": s.text + "\n" + text})
                if s.source_id == "source-library"
                else s
                for s in context.sources
            ),
            "facts": tuple(
                f.model_copy(
                    update={
                        "quote": text,
                        "span": c.SourceSpan(start=start, end=start + len(text)),
                        "claim_kind": "stated_view",
                    }
                )
                if f.fact_id == "fact-library"
                else f
                for f in context.facts
            ),
        }
    )


def check_learning(context: c.ContractContext, fact_ids: tuple[c.FactId, ...]) -> None:
    draft = context.section_drafts[0]
    allocation = draft.allocations[0]
    sentence = allocation.sentences[0].model_copy(
        update={
            "text": "I learned to agree on a method before starting.",
            "claim_kind": "stated_view",
            "fact_ids": fact_ids,
        }
    )
    validate_allocation_sentence(sentence, draft, allocation.planned_paragraph_id, context)


def test_event_alone_cannot_establish_personal_learning() -> None:
    context = prepared_context()
    with pytest.raises(c.ContractViolation, match="stated_view_evidence"):
        check_learning(context, (c.FactId("fact-library"),))


def test_explicit_available_personal_learning_is_accepted() -> None:
    context = stated_context(prepared_context())
    c.validate_contract(context)
    check_learning(context, (c.FactId("fact-library"),))


def test_view_and_event_context_are_both_allowed() -> None:
    context = stated_context(context_for("merged"))
    c.validate_contract(context)
    check_learning(context, (c.FactId("fact-library"), c.FactId("fact-garden")))


@pytest.mark.parametrize("state", ["unverified", "conflicting"])
def test_unavailable_view_is_not_positive_evidence(
    state: Literal["unverified", "conflicting"],
) -> None:
    context = stated_context(prepared_context())
    context = context.model_copy(
        update={
            "facts": tuple(
                f.model_copy(update={"information_state": state})
                if f.fact_id == "fact-library"
                else f
                for f in context.facts
            )
        }
    )
    with pytest.raises(c.ContractViolation):
        check_learning(context, (c.FactId("fact-library"),))


@pytest.mark.parametrize("name", ["complete.json", "merged-sections.json", "fallback.json"])
def test_existing_event_general_and_gap_contracts_unchanged(name: str) -> None:
    c.validate_contract(ContractCase.load(name).parse())


@pytest.mark.parametrize("change", ["source", "version"])
def test_view_evidence_still_requires_current_source_and_version(
    change: Literal["source", "version"],
) -> None:
    context = stated_context(prepared_context())
    if change == "source":
        context = context.model_copy(
            update={
                "facts": (
                    context.facts[0].model_copy(update={"source_id": c.SourceId("foreign")}),
                    *context.facts[1:],
                )
            }
        )
    else:
        context = context.model_copy(
            update={
                "sources": (
                    context.sources[0].model_copy(
                        update={"evidence_version": c.EvidenceVersion("old")}
                    ),
                    *context.sources[1:],
                )
            }
        )
    with pytest.raises(c.ContractViolation):
        c.validate_contract(context)


def test_wrong_kind_recovers_valid_siblings_within_existing_retry_budget() -> None:
    context = prepared_context()
    assert context.request is not None
    assert context.analysis is not None
    assert context.outline is not None
    draft = context.section_drafts[0]
    allocation = draft.allocations[0]
    invalid = allocation.sentences[0].model_copy(
        update={"text": "I learned an unsupported personal lesson.", "claim_kind": "stated_view"}
    )
    proposal = WritingOutput(
        section_drafts=(
            draft.model_copy(
                update={"allocations": (allocation.model_copy(update={"sentences": (invalid,)}),)}
            ),
            *context.section_drafts[1:],
        ),
        notes=(),
        section_checks=(),
        personalization="partial",
    )
    calls: list[Stage] = []

    def respond(stage: Stage, payload: c.ContractModel, output_model: type[Output]) -> Output:
        del payload
        calls.append(stage)
        return output_model.model_validate(proposal.model_dump())

    state = EssayState(
        request=context.request,
        evidence_version=context.evidence_version,
        revision_context=c.RevisionContext(source_history=(), question_registry=()),
        sources=context.sources,
        facts=context.facts,
        analysis=context.analysis,
        outline=context.outline,
    )

    async def run() -> c.WritingReport:
        fast, quality = FastLLM(respond), QualityLLM(respond)
        try:
            update = await write_sections(state, SupervisorDeps(fast, quality))
            assert "section_drafts" in update
            assert "writing_report" in update
            sentences = tuple(
                s for d in update["section_drafts"] for a in d.allocations for s in a.sentences
            )
            assert sentences
            assert invalid.sentence_id not in {s.sentence_id for s in sentences}
            assert any(s.sentence_id == "sentence-two" for s in sentences)
            return update["writing_report"]
        finally:
            await fast.aclose()
            await quality.aclose()

    report = anyio.run(run)
    assert calls == ["write_sections", "write_sections"]
    assert any(note.code == "contract_mismatch" for note in report.notes)
    folder = Path("../.omo/evidence/essay-agent/task-10-mental-claim")
    folder.mkdir(parents=True, exist_ok=True)
    _ = (folder / "recovered-writing.json").write_text(report.model_dump_json(indent=2))
