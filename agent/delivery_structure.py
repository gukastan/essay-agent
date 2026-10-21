"""Explain actual selected prose using exact locations and current sentence checks."""

from .contracts import (
    DraftBundle,
    Location,
    Outline,
    RequirementStatus,
    Review,
    SentenceId,
    StructureEntry,
)


def locations_for(
    bundle: DraftBundle, sentence_ids: tuple[SentenceId, ...]
) -> tuple[Location, ...]:
    """Derive one-based paragraph positions and exact excerpts from the selected bundle."""
    selected = set(sentence_ids)
    return tuple(
        Location(
            paragraph_id=p.paragraph_id,
            paragraph_number=index,
            sentence_ids=tuple(s.sentence_id for s in p.sentences if s.sentence_id in selected),
            excerpts=tuple(s.text for s in p.sentences if s.sentence_id in selected),
        )
        for index, p in enumerate(bundle.paragraphs, 1)
        if any(s.sentence_id in selected for s in p.sentences)
    )


def structure_for(
    bundle: DraftBundle, review: Review, outline: Outline
) -> tuple[StructureEntry, ...]:
    """Keep unwritten planned parts without attaching generic fallback to personal sections."""
    checks = {c.sentence_id: c for c in review.sentence_checks}
    requirements = {c.requirement_id: c for c in review.requirement_checks}
    rows: list[StructureEntry] = []
    for section in outline.sections:
        ids = tuple(
            s.sentence_id
            for p in bundle.paragraphs
            for s in p.sentences
            if section.section_id in s.section_ids
        )
        statuses = tuple(checks[sid].status if sid in checks else "unassessed" for sid in ids)
        coverage = (
            "not_expressed"
            if not ids
            else "supported"
            if all(s in ("source_supported", "general_valid") for s in statuses)
            and "source_supported" in statuses
            else "general"
            if all(s == "general_valid" for s in statuses)
            else "unassessed"
        )
        rows.append(
            StructureEntry.model_validate(
                {
                    "section_id": section.section_id,
                    "purpose": section.purpose,
                    "intended_content": section.intended_content,
                    "actual_sentence_ids": ids,
                    "locations": locations_for(bundle, ids),
                    "requirement_ids": section.requirement_ids,
                    "requirement_statuses": tuple(
                        RequirementStatus(requirement_id=rid, status=requirements[rid].status)
                        for rid in section.requirement_ids
                        if rid in requirements
                    ),
                    "coverage": coverage,
                    "missing_info": tuple(
                        requirements[rid].missing_detail
                        for rid in section.requirement_ids
                        if rid in requirements
                        and requirements[rid].missing_detail is not None
                        and requirements[rid].status != "met"
                    ),
                }
            )
        )
    positions = {
        s.sentence_id: (pindex, sindex)
        for pindex, p in enumerate(bundle.paragraphs)
        for sindex, s in enumerate(p.sentences)
    }
    rows.sort(
        key=lambda row: min(
            (positions[sid] for sid in row.actual_sentence_ids), default=(len(bundle.paragraphs), 0)
        )
    )
    return tuple(rows)
