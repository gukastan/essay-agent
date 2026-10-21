"""Minimum structure recovery without inventing personal content."""

from .contracts import (
    AnswerCandidate,
    Budget,
    Outline,
    ParagraphAllocation,
    ParagraphId,
    ParagraphPlan,
    Requirement,
    RequirementMap,
    SectionId,
    SectionPlan,
    SelectionDecision,
    SubtitlePlan,
)
from .essay_rules import budget_outline
from .stage_evidence import eligible_links
from .stage_normalization import reservation_reason, title_reservation
from .stage_structure_models import StructurePayload


def usable_candidates(payload: StructurePayload) -> tuple[AnswerCandidate, ...]:
    """Discard held, excluded and conflicting links before fallback selection."""
    usable = {link.candidate_id for link in eligible_links(payload.analysis, payload.facts)}
    return tuple(
        sorted(
            (
                candidate
                for candidate in payload.analysis.answer_candidates
                if candidate.candidate_id in usable
            ),
            key=lambda item: item.source_order,
        )
    )


def selected_candidates(payload: StructurePayload) -> tuple[AnswerCandidate, ...]:
    """Keep source-order candidates that add an unrepresented usable requirement."""
    candidates = usable_candidates(payload)
    selected: list[AnswerCandidate] = []
    covered: set[str] = set()
    for candidate in candidates:
        direct = {
            link.requirement_id
            for link in eligible_links(payload.analysis, payload.facts)
            if link.candidate_id == candidate.candidate_id
        }
        if direct - covered or not selected:
            selected.append(candidate)
            covered.update(direct)
    return tuple(selected)


def requirement_section(
    requirement: Requirement, payload: StructurePayload, selected: tuple[AnswerCandidate, ...]
) -> SectionPlan:
    """Allocate only selected available evidence and retain missing requirement gaps."""
    selected_ids = {candidate.candidate_id for candidate in selected}
    linked = {
        fid
        for link in eligible_links(payload.analysis, payload.facts)
        if requirement.resolution != "unparsed"
        and link.requirement_id == requirement.requirement_id
        and link.candidate_id in selected_ids
        for fid in link.fact_ids
    }
    ordered = tuple(fact for fact in payload.facts if fact.fact_id in linked)
    gaps = tuple(
        gap for gap in payload.analysis.gaps if requirement.requirement_id in gap.requirement_ids
    )
    return SectionPlan(
        section_id=SectionId(f"S-{requirement.requirement_id}"),
        requirement_ids=(requirement.requirement_id,),
        role=requirement.description,
        purpose=requirement.reason,
        intended_content=requirement.description,
        allowed_content=" ".join(fact.quote for fact in ordered),
        fact_ids=tuple(fact.fact_id for fact in ordered),
        experience_ids=tuple(
            dict.fromkeys(fact.experience_id for fact in ordered if fact.experience_id is not None)
        ),
        gap_ids=tuple(gap.gap_id for gap in gaps),
        missing_info=tuple(gap.missing_detail for gap in gaps),
        write_mode="grounded" if ordered else "omit",
    )


def structure_fallback(payload: StructurePayload) -> Outline:
    """Keep all requirements, source-order evidence and one writable physical paragraph."""
    selected = selected_candidates(payload)
    selected_ids = tuple(candidate.candidate_id for candidate in selected)
    sections = tuple(
        requirement_section(requirement, payload, selected)
        for requirement in payload.analysis.requirements
    )
    writable = tuple(section for section in sections if section.write_mode != "omit")
    if not writable:
        general = SectionPlan(
            section_id=SectionId("S-general"),
            requirement_ids=(),
            role="일반 설명",
            purpose="개인 경험을 주장하지 않는 설명",
            intended_content="문항의 일반적인 설명 방향",
            allowed_content="제공되지 않은 경험이나 생각을 개인 사실로 쓰지 않는 일반 설명",
            fact_ids=(),
            experience_ids=(),
            gap_ids=(),
            missing_info=(),
            write_mode="general",
        )
        sections += (general,)
        writable = (general,)
    maps = tuple(
        RequirementMap(
            requirement_id=section.requirement_ids[0],
            section_ids=(section.section_id,),
            planned_coverage="planned_supported" if section.fact_ids else "unfilled",
            gap_ids=section.gap_ids,
            reason="현재 유효한 근거 범위만 배치하고 미제공 요구는 남깁니다.",
        )
        for section in sections
        if section.requirement_ids
    )
    selected_facts = {fid for section in writable for fid in section.fact_ids}
    personal = tuple(
        fact
        for fact in payload.facts
        if fact.fact_id in selected_facts and fact.source_kind == "applicant"
    )
    limit = payload.request.length_policy.max_chars
    outline = Outline(
        evidence_version=payload.evidence_version,
        selected_candidate_ids=selected_ids,
        selected_experience_ids=tuple(
            dict.fromkeys(eid for c in selected for eid in c.experience_ids)
        ),
        selection_decisions=tuple(
            SelectionDecision(
                candidate_id=c.candidate_id,
                decision="selected" if c.candidate_id in selected_ids else "not_selected",
                requirement_ids=c.requirement_ids,
                reason="유효한 요구 연결과 원문 순서로 선택하며 다른 사건은 구분합니다.",
                limits=("결정적 최소 구조이며 의미 적합성은 후속 검토 대상입니다.",),
            )
            for c in payload.analysis.answer_candidates
        ),
        core_answer=" ".join(fact.quote for fact in personal) if personal else None,
        core_answer_fact_ids=tuple(fact.fact_id for fact in personal),
        general_direction=None
        if personal
        else "문항의 주제를 개인 이력으로 주장하지 않고 설명합니다.",
        composition="근거에 따른 요구별 설명",
        composition_reason="원문 요구와 사건을 보존한 최소 배치",
        requirement_map=maps,
        sections=sections,
        paragraphs=(
            ParagraphPlan(
                paragraph_id=ParagraphId("P1"),
                order=0,
                purpose="현재 작성 가능한 내용",
                allocations=tuple(
                    ParagraphAllocation(
                        section_id=s.section_id,
                        content_focus=s.allowed_content,
                        fact_ids=s.fact_ids,
                    )
                    for s in writable
                ),
                previous_relation=None,
                weight=100,
                target_chars=None,
                budget_reason="최소 구조의 단일 문단",
            ),
        ),
        subtitle_plan=SubtitlePlan(
            purpose="확인된 본문 주제를 요약",
            fact_ids=tuple(f.fact_id for f in personal),
            held_claims=payload.analysis.held_claims,
        ),
        budget=Budget(
            max_chars=limit,
            subtitle_reserved_chars=None
            if limit is None
            else title_reservation(writable[0].role, payload.request.length_policy),
            separator_chars=0,
            usable_body_chars=None,
            constraint_notes=(),
        ),
        design_status="general"
        if not personal
        else "partial"
        if any(not s.fact_ids for s in sections)
        else "ready",
        planning_notes=(
            "최소 구조: 필요한 설명을 보존하고 없는 개인 정보는 생략합니다.",
            reservation_reason(writable[0].role),
        ),
        held_claims=payload.analysis.held_claims,
    )
    return budget_outline(outline, payload.request.length_policy)
