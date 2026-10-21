"""Recalculate structural edit/paragraph records after deterministic restoration."""

from .contract_composition_validation import bundle_sentences
from .contracts import (
    Analysis,
    DraftBundle,
    IntegrationEdit,
    IntegrationRequirementCheck,
    Outline,
    ReverseOutline,
)


def restoration_edits(before: DraftBundle, after: DraftBundle) -> tuple[IntegrationEdit, ...]:
    """Trace every original and current sentence exactly once after safety cleanup."""
    old = {s.sentence_id: s for s in bundle_sentences(before)}
    current = {s.sentence_id: s for s in bundle_sentences(after)}
    edits: list[IntegrationEdit] = []
    for sid, sentence in old.items():
        edits.append(
            IntegrationEdit(
                operation="retain" if sid in current else "delete",
                before_sentence_ids=(sid,),
                after_sentence_ids=(sid,) if sid in current else (),
                section_ids=sentence.section_ids,
                fact_ids=sentence.fact_ids,
                reason="보존된 기준 문장과 안전 처리 후 문장을 대응했습니다.",
            )
        )
    edits.extend(
        IntegrationEdit(
            operation="add_fallback",
            before_sentence_ids=(),
            after_sentence_ids=(sid,),
            section_ids=(),
            fact_ids=(),
            reason="남은 유효 문장이 없어 비개인화된 완결 설명을 제공했습니다.",
        )
        for sid in current
        if sid not in old
    )
    return tuple(edits)


def structural_reverse(bundle: DraftBundle, scope: str) -> tuple[ReverseOutline, ...]:
    """Leave semantic summaries unassessed when Python only knows current references."""
    return tuple(
        ReverseOutline.model_validate(
            {
                "scope": scope,
                "paragraph_id": paragraph.paragraph_id,
                "sentence_ids": tuple(s.sentence_id for s in paragraph.sentences),
                "section_ids": tuple(
                    dict.fromkeys(sid for s in paragraph.sentences for sid in s.section_ids)
                ),
                "fact_ids": tuple(
                    dict.fromkeys(fid for s in paragraph.sentences for fid in s.fact_ids)
                ),
                "gist": None,
                "roles": (),
                "requirement_ids": (),
                "semantic_status": "unassessed",
                "difference_from_plan": None,
            }
        )
        for paragraph in bundle.paragraphs
    )


def unassessed_requirements(
    before: DraftBundle,
    after: DraftBundle,
    analysis: Analysis,
    outline: Outline,
) -> tuple[IntegrationRequirementCheck, ...]:
    """Recompute current locations without treating section mapping as semantic coverage."""
    rows: list[IntegrationRequirementCheck] = []
    for requirement in analysis.requirements:
        sections = {
            s.section_id
            for s in outline.sections
            if requirement.requirement_id in s.requirement_ids
        }
        rows.append(
            IntegrationRequirementCheck(
                requirement_id=requirement.requirement_id,
                baseline_sentence_ids=tuple(
                    s.sentence_id
                    for s in bundle_sentences(before)
                    if sections.intersection(s.section_ids)
                ),
                candidate_sentence_ids=tuple(
                    s.sentence_id
                    for s in bundle_sentences(after)
                    if sections.intersection(s.section_ids)
                ),
                before_state="unassessed",
                after_state="unassessed",
                gap_ids=tuple(
                    g.gap_id
                    for g in analysis.gaps
                    if requirement.requirement_id in g.requirement_ids
                ),
                missing_detail=None,
                reason="복원 후 의미 충족은 현재 본문을 다시 검토해야 합니다.",
            )
        )
    return tuple(rows)
