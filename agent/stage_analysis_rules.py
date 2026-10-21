"""Conservative analysis recovery and stable optional-question handling."""

from .contracts import Analysis, Gap, GapId, QuestionKey, Requirement, RequirementId
from .stage_analysis_models import AnalysisOutput, AnalysisPayload
from .stage_evidence import eligible_links
from .stage_questions import normalize_gap


def unparsed_requirement(question: str) -> Requirement:
    """Preserve exact question codepoints when decomposition is incomplete."""
    return Requirement(
        requirement_id=RequirementId("R-unparsed-question"),
        description=question,
        resolution="unparsed",
        origin="explicit",
        information_role="direct",
        required_by_prompt=True,
        application_condition=None,
        reason="문항 분해를 마치지 못해 원문 요구를 그대로 보존합니다.",
    )


def missing_gap(requirement: Requirement) -> Gap:
    """Represent absent information without inventing a fact."""
    return Gap(
        gap_id=GapId(f"G-{requirement.requirement_id}"),
        question_key=QuestionKey(f"pending:{requirement.requirement_id}"),
        requirement_ids=(requirement.requirement_id,),
        candidate_id=None,
        missing_detail=requirement.description,
        why_it_matters=requirement.reason,
        priority=1,
        question=None,
        question_status="proposed",
    )


def normalize_analysis(output: AnalysisOutput, payload: AnalysisPayload) -> AnalysisOutput:
    """Preserve raw questions on decomposition failure and server question identities."""
    analysis = output.analysis
    requirements = analysis.requirements
    gaps = analysis.gaps
    if payload.request.question and analysis.analysis_status != "complete":
        raw = unparsed_requirement(payload.request.question)
        requirements = (
            *tuple(r for r in requirements if r.requirement_id != raw.requirement_id),
            raw,
        )
        if not any(raw.requirement_id in gap.requirement_ids for gap in gaps):
            gaps += (missing_gap(raw),)
    for requirement in requirements:
        supported = requirement.resolution != "unparsed" and any(
            link.requirement_id == requirement.requirement_id
            for link in eligible_links(analysis, output.facts)
        )
        if not supported and not any(requirement.requirement_id in g.requirement_ids for g in gaps):
            gaps += (missing_gap(requirement),)
    normalized = tuple(normalize_gap(gap, output, payload) for gap in gaps)
    return output.model_copy(
        update={
            "analysis": analysis.model_copy(
                update={
                    "requirements": requirements,
                    "gaps": tuple(normalized),
                    "research_status": payload.research_status,
                }
            )
        }
    )


def analysis_fallback(payload: AnalysisPayload) -> AnalysisOutput:
    """Recover without manufacturing facts or pretending a question was decomposed."""
    requirement = (
        unparsed_requirement(payload.request.question)
        if payload.request.question
        else Requirement(
            requirement_id=RequirementId("R-general"),
            description="일반 자기소개 방향",
            resolution="interpreted",
            origin="interpreted",
            information_role="direct",
            required_by_prompt=False,
            application_condition=None,
            reason="문항이 제공되지 않았습니다.",
        )
    )
    return normalize_analysis(
        AnalysisOutput(
            facts=(),
            analysis=Analysis(
                analysis_status="unavailable",
                question_type="general",
                requirements=(requirement,),
                writing_conditions=(),
                company_role_context=(),
                experience_candidates=(),
                answer_candidates=(),
                evidence_links=(),
                competency_candidates=(),
                role_links=(),
                gaps=(missing_gap(requirement),),
                held_claims=(),
                research_status=payload.research_status,
            ),
        ),
        payload,
    )
