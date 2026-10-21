from uuid import UUID

import pytest
from pydantic import BaseModel, JsonValue, ValidationError

from agent.contracts import (
    Analysis,
    ContractContext,
    ContractViolation,
    DraftBundle,
    EssayRequest,
    EssayResult,
    IntegrationReport,
    LengthPolicy,
    Outline,
    Review,
    RunErrorPayload,
    SectionDraft,
    SourceSnapshot,
    StoredParent,
    WritingReport,
    count_characters,
    render_body,
    render_copy_text,
    validate_contract,
    validate_request_parent,
)
from tests.fixtures.cases import (
    ACCEPTED_EDGE_FIXTURES,
    PAYLOAD,
    ContractCase,
    Rejection,
    rejection_cases,
)
from tests.fixtures.schema_checks import assert_strict_schema


def test_empty_context_is_valid() -> None:
    # Given no supplied company, question, or experience.
    payload = {}
    # When the public request boundary parses it.
    request = EssayRequest.model_validate(payload)
    # Then missing information remains valid input with server-owned identifiers.
    assert request.experiences == ()
    assert request.question is None
    identifiers = (request.request_id, request.thread_id, request.document_id)
    assert all(isinstance(value, UUID) for value in identifiers)


@pytest.mark.parametrize("max_chars", [0, -1, True, "500", 1.5])
def test_invalid_length_policy(max_chars: float | str) -> None:
    # Given an invalid limit, including coercible values.
    payload = {"max_chars": max_chars}
    # When the request length policy is parsed, then it is rejected.
    with pytest.raises((ValidationError, ContractViolation)):
        _ = LengthPolicy.model_validate(payload)


@pytest.mark.parametrize(
    ("spaces", "newlines", "expected"),
    [
        (True, True, 5),
        (False, False, 3),
        (True, False, 4),
        (False, True, 4),
    ],
)
def test_length_policy(*, spaces: bool, newlines: bool, expected: int) -> None:
    # Given Korean text with independent whitespace categories.
    policy = LengthPolicy(include_spaces=spaces, include_newlines=newlines)
    # When the public counter measures it.
    actual = count_characters("가 나\n다", policy)
    # Then each policy has an independently specified character count.
    assert actual == expected


def test_length_count_normalizes_nfc_without_overwriting_source(source_case: ContractCase) -> None:
    # Given decomposed Hangul in preserved user text.
    source = source_case.replace(("sources", 0, "text"), "가").parse().sources[0]
    # When display length is measured.
    actual = count_characters(source.text, LengthPolicy())
    # Then the count is NFC-based while the quote source remains verbatim.
    assert actual == 1
    assert source.text == "가"


@pytest.mark.parametrize("field", ["previous_draft", "revision_context"])
def test_client_cannot_supply_server_owned_evidence(field: str) -> None:
    # Given a generated draft or server-owned history supplied by a client.
    payload = {field: "Earlier AI prose"}
    # When the request is parsed, then provenance injection is rejected.
    with pytest.raises(ValidationError):
        _ = EssayRequest.model_validate(payload)


@pytest.mark.parametrize("origin", ["assistant", "generated", "mcp"])
def test_generated_draft_is_not_applicant_source(source_case: ContractCase, origin: str) -> None:
    # Given personal evidence with an untrusted producer.
    case = source_case.replace(("sources", 0, "metadata", "origin"), origin)
    # When the source boundary parses it, then it is rejected.
    with pytest.raises((ValidationError, ContractViolation)):
        _ = case.parse()


def test_different_document_parent_is_rejected() -> None:
    # Given a request pointing at a version stored under another document.
    request = EssayRequest.model_validate(
        {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "parent_version_id": "v1",
        }
    )
    parent = StoredParent.model_validate(
        {
            "document_id": "00000000-0000-0000-0000-000000000002",
            "version_id": "v1",
        }
    )
    # When lineage is checked, then the cross-document reference is rejected.
    with pytest.raises(ContractViolation):
        validate_request_parent(request, parent)


def test_source_snapshot_span_immutable(source_case: ContractCase) -> None:
    # Given a parsed preserved source.
    source = source_case.parse().sources[0]
    # When another stage attempts to overwrite it, then mutation is rejected.
    with pytest.raises(ValidationError):
        source.text = "A new result that the user never supplied."


def test_source_metadata_is_deeply_immutable(source_case: ContractCase) -> None:
    # Given a source with typed nested metadata.
    source = source_case.parse().sources[0]
    # When producer metadata is rewritten, then the nested object is frozen too.
    with pytest.raises(ValidationError):
        source.metadata.origin = "mcp"


def test_model_output_requires_nullable_fields_and_forbids_extras() -> None:
    # Given the public structured-output schema.
    schema = PAYLOAD.validate_python(SourceSnapshot.model_json_schema())
    # When a model consumer inspects its metadata object.
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    metadata = definitions["SourceMetadata"]
    assert isinstance(metadata, dict)
    required = metadata["required"]
    assert isinstance(required, list)
    # Then absent optional values must be explicit null, and extra keys are forbidden.
    assert set(required) == {"origin", "label", "uri", "catalog"}
    assert metadata["additionalProperties"] is False


def test_sparse_context_boundary_does_not_require_a_later_stage() -> None:
    # Given an execution that has not yet produced analysis.
    context = ContractContext.model_validate({"evidence_version": "evidence-empty"})
    # When stage-independent integrity is checked.
    result = validate_contract(context)
    # Then missing stage outputs do not create an information refusal.
    assert result is None


def test_complete_contract_roundtrip_preserves_many_to_many_and_omit(
    complete_case: ContractCase,
) -> None:
    # Given a complete fictional source-to-result chain with an unknown required outcome.
    context = complete_case.parse()
    # When the public contract verifies and serializes it.
    validate_contract(context)
    restored = ContractContext.model_validate_json(context.model_dump_json())
    # Then logical sections and physical paragraphs retain independent mappings.
    assert restored == context
    assert restored.outline is not None
    assert len(restored.section_drafts[0].allocations) == 2
    assert len(restored.outline.paragraphs[0].allocations) == 2
    assert restored.section_drafts[2].allocations == ()


@pytest.mark.parametrize(
    "rejection", rejection_cases(), ids=[case.name for case in rejection_cases()]
)
def test_invalid_contract_is_rejected(complete_case: ContractCase, rejection: Rejection) -> None:
    # Given a valid control and exactly one malformed or stale field.
    validate_contract(complete_case.parse())
    changed = complete_case.replace(rejection.path, rejection.value)
    # When the changed payload crosses the public boundary, then it must fail.
    with pytest.raises((ValidationError, ContractViolation)):
        validate_contract(changed.parse())


def test_information_role_independent_of_availability(complete_case: ContractCase) -> None:
    # Given one supplied action, an unknown mandatory result, and irrelevant known context.
    context = complete_case.parse()
    # When the public boundary validates them.
    validate_contract(context)
    # Then necessity, availability, and applicability remain separate dimensions.
    assert context.analysis is not None
    links = context.analysis.evidence_links
    assert [
        (link.information_role, link.information_state, link.applicability, link.use_status)
        for link in links
    ] == [
        ("direct", "available", "applies", "candidate"),
        ("direct", "unverified", "applies", "held"),
        ("supporting", "available", "not_applicable", "excluded"),
    ]
    assert context.analysis.gaps[0].question_status == "proposed"


def test_missing_fact_recorded_as_gap_without_refusal(complete_case: ContractCase) -> None:
    # Given a missing required outcome that has no fabricated Fact.
    context = complete_case.parse()
    # When the completed result crosses the boundary.
    validate_contract(context)
    # Then a normal result retains the unfulfilled requirement and optional question.
    assert context.result is not None
    assert context.result.generation_status == "completed"
    assert context.result.structure[2].coverage == "not_expressed"
    assert context.result.suggestions[0].category == "required_info"
    assert context.review is not None
    assert context.review.repair_targets == ()


def test_body_and_copy_render_from_selected_sentences(complete_case: ContractCase) -> None:
    # Given the selected paragraph sentences and title.
    bundle = complete_case.parse().bundle
    assert bundle is not None
    # When the public renderers prepare body and copy text.
    body, copy = render_body(bundle), render_copy_text(bundle)
    # Then exact known fixture strings determine the expected output.
    expected = "I sorted library books. Order can help shared work.\n\nMy task was sorting books."
    assert body == expected
    assert copy == "Sorting library books\n\n" + expected


def test_display_only_title_is_excluded_from_copy(complete_case: ContractCase) -> None:
    # Given a title that is only displayed outside the answer.
    bundle = complete_case.replace(("bundle", "subtitle_placement"), "display_only").parse().bundle
    assert bundle is not None
    # When the submission copy is rendered.
    copy = render_copy_text(bundle)
    # Then the title is absent even though a visible title exists.
    assert (
        copy == "I sorted library books. Order can help shared work.\n\nMy task was sorting books."
    )


@pytest.mark.parametrize(
    "model",
    [
        Analysis,
        Outline,
        SectionDraft,
        WritingReport,
        IntegrationReport,
        DraftBundle,
        Review,
        EssayResult,
    ],
)
def test_stage_outputs_have_recursive_strict_schema(model: type[BaseModel]) -> None:
    # Given a public model-output DTO.
    schema_model = model
    # When all nested object definitions are checked, then every key is required.
    assert_strict_schema(schema_model)


def test_request_defaults_remain_optional_in_schema() -> None:
    # Given the public API request, whose sparse fields are optional.
    schema = PAYLOAD.validate_python(EssayRequest.model_json_schema())
    # When an API consumer reads required input fields.
    required = schema.get("required", [])
    # Then sparse input remains distinct from strict model output.
    assert required == []


def test_error_payload_preserves_previous_result(complete_case: ContractCase) -> None:
    # Given a technical failure after a real prior result exists.
    previous = complete_case.parse().result
    assert previous is not None
    # When the error envelope is constructed.
    error = RunErrorPayload(
        request_id=previous.request_id,
        generation_status="technical_error",
        code="workflow_failure",
        message="Processing failed",
        last_result=previous,
    )
    # Then the previous success remains intact inside a distinct error shape.
    assert error.last_result == previous
    assert error.last_result is not None
    assert error.last_result.generation_status == "completed"
    assert "body" not in error.model_dump()


@pytest.mark.parametrize("name", ACCEPTED_EDGE_FIXTURES)
def test_stage_edge_case_is_valid(name: str) -> None:
    # Given independent fixtures for repair, unparsed requirements, and empty-draft fallback.
    context = ContractCase.load(name).parse()
    # When the public boundary verifies each preserved state.
    result = validate_contract(context)
    # Then missing information and explicit fallback are accepted.
    assert result is None


@pytest.mark.parametrize(
    ("name", "path", "value"),
    [
        ("repairable.json", ("review", "repair_targets", 0, "section_ids"), ["section-result"]),
        ("unparsed.json", ("review", "requirement_checks", 1, "status"), "met"),
        ("unparsed.json", ("result", "quality_report", "display_status"), "reviewed_draft"),
        ("fallback.json", ("writing_report", "fallback_sentences"), []),
        ("fallback.json", ("bundle", "evidence_version"), "stale-evidence"),
        ("fallback.json", ("integration_report", "edits", 0, "section_ids"), ["invented"]),
    ],
)
def test_stage_edge_corruption_is_rejected(
    name: str,
    path: tuple[str | int, ...],
    value: JsonValue,
) -> None:
    # Given a valid edge-case control and one incompatible field change.
    case = ContractCase.load(name)
    validate_contract(case.parse())
    # When the altered state crosses the public boundary, then integrity fails.
    with pytest.raises((ValidationError, ContractViolation)):
        validate_contract(case.replace(path, value).parse())


def test_fact_source_span_is_immutable(complete_case: ContractCase) -> None:
    # Given a parsed fact whose offsets bind it to preserved user text.
    fact = complete_case.parse().facts[0]
    # When another stage changes a nested offset, then the source binding stays frozen.
    with pytest.raises(ValidationError):
        fact.span.start = 1


@pytest.mark.parametrize(
    ("control", "corrupted"),
    [
        ("removed-fallback.json", "retained-fallback.json"),
        ("merged-sections.json", "foreign-merged-fact.json"),
    ],
)
def test_integration_edge_corruption_is_rejected(control: str, corrupted: str) -> None:
    # Given a valid integration control and a candidate with a specific ownership violation.
    validate_contract(ContractCase.load(control).parse())
    # When the corrupted candidate is validated, then it must be rejected.
    with pytest.raises((ValidationError, ContractViolation)):
        validate_contract(ContractCase.load(corrupted).parse())


def test_result_suggestions_support_title_and_global_issues() -> None:
    # Given title and whole-answer suggestions without fabricated section IDs.
    context = ContractCase.load("suggestions.json").parse()
    # When the public boundary verifies the completed result.
    validate_contract(context)
    # Then both suggestion locations retain their explicit non-section scope.
    assert context.result is not None
    assert [(item.area, item.section_id) for item in context.result.suggestions[1:]] == [
        ("subtitle", None),
        ("whole_answer", None),
    ]
