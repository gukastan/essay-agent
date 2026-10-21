"""Sanitized technical issue records shared by graph stages."""

from .contracts import TechnicalIssue
from .essay_llm import GenerationError


def generation_issue(node: str, error: GenerationError) -> TechnicalIssue:
    """Expose only sanitized provider category and actual attempt accounting."""
    return TechnicalIssue(
        node=node,
        code=error.kind.value,
        attempts=len(error.usage.attempts),
        exhausted=error.retryable,
        recovered=True,
        message="모델 단계 오류 후 보존된 입력으로 대체 경로를 사용했습니다.",
    )
