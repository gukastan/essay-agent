"""Literal-source analysis for explicit test mode, not a semantic quality oracle."""

import re

from .contracts import (
    Analysis,
    AnswerCandidate,
    CandidateId,
    EvidenceLink,
    ExperienceCandidate,
    ExperienceId,
    Fact,
    FactId,
    HeldClaim,
    RequirementId,
    SourceSpan,
)
from .fake_requirements import explanation_requirements, has_words, matching_facts
from .stage_analysis_models import AnalysisOutput, AnalysisPayload
from .stage_analysis_rules import missing_gap


def literal_facts(payload: AnalysisPayload) -> tuple[Fact, ...]:
    """Slice original codepoints and keep each supplied event separate."""
    facts: list[Fact] = []
    view_ids = {f"user:{source.source_id}" for source in payload.request.user_views}
    for source in payload.sources:
        event = (
            ExperienceId(f"E{source.source_order + 1}")
            if source.source_kind == "applicant" and source.source_id not in view_ids
            else None
        )
        for piece in re.finditer(r"[^.!?\n]+[.!?]?", source.text):
            quote = piece.group().strip()
            if not quote:
                continue
            start = piece.start() + len(piece.group()) - len(piece.group().lstrip())
            facts.append(
                Fact(
                    fact_id=FactId(f"F{len(facts) + 1}"),
                    source_id=source.source_id,
                    source_kind=source.source_kind,
                    quote=quote,
                    span=SourceSpan(start=start, end=start + len(quote)),
                    experience_id=event,
                    claim_kind="external_context"
                    if source.source_kind != "applicant"
                    else "stated_view"
                    if source.source_id in view_ids
                    else "personal_event",
                    attribution="팀"
                    if has_words(quote, ("팀원들", "팀 전체", "우리 팀"))
                    else "사용자 진술",
                    information_state="available",
                    conflict_ids=(),
                )
            )
    return tuple(facts)


def analyze_literals(payload: AnalysisPayload) -> AnalysisOutput:
    """Extract exact quotes; absent learning, motives and results remain gaps."""
    requirements = explanation_requirements(payload.request.question)
    facts = literal_facts(payload)
    events = tuple(dict.fromkeys(fact.experience_id for fact in facts if fact.experience_id))
    experiences = tuple(
        ExperienceCandidate(
            experience_id=event,
            fact_ids=tuple(f.fact_id for f in facts if f.experience_id == event),
            source_order=i,
        )
        for i, event in enumerate(events)
    )
    sources = tuple(dict.fromkeys(f.source_id for f in facts if f.source_kind == "applicant"))
    candidates: list[AnswerCandidate] = []
    links: list[EvidenceLink] = []
    for order, source_id in enumerate(sources):
        current = tuple(f for f in facts if f.source_id == source_id)
        candidate_id = CandidateId(f"C{order + 1}")
        candidate_requirements: list[RequirementId] = []
        for requirement in requirements:
            matched = matching_facts(requirement, current)
            if requirement.requirement_id == "R-second-experience" and order == 0:
                matched = ()
            if matched:
                candidate_requirements.append(requirement.requirement_id)
            links.append(
                EvidenceLink(
                    requirement_id=requirement.requirement_id,
                    candidate_id=candidate_id,
                    fact_ids=matched,
                    information_role=requirement.information_role,
                    information_state="available" if matched else "unverified",
                    applicability="applies",
                    use_status="candidate" if matched else "held",
                    reason="현재 원문에 명시된 내용만 연결합니다.",
                )
            )
        candidates.append(
            AnswerCandidate(
                candidate_id=candidate_id,
                experience_ids=tuple(
                    dict.fromkeys(f.experience_id for f in current if f.experience_id)
                ),
                fact_ids=tuple(f.fact_id for f in current),
                requirement_ids=tuple(candidate_requirements),
                source_order=order,
            )
        )
    gaps = tuple(
        missing_gap(requirement)
        for requirement in requirements
        if not any(
            link.requirement_id == requirement.requirement_id and link.fact_ids for link in links
        )
    )
    held = tuple(
        HeldClaim(
            description=gap.missing_detail,
            reason="제공되지 않은 개인 사실은 쓰지 않습니다.",
            fact_ids=(),
            requirement_ids=gap.requirement_ids,
        )
        for gap in gaps
    )
    text = payload.request.question or ""
    question_type = (
        "motivation"
        if has_words(text, ("동기", "motivation"))
        else "aspiration"
        if has_words(text, ("의견", "포부", "계획"))
        else "experience"
        if events
        else "general"
    )
    return AnalysisOutput(
        facts=facts,
        analysis=Analysis(
            analysis_status="complete",
            question_type=question_type,
            requirements=requirements,
            writing_conditions=(),
            company_role_context=(),
            experience_candidates=experiences,
            answer_candidates=tuple(candidates),
            evidence_links=tuple(links),
            competency_candidates=(),
            role_links=(),
            gaps=gaps,
            held_claims=held,
            research_status=payload.research_status,
        ),
    )
