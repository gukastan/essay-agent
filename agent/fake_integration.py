"""Deterministic exact repetition cleanup without semantic similarity guesses."""

from .composition_rules import new_version
from .contracts import DraftBundle, DraftParagraph, IntegrationEdit, Sentence, SentenceId


def merge_exact_repetitions(
    baseline: DraftBundle,
) -> tuple[tuple[DraftParagraph, ...], tuple[IntegrationEdit, ...]]:
    """Merge only identical text and evidence within each actual paragraph."""
    paragraphs: list[DraftParagraph] = []
    edits: list[IntegrationEdit] = []
    for paragraph in baseline.paragraphs:
        groups: dict[tuple[str, str, tuple[str, ...]], list[Sentence]] = {}
        for sentence in paragraph.sentences:
            key = (sentence.text, sentence.claim_kind, sentence.fact_ids)
            groups.setdefault(key, []).append(sentence)
        sentences: list[Sentence] = []
        for originals in groups.values():
            first = originals[0]
            merged = len(originals) > 1
            current = (
                first.model_copy(
                    update={
                        "sentence_id": SentenceId(f"merged:{new_version()}"),
                        "section_ids": tuple(
                            dict.fromkeys(sid for s in originals for sid in s.section_ids)
                        ),
                    }
                )
                if merged
                else first
            )
            sentences.append(current)
            edits.append(
                IntegrationEdit(
                    operation="merge" if merged else "retain",
                    before_sentence_ids=tuple(s.sentence_id for s in originals),
                    after_sentence_ids=(current.sentence_id,),
                    section_ids=current.section_ids,
                    fact_ids=current.fact_ids,
                    reason="동일 문장과 동일 근거의 반복만 합쳤습니다.",
                )
            )
        paragraphs.append(paragraph.model_copy(update={"sentences": tuple(sentences)}))
    return tuple(paragraphs), tuple(edits)
