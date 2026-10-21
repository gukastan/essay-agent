"""Conservative offline repair returns an explicit identity proposal."""

from .contracts import IntegrationEdit
from .stage_review_models import RepairOutput, RepairPayload


def repair_literals(payload: RepairPayload) -> RepairOutput:
    """Make no imagined improvement when only a semantic model could rewrite safely."""
    bundle = payload.candidate_bundle
    return RepairOutput(
        paragraphs=bundle.paragraphs,
        subtitle=bundle.subtitle,
        subtitle_fact_ids=bundle.subtitle_fact_ids,
        edits=tuple(
            IntegrationEdit(
                operation="retain",
                before_sentence_ids=(s.sentence_id,),
                after_sentence_ids=(s.sentence_id,),
                section_ids=s.section_ids,
                fact_ids=s.fact_ids,
                reason="현재 근거 있는 문장을 유지했습니다.",
            )
            for p in bundle.paragraphs
            for s in p.sentences
        ),
    )
