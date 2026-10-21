from agent.contracts import CandidateId, EvidenceLink, FactId, RequirementId, RevisionContext
from agent.stage_analysis_models import AnalysisOutput, AnalysisPayload
from agent.stage_structure_models import StructureOutput, StructurePayload
from tests.analysis_support import request_for, run
from tests.fixtures.cases import ContractCase


def analysis_pair() -> tuple[AnalysisPayload, AnalysisOutput]:
    context = ContractCase.load("complete.json").parse()
    assert context.request is not None
    assert context.analysis is not None
    analysis = context.analysis.model_copy(
        update={
            "evidence_links": (
                *context.analysis.evidence_links,
                EvidenceLink(
                    requirement_id=RequirementId("req-action"),
                    candidate_id=CandidateId("answer-garden"),
                    fact_ids=(FactId("fact-garden"),),
                    information_role="direct",
                    information_state="available",
                    applicability="applies",
                    use_status="candidate",
                    reason="The supplied garden quote explicitly states the watering action.",
                ),
            )
        }
    )
    return AnalysisPayload(
        request=context.request,
        evidence_version=context.evidence_version,
        sources=context.sources,
        revision_context=RevisionContext(source_history=(), question_registry=()),
        research_status="not_requested",
    ), AnalysisOutput(facts=context.facts, analysis=analysis)


def structure_pair() -> tuple[StructurePayload, StructureOutput]:
    context = run(request_for())
    payload = StructurePayload(
        request=context.request,
        evidence_version=context.evidence_version,
        sources=context.sources,
        facts=context.facts,
        analysis=context.analysis,
        guide="test",
        procedure="test",
    )
    return payload, StructureOutput(outline=context.outline)
