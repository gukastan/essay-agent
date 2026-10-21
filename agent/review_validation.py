"""Reject cross-version references inside the provider's single retry owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contract_base import require
from .contract_composition_validation import validate_sentences
from .contracts import ContractContext

if TYPE_CHECKING:
    from .stage_review_data import RepairPayload, RepairProposal, ReviewJudgments, ReviewPayload


def validate_review_output(output: ReviewJudgments, payload: ReviewPayload) -> None:
    """Validate supplied body judgments while allowing missing checks to remain unassessed."""
    sentences = {s.sentence_id: s for p in payload.candidate_bundle.paragraphs for s in p.sentences}
    requirements = {r.requirement_id for r in payload.analysis.requirements}
    facts = {f.fact_id for f in payload.facts}
    sections = {s.section_id for s in payload.outline.sections}
    gaps = {g.gap_id for g in payload.analysis.gaps}
    require(
        len({c.sentence_id for c in output.sentence_checks}) == len(output.sentence_checks),
        "review_duplicates",
        "One supplied sentence judgment",
    )
    for check in output.sentence_checks:
        require(check.sentence_id in sentences, "review_sentence", "Check current sentences only")
        require(
            set(check.fact_ids) <= set(sentences[check.sentence_id].fact_ids),
            "review_fact",
            "Check linked facts only",
        )
        require(
            check.status != "source_supported" or bool(check.fact_ids),
            "review_positive",
            "Support needs facts",
        )
        require(
            check.status != "general_valid"
            or sentences[check.sentence_id].claim_kind in ("general_statement", "connective"),
            "review_general",
            "Personal claims need personal evidence",
        )
    require(
        len({c.requirement_id for c in output.requirement_checks})
        == len(output.requirement_checks),
        "review_duplicates",
        "One supplied requirement judgment",
    )
    for check in output.requirement_checks:
        require(
            check.requirement_id in requirements
            and set(check.body_sentence_ids) <= set(sentences)
            and set(check.fact_ids) <= facts,
            "review_requirement",
            "Check current requirement references",
        )
    for issue in output.issues:
        require(
            set(issue.sentence_ids) <= set(sentences)
            and set(issue.section_ids) <= sections
            and set(issue.fact_ids) <= facts
            and set(issue.requirement_ids) <= requirements
            and set(issue.gap_ids) <= gaps,
            "review_issue",
            "Issue must describe current evidence and locations",
        )


def validate_repair_output(output: RepairProposal, payload: RepairPayload) -> None:
    """Keep targeted repairs inside current facts, selected sections and complete trace."""
    before = {s.sentence_id: s for p in payload.candidate_bundle.paragraphs for s in p.sentences}
    after = {s.sentence_id: s for p in output.paragraphs for s in p.sentences}
    require(
        len(after) == sum(len(p.sentences) for p in output.paragraphs),
        "repair_duplicates",
        "Unique repaired sentence identities",
    )
    ctx = ContractContext(
        evidence_version=payload.evidence_version,
        sources=payload.sources,
        facts=payload.facts,
        analysis=payload.analysis,
        outline=payload.outline,
    )
    inherited: set[str] = {
        s.sentence_id
        for s in payload.fallback_provenance
        if before.get(s.sentence_id) == s and after.get(s.sentence_id) == s
    }
    validate_sentences(tuple(after.values()), ctx, inherited)
    targets = payload.review.repair_targets
    whole = any(not t.sentence_ids and not t.section_ids and t.area != "subtitle" for t in targets)
    targeted = {sid for t in targets for sid in t.sentence_ids}
    sections = {sid for t in targets for sid in t.section_ids}
    for sid, sentence in before.items():
        if not whole and sid not in targeted and not sections.intersection(sentence.section_ids):
            require(
                after.get(sid) == sentence, "repair_scope", "Unselected prose remains unchanged"
            )
    for sid in set(before) & set(after):
        require(before[sid] == after[sid], "repair_identity", "Changed content gets a new ID")
    allowed = {fid for t in targets for fid in t.allowed_fact_ids}
    for sid in set(after) - set(before):
        require(
            set(after[sid].fact_ids) <= allowed,
            "repair_facts",
            "Repair stays within target evidence",
        )
    old_trace = tuple(sid for e in output.edits for sid in e.before_sentence_ids)
    new_trace = tuple(sid for e in output.edits for sid in e.after_sentence_ids)
    require(
        len(old_trace) == len(set(old_trace))
        and set(old_trace) == set(before)
        and len(new_trace) == len(set(new_trace))
        and set(new_trace) == set(after),
        "repair_trace",
        "Every old and new sentence has one mapping",
    )
