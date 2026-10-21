from unicodedata import normalize

import pytest

from agent import contracts as c
from agent.contract_result_validation import validate_result
from agent.delivery_structure import structure_for
from agent.review_titles import generic_title, measure_final, title_for_body
from tests.fixtures.cases import ContractCase


def test_display_and_copy_preserve_reviewed_unicode() -> None:
    # Given decomposed Hangul and a compound emoji in reviewed text.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    sentence = ctx.bundle.paragraphs[0].sentences[0].model_copy(update={"text": "가 👩‍💻"})
    bundle = ctx.bundle.model_copy(
        update={
            "subtitle": "나",
            "paragraphs": (ctx.bundle.paragraphs[0].model_copy(update={"sentences": (sentence,)}),),
        }
    )
    # When display/copy strings and character count are derived.
    body, copied = c.render_body(bundle), c.render_copy_text(bundle)
    # Then display is exact while counting alone normalizes Unicode.
    assert body == sentence.text
    assert copied == "나\n\n" + sentence.text
    assert c.count_characters(copied, c.LengthPolicy()) == len(normalize("NFC", copied))


def test_supported_coverage_accepts_positive_and_general_current_checks() -> None:
    # Given one section with positively checked personal and general sentences.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    assert ctx.review is not None
    assert ctx.result is not None
    assert ctx.outline is not None
    first = ctx.bundle.paragraphs[0]
    general = first.sentences[1].model_copy(
        update={"section_ids": (c.SectionId("section-action"),)}
    )
    bundle = ctx.bundle.model_copy(
        update={
            "paragraphs": (
                first.model_copy(update={"sentences": (first.sentences[0], general)}),
                ctx.bundle.paragraphs[1],
            )
        }
    )
    result = ctx.result.model_copy(
        update={"structure": structure_for(bundle, ctx.review, ctx.outline)}
    )
    # When the exact result package crosses the shared contract boundary.
    validate_result(ctx.model_copy(update={"bundle": bundle, "result": result}))
    # Then a positive personal check plus valid general prose remains supported.
    assert result.structure[0].coverage == "supported"


@pytest.mark.parametrize("status", ["unassessed", "unsupported", "conflicting", "general_valid"])
def test_supported_coverage_rejects_without_positive_safe_checks(status: str) -> None:
    # Given a falsely supported general-only section or a section with an unsafe check.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.review is not None
    assert ctx.result is not None
    sid = (
        c.SentenceId("sentence-two") if status == "general_valid" else c.SentenceId("sentence-one")
    )
    review = ctx.review.model_copy(
        update={
            "sentence_checks": tuple(
                check.model_copy(update={"status": status}) if check.sentence_id == sid else check
                for check in ctx.review.sentence_checks
            )
        }
    )
    result = ctx.result.model_copy(
        update={
            "structure": tuple(
                row.model_copy(update={"coverage": "supported"})
                if sid in row.actual_sentence_ids
                else row
                for row in ctx.result.structure
            )
        }
    )
    # When an unsupported coverage label is validated.
    with pytest.raises(c.ContractViolation, match="coverage_evidence"):
        validate_result(ctx.model_copy(update={"review": review, "result": result}))


def fallback_context() -> c.ContractContext:
    ctx = ContractCase.load("fallback.json").parse()
    template = ContractCase.load("complete.json").parse().review
    assert ctx.bundle is not None
    assert template is not None
    bundle, title = title_for_body(ctx.bundle, generic_title())
    review = template.model_copy(
        update={
            "version_id": bundle.version_id,
            "evidence_version": bundle.evidence_version,
            "personalization": "non_personalized",
            "title_review": title,
            "sentence_checks": tuple(
                c.SentenceCheck(
                    sentence_id=s.sentence_id,
                    fact_ids=(),
                    status="unassessed",
                    reason="Unreviewed fallback",
                )
                for p in bundle.paragraphs
                for s in p.sentences
            ),
            "requirement_checks": (),
            "issues": (),
            "repair_targets": (),
            "suggestions": (),
            "fixable_without_new_info": False,
            "length_check": measure_final(bundle, c.LengthPolicy()),
            "review_status": "partial",
        }
    )
    return c.ContractContext(evidence_version=ctx.evidence_version, bundle=bundle, review=review)


def test_new_review_stage_fallback_needs_no_rewritten_composition_history() -> None:
    # Given a current partial review of a wholly general unmapped fallback.
    ctx = fallback_context()
    # When the new stage5 delivery copy is validated.
    c.validate_contract(ctx)
    # Then prior stage3/4 reports remain absent and unmodified.
    assert ctx.writing_report is None
    assert ctx.integration_report is None


@pytest.mark.parametrize("change", ["performed", "stale", "personal", "mixed"])
def test_review_fallback_exception_is_narrow(change: str) -> None:
    # Given a forged fallback with one prerequisite broken.
    ctx = fallback_context()
    assert ctx.bundle is not None
    assert ctx.review is not None
    if change == "performed":
        ctx = ctx.model_copy(
            update={"review": ctx.review.model_copy(update={"review_status": "performed"})}
        )
    elif change == "stale":
        ctx = ctx.model_copy(
            update={"review": ctx.review.model_copy(update={"version_id": c.VersionId("old")})}
        )
    else:
        sentence = ctx.bundle.paragraphs[0].sentences[0]
        changed = (
            sentence.model_copy(update={"claim_kind": "personal_event"})
            if change == "personal"
            else sentence.model_copy(
                update={
                    "sentence_id": c.SentenceId("mixed"),
                    "section_ids": (c.SectionId("section-action"),),
                }
            )
        )
        sentences = (changed,) if change == "personal" else (sentence, changed)
        ctx = ctx.model_copy(
            update={
                "bundle": ctx.bundle.model_copy(
                    update={
                        "paragraphs": (
                            ctx.bundle.paragraphs[0].model_copy(update={"sentences": sentences}),
                        )
                    }
                )
            }
        )
    # When it tries to use the review-only fallback exception.
    with pytest.raises(c.ContractViolation):
        c.validate_contract(ctx)


def test_exact_explicit_fallback_provenance_allows_performed_review() -> None:
    # Given already-generated fallback text that is now positively reviewed as general prose.
    ctx = fallback_context()
    assert ctx.bundle is not None
    assert ctx.review is not None
    originals = tuple(s for p in ctx.bundle.paragraphs for s in p.sentences)
    review = ctx.review.model_copy(
        update={
            "review_status": "performed",
            "sentence_checks": tuple(
                check.model_copy(update={"status": "general_valid"})
                for check in ctx.review.sentence_checks
            ),
        }
    )
    # When internal exact provenance accompanies the current unchanged fallback.
    c.validate_contract(ctx.model_copy(update={"review": review, "fallback_provenance": originals}))
    # Then successful review does not erase provenance or attach personal section IDs.
    assert all(not s.section_ids for s in originals)


@pytest.mark.parametrize("change", ["text", "id", "personal"])
def test_internal_fallback_provenance_rejects_changed_content(change: str) -> None:
    # Given a claimed provenance sentence that does not exactly match a valid general origin.
    ctx = fallback_context()
    assert ctx.bundle is not None
    original = ctx.bundle.paragraphs[0].sentences[0]
    replacements = {
        "text": {"text": "Different content"},
        "id": {"sentence_id": c.SentenceId("foreign")},
        "personal": {"claim_kind": "personal_event"},
    }
    forged = original.model_copy(update=replacements[change])
    # When the internal provenance is checked at the shared boundary.
    with pytest.raises(c.ContractViolation, match="fallback_provenance"):
        c.validate_contract(ctx.model_copy(update={"fallback_provenance": (forged,)}))
