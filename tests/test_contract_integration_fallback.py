import pytest

from agent.contract_base import ContractViolationError
from agent.contracts import (
    ContractContext,
    IntegrationEdit,
    Sentence,
    SentenceId,
    validate_contract,
)
from tests.fixtures.cases import ContractCase


def fallback_context() -> ContractContext:
    context = ContractCase.load("fallback.json").parse()
    assert context.bundle is not None
    assert context.integration_report is not None
    baseline = context.bundle
    ids = tuple(s.sentence_id for p in baseline.paragraphs for s in p.sentences)
    report = context.integration_report.model_copy(
        update={
            "baseline_bundle": baseline,
            "selection": "baseline",
            "candidate_version_id": baseline.version_id,
            "edits": (
                IntegrationEdit(
                    operation="retain",
                    before_sentence_ids=ids,
                    after_sentence_ids=ids,
                    section_ids=(),
                    fact_ids=(),
                    reason="Preserve declared writing fallback.",
                ),
            ),
            "length_before": context.integration_report.length_after,
            "reverse_outline": (),
            "requirement_checks": (),
        }
    )
    return context.model_copy(update={"integration_report": report, "review": None, "result": None})


def test_empty_sections_allow_exact_declared_writing_fallback_as_baseline() -> None:
    validate_contract(fallback_context())


def test_rogue_unmapped_baseline_is_not_declared_fallback() -> None:
    context = fallback_context()
    assert context.integration_report is not None
    assert context.writing_report is not None
    rogue = Sentence(
        sentence_id=SentenceId("rogue"),
        text="This was not the writing fallback.",
        section_ids=(),
        fact_ids=(),
        claim_kind="general_statement",
    )
    report = context.writing_report.model_copy(update={"fallback_sentences": (rogue,)})
    with pytest.raises(ContractViolationError):
        validate_contract(context.model_copy(update={"writing_report": report}))


def test_fallback_cannot_be_mixed_with_nonempty_section_drafts() -> None:
    context = ContractCase.load("complete.json").parse()
    fallback = fallback_context().writing_report
    assert context.writing_report is not None
    assert fallback is not None
    report = context.writing_report.model_copy(
        update={"fallback_sentences": fallback.fallback_sentences}
    )
    with pytest.raises(ContractViolationError, match="fallback_nonempty"):
        validate_contract(context.model_copy(update={"writing_report": report}))
