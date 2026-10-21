"""Limited literal vocabulary for deterministic offline response fixtures."""

from typing import Final

from .contracts import Fact, FactId, Requirement, RequirementId

PARTS: Final = (
    ("role", "본인 역할", ("역할", "role"), ("담당", "맡", "role", "responsib")),
    (
        "action",
        "본인 행동",
        ("행동", "과정", "action"),
        ("작성", "만들", "반영", "수거", "설치", "소통", "실행", "전달", "created"),
    ),
    (
        "result",
        "확인된 결과",
        ("결과", "성과", "result"),
        ("기한", "완료", "결과", "실패", "변화 없", "제출", "전달", "result"),
    ),
    ("learning", "실제 배운 점", ("배운", "배움", "learn"), ("배웠", "깨달", "learned")),
    (
        "motive",
        "실제 선택 이유",
        ("동기", "선택 이유", "motivation"),
        ("때문", "이유", "관심", "좋아", "because"),
    ),
    ("metric", "수치 근거", ("수치", "정량", "metric"), ("%", "개", "곳", "명", "시간", "개월")),
    (
        "view",
        "실제 의견과 계획",
        ("의견", "포부", "계획", "opinion"),
        ("생각", "계획", "목표", "원합", "believe"),
    ),
)


def has_words(text: str, words: tuple[str, ...]) -> bool:
    """Match literal test-mode vocabulary without changing source text."""
    return any(word in text.casefold() for word in words)


def question_requirements(question: str | None) -> tuple[Requirement, ...]:
    """Recognize explicit test-mode roles while preserving the full question."""
    text = question or ""
    requirements = [
        Requirement(
            requirement_id=RequirementId(f"R-{key}"),
            description=description,
            resolution="interpreted",
            origin="explicit",
            information_role="direct",
            required_by_prompt=True,
            application_condition=None,
            reason=f"문항 원문: {text}",
        )
        for key, description, words, _ in PARTS
        if has_words(text, words)
    ]
    if has_words(text, ("경험", "사례", "experience")) or not requirements:
        requirements.insert(
            0,
            Requirement(
                requirement_id=RequirementId("R-experience" if text else "R-general"),
                description=text or "일반 자기소개 방향",
                resolution="interpreted",
                origin="explicit" if text else "interpreted",
                information_role="direct",
                required_by_prompt=bool(text),
                application_condition=None,
                reason="문항의 중심 요구" if text else "문항 미제공에 따른 일반 해석",
            ),
        )
    if has_words(text, ("두 사례", "두 가지 경험", "두 경험", "two experiences")):
        requirements.append(
            Requirement(
                requirement_id=RequirementId("R-second-experience"),
                description="두 번째 별개 경험",
                resolution="interpreted",
                origin="explicit",
                information_role="direct",
                required_by_prompt=True,
                application_condition=None,
                reason=f"문항 원문: {text}",
            )
        )
    return tuple(requirements)


def explanation_requirements(question: str | None) -> tuple[Requirement, ...]:
    """Keep implicit action and result needs for the explicit problem-solving fixture vocabulary."""
    requirements = question_requirements(question)
    if not has_words(question or "", ("해결", "개선", "resolve", "improve")):
        return requirements
    existing = {item.requirement_id for item in requirements}
    inferred = tuple(
        Requirement(
            requirement_id=RequirementId(f"R-{key}"),
            description=description,
            resolution="interpreted",
            origin="interpreted",
            information_role="logical_core",
            required_by_prompt=False,
            application_condition="문제 해결 또는 개선을 설명할 때",
            reason="해결 주장을 이해하려면 실제 행동과 확인된 결과의 범위가 필요합니다.",
        )
        for key, description in (("action", "본인 행동"), ("result", "확인된 결과"))
        if f"R-{key}" not in existing
    )
    return requirements + inferred


def matching_facts(requirement: Requirement, facts: tuple[Fact, ...]) -> tuple[FactId, ...]:
    """Use only applicant quotes matching the requested test-mode role."""
    filters = {f"R-{key}": words for key, _, _, words in PARTS}
    words = filters.get(requirement.requirement_id)
    return tuple(
        fact.fact_id
        for fact in facts
        if fact.source_kind == "applicant"
        and (requirement.requirement_id not in ("R-role", "R-action") or fact.attribution != "팀")
        and (words is None or has_words(fact.quote, words))
    )
