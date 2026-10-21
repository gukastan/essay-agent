from agent import contracts as c
from agent.stage_review_models import RepairOutput, RepairPayload, ReviewOutput, ReviewPayload
from tests.review_adversarial_contracts import Scenario, issue, title


def review_output(payload: ReviewPayload, scenario: Scenario) -> ReviewOutput:
    sentences = tuple(s for p in payload.candidate_bundle.paragraphs for s in p.sentences)
    checks = tuple(
        c.SentenceCheck(
            sentence_id=s.sentence_id,
            fact_ids=s.fact_ids,
            status="unassessed"
            if scenario == "no_positive"
            else "unsupported"
            if scenario == "all_unsafe"
            or s.sentence_id == "fabricated-sentence"
            or (scenario == "unsafe_swap" and s.sentence_id == "sentence-one")
            else "source_supported"
            if s.fact_ids
            else "general_valid",
            reason="Injected semantic report.",
        )
        for s in sentences
    )
    requirements: list[c.RequirementCheck] = []
    for requirement in payload.analysis.requirements:
        sections = {
            s.section_id
            for s in payload.outline.sections
            if requirement.requirement_id in s.requirement_ids
        }
        linked = tuple(s for s in sentences if sections.intersection(s.section_ids))
        requirements.append(
            c.RequirementCheck(
                requirement_id=requirement.requirement_id,
                body_sentence_ids=tuple(s.sentence_id for s in linked),
                fact_ids=tuple(dict.fromkeys(fid for s in linked for fid in s.fact_ids)),
                status="not_applicable"
                if not requirement.required_by_prompt
                else "met"
                if linked or scenario == "title_only"
                else "unmet",
                missing_detail=None if linked else "The required answer is absent from the body.",
                reason="Injected body-only assessment.",
            )
        )
    issues: tuple[c.ReviewIssue, ...] = ()
    if scenario in ("lost_learning", "fabricated", "repair_error") and payload.repair_count == 0:
        target = next(
            s
            for s in sentences
            if s.sentence_id
            == ("sentence-learning" if scenario == "lost_learning" else "sentence-one")
        )
        issues = (
            issue("repair-request", "length" if scenario == "lost_learning" else "style", target),
        )
    if scenario == "fabricated" and payload.repair_count:
        issues = tuple(
            issue("fabricated", "unsupported_claim", s)
            for s in sentences
            if s.sentence_id == "fabricated-sentence"
        )
    if scenario == "unsafe_swap":
        issues = tuple(
            issue("reported-" + s.sentence_id, "unsupported_claim", s)
            for s in sentences
            if s.sentence_id in ("sentence-one", "fabricated-sentence")
        )
    if scenario == "title_budget":
        issues = tuple(
            issue("title-" + str(i), "subtitle") for i in range(2 - payload.repair_count)
        )
    if scenario in ("missing", "unavailable", "resolved"):
        issues = (issue("missing-answer", "missing_information", fixable=False),)
    if scenario == "omitted" and not any(s.sentence_id == "sentence-learning" for s in sentences):
        issues = (issue("supplied-answer-omitted", "prompt_coverage"),)
    if scenario == "all_unsafe":
        issues = tuple(
            issue("unsafe-" + str(i), "unsupported_claim", s) for i, s in enumerate(sentences)
        )
    return ReviewOutput(
        title_review=title(payload, scenario),
        sentence_checks=checks,
        requirement_checks=tuple(requirements),
        issues=issues,
        quality=c.Quality(
            specificity="adequate",
            prompt_coverage="limited" if issues else "adequate",
            coherence="adequate",
        ),
        suggestions=(),
    )


def repair_output(payload: RepairPayload, scenario: Scenario) -> RepairOutput:
    baseline = payload.candidate_bundle
    paragraphs = baseline.paragraphs
    before = tuple(s for p in paragraphs for s in p.sentences)
    edits = tuple(
        c.IntegrationEdit(
            operation="retain",
            before_sentence_ids=(s.sentence_id,),
            after_sentence_ids=(s.sentence_id,),
            section_ids=s.section_ids,
            fact_ids=s.fact_ids,
            reason="Unchanged supplied prose.",
        )
        for s in before
    )
    subtitle = baseline.subtitle
    if scenario == "lost_learning":
        paragraphs = tuple(
            p.model_copy(
                update={
                    "sentences": tuple(
                        s for s in p.sentences if s.sentence_id != "sentence-learning"
                    )
                }
            )
            for p in paragraphs
        )
        edits = tuple(
            e.model_copy(update={"operation": "delete", "after_sentence_ids": ()})
            if e.before_sentence_ids == ("sentence-learning",)
            else e
            for e in edits
        )
        subtitle = None
    if scenario in ("fabricated", "unsafe_swap"):
        changed = before[0].model_copy(
            update={
                "sentence_id": c.SentenceId("fabricated-sentence"),
                "text": "I led."
                if scenario == "unsafe_swap"
                else "I led every library in the country.",
            }
        )
        paragraphs = tuple(
            p.model_copy(
                update={
                    "sentences": tuple(
                        changed if s.sentence_id == before[0].sentence_id else s
                        for s in p.sentences
                    )
                }
            )
            for p in paragraphs
        )
        edits = tuple(
            e.model_copy(
                update={"operation": "rewrite", "after_sentence_ids": (changed.sentence_id,)}
            )
            if e.before_sentence_ids == (before[0].sentence_id,)
            else e
            for e in edits
        )
        subtitle = None
    if scenario == "title_budget":
        subtitle = "Revised work notes " + str(payload.repair_count)
    if scenario == "omitted":
        learning = c.Sentence(
            sentence_id=c.SentenceId("sentence-learning"),
            text="I learned to agree on a method before starting.",
            section_ids=(c.SectionId("section-result"),),
            fact_ids=(c.FactId("fact-learning"),),
            claim_kind="stated_view",
        )
        paragraphs = (
            *paragraphs[:-1],
            paragraphs[-1].model_copy(update={"sentences": (*paragraphs[-1].sentences, learning)}),
        )
        edits = (
            *edits,
            c.IntegrationEdit(
                operation="add_grounded",
                before_sentence_ids=(),
                after_sentence_ids=(learning.sentence_id,),
                section_ids=learning.section_ids,
                fact_ids=learning.fact_ids,
                reason="Express the explicitly supplied learning fact.",
            ),
        )
        subtitle = None
    return RepairOutput(paragraphs=paragraphs, subtitle=subtitle, subtitle_fact_ids=(), edits=edits)
