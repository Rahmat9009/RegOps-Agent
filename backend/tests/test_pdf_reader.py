from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import PdfLimits
from regops_api.pdf_reader import parse_pdf
from regops_api.worker_models import SourceDocument
from tests.test_worker_models import source_fixture

SAMPLE = Path(__file__).resolve().parents[2] / "samples/regops-synthetic-regulation-2026.pdf"


def pdf_bytes(
    *texts: str, encrypted: bool = False, javascript: bool = False, attachment: bool = False
) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                ),
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 20 700 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    if encrypted:
        writer.encrypt("test-only-password")
    if javascript:
        writer.add_js("app.alert('synthetic adversarial test')")
    if attachment:
        writer.add_attachment("instructions.txt", b"synthetic uninspected instructions")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def parse(content: bytes, **limits: int) -> SourceDocument:
    return parse_pdf(
        content=content,
        doc_id="SYN-PDF",
        source_sha256=sha256(content).hexdigest(),
        limits=PdfLimits(**limits),
    )


def test_checked_in_pdf_has_four_exact_bound_one_based_pages() -> None:
    expected = source_fixture()
    content = SAMPLE.read_bytes()
    actual = parse_pdf(
        content=content,
        doc_id=expected.identity.doc_id,
        source_sha256=expected.identity.source_sha256,
    )
    assert actual == expected
    assert [page.page for page in actual.pages] == [1, 2, 3, 4]
    assert {p.source_sha256 for p in actual.pages} == {sha256(content).hexdigest()}


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"not a PDF", AnalystCode.PDF_INVALID),
        (b"%PDF-1.7\nprivate broken PDF text", AnalystCode.PDF_INVALID),
        (pdf_bytes("synthetic", encrypted=True), AnalystCode.PDF_ENCRYPTED),
        (pdf_bytes(), AnalystCode.PDF_TEXT_UNAVAILABLE),
        (pdf_bytes(""), AnalystCode.PDF_TEXT_UNAVAILABLE),
        (pdf_bytes("synthetic", ""), AnalystCode.PDF_TEXT_UNAVAILABLE),
        (pdf_bytes("synthetic", javascript=True), AnalystCode.PDF_INVALID),
        (pdf_bytes("synthetic", attachment=True), AnalystCode.PDF_INVALID),
    ],
    ids=[
        "signature",
        "damaged",
        "encrypted",
        "zero-pages",
        "blank",
        "blank-page",
        "active",
        "attachment",
    ],
)
def test_rejected_pdfs_have_only_sanitized_errors(
    content: bytes, code: AnalystCode, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(AnalystError) as caught:
        parse(content)
    assert caught.value.code is code
    assert str(caught.value) == code.value
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    ("limits", "code"),
    [
        ({"max_bytes": 1024}, AnalystCode.PDF_TOO_LARGE),
        ({"max_pages": 3}, AnalystCode.PDF_PAGE_LIMIT),
        ({"max_page_chars": 100}, AnalystCode.PDF_TEXT_LIMIT),
        ({"max_total_chars": 2000}, AnalystCode.PDF_TEXT_LIMIT),
    ],
)
def test_pdf_bounds(limits: dict[str, int], code: AnalystCode) -> None:
    with pytest.raises(AnalystError) as caught:
        parse(SAMPLE.read_bytes(), **limits)
    assert caught.value.code is code


def test_source_hash_cannot_be_rebound() -> None:
    with pytest.raises(AnalystError, match="SOURCE_BINDING_MISMATCH"):
        parse_pdf(content=SAMPLE.read_bytes(), doc_id="SYN-PDF", source_sha256="0" * 64)


def test_unfiltered_stream_has_an_independent_decoded_size_limit() -> None:
    # pypdf can reject the declared stream length before our decoded-size check.
    # Neither path may proceed to text extraction (PDF_TEXT_LIMIT).
    with pytest.raises(AnalystError, match=r"^PDF_(INVALID|TOO_LARGE)$"):
        parse(pdf_bytes("x" * (8 * 1024 * 1024)))


def test_character_limits_do_not_truncate_and_boundary_is_inclusive() -> None:
    content = pdf_bytes("Synthetic text")
    result = parse(content)
    length = len(result.pages[0].text)
    assert parse(content, max_page_chars=length, max_total_chars=length) == result
    with pytest.raises(AnalystError, match="PDF_TEXT_LIMIT"):
        parse(content, max_total_chars=length - 1)


def test_parser_timeout_is_terminal_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("private internal command", 10, output=b"private text")

    monkeypatch.setattr("regops_api.pdf_reader.subprocess.run", timeout)
    with pytest.raises(AnalystError, match=r"^PDF_INVALID$") as caught:
        parse(SAMPLE.read_bytes())
    assert not caught.value.transient
    assert caught.value.__context__ is None
