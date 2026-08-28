"""Independent local extraction in a disposable, time-bounded parser process.

PDF bytes travel through stdin, never argv, temporary files, URLs or logs.
The child emits either a bounded manifest or a fixed error code. No OCR/repair.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from hashlib import sha256
from hmac import compare_digest
from io import BytesIO

from pydantic import TypeAdapter, ValidationError
from pypdf import PdfReader, filters
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import PdfLimits
from regops_api.schemas import DocumentKind
from regops_api.worker_models import (
    Digest,
    Identifier,
    ImmutableSourceIdentity,
    SourceDocument,
    SourcePage,
)

DEFAULT_PDF_LIMITS = PdfLimits()


def parse_pdf(
    *, content: bytes, doc_id: str, source_sha256: str, limits: PdfLimits = DEFAULT_PDF_LIMITS
) -> SourceDocument:
    try:
        limits = PdfLimits.model_validate(limits)
        TypeAdapter(Identifier).validate_python(doc_id, strict=True)
        TypeAdapter(Digest).validate_python(source_sha256, strict=True)
    except ValidationError:
        raise AnalystError(AnalystCode.SOURCE_BINDING_MISMATCH) from None
    if type(content) is not bytes or not re.match(rb"%PDF-[12]\.[0-9](?:\r|\n)", content):
        raise AnalystError(AnalystCode.PDF_INVALID)
    if len(content) > limits.max_bytes:
        raise AnalystError(AnalystCode.PDF_TOO_LARGE)
    if not compare_digest(sha256(content).hexdigest(), source_sha256):
        raise AnalystError(AnalystCode.SOURCE_BINDING_MISMATCH)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "regops_api.pdf_reader",
                doc_id,
                source_sha256,
                limits.model_dump_json(),
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=limits.timeout_seconds,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode:
            # The only error body accepted from the child is an enum value.
            code = AnalystCode(result.stdout.decode("ascii"))
            if not code.value.startswith("PDF_"):
                code = AnalystCode.PDF_INVALID
            raise AnalystError(code)
        return SourceDocument.model_validate_json(result.stdout)
    except AnalystError:
        raise
    except Exception:
        pass
    raise AnalystError(AnalystCode.PDF_INVALID)


def _extract(content: bytes, doc_id: str, digest: str, limits: PdfLimits) -> SourceDocument:
    # These globals are confined to the disposable child, never the API process.
    for name in (
        "ZLIB_MAX_OUTPUT_LENGTH",
        "LZW_MAX_OUTPUT_LENGTH",
        "RUN_LENGTH_MAX_OUTPUT_LENGTH",
        "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
        "MAX_DECLARED_STREAM_LENGTH",
        "FLATE_MAX_BUFFER_SIZE",
    ):
        setattr(filters, name, 8 * 1024 * 1024)
    reader = PdfReader(BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise AnalystError(AnalystCode.PDF_ENCRYPTED)
    # The checked-in sample has an associated C2PA provenance record. It is
    # metadata, not source evidence; skip only this explicit FileSpec shape.
    # No original PDF/metadata bytes are supplied to Gemini (inspected text only).
    root = reader.trailer["/Root"]
    if not isinstance(root, DictionaryObject):
        raise AnalystError(AnalystCode.PDF_INVALID)
    names = root.get("/Names", DictionaryObject()).get_object()
    if not isinstance(names, DictionaryObject):
        raise AnalystError(AnalystCode.PDF_INVALID)
    ignored: set[int] = set()
    if "/EmbeddedFiles" in names:
        embedded = names["/EmbeddedFiles"].get_object()
        if not isinstance(embedded, DictionaryObject):
            raise AnalystError(AnalystCode.PDF_INVALID)
        entries = embedded.get("/Names", [])
        if set(embedded) != {"/Names"} or not entries or len(entries) % 2:
            raise AnalystError(AnalystCode.PDF_INVALID)
        for index in range(0, len(entries), 2):
            spec = entries[index + 1].get_object()
            if not isinstance(spec, DictionaryObject):
                raise AnalystError(AnalystCode.PDF_INVALID)
            if (
                entries[index] != "Content Credentials"
                or spec.get("/AFRelationship") != "/C2PA_Manifest"
                or spec.get("/Subtype") != "application/c2pa"
                or spec.get("/Type") != "/FileSpec"
                or set(spec) - {"/AFRelationship", "/Desc", "/F", "/Subtype", "/Type", "/UF", "/EF"}
            ):
                raise AnalystError(AnalystCode.PDF_INVALID)
            ignored.add(id(spec))
        ignored.add(id(embedded))
    # Walk the object graph with cycle/node/stream budgets before extraction.
    pending: list[object] = [reader.trailer]
    seen: set[int] = ignored
    stream_bytes = 0
    nodes = 0
    forbidden = {
        "/JavaScript",
        "/JS",
        "/OpenAction",
        "/AA",
        "/EF",
        "/Launch",
        "/XFA",
        "/RichMediaContent",
        "/URI",
        "/AcroForm",
    }
    while pending:
        value = pending.pop()
        nodes += 1
        if nodes > 50_000:
            raise AnalystError(AnalystCode.PDF_INVALID)
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, DictionaryObject):
            if forbidden.intersection(value):
                raise AnalystError(AnalystCode.PDF_INVALID)
            if value.get("/Subtype") == "/Image":
                raise AnalystError(AnalystCode.PDF_TEXT_UNAVAILABLE)
            if isinstance(value, StreamObject):
                # No external decoders or exotic image filters in this text-only boundary.
                names = value.get("/Filter", [])
                if isinstance(names, str):
                    names = [names]
                if any(
                    n not in {"/FlateDecode", "/ASCII85Decode", "/ASCIIHexDecode"} for n in names
                ):
                    raise AnalystError(AnalystCode.PDF_INVALID)
                decoded_size = len(value.get_data())
                stream_bytes += decoded_size
                if decoded_size > 8 * 1024 * 1024 or stream_bytes > 32 * 1024 * 1024:
                    raise AnalystError(AnalystCode.PDF_TOO_LARGE)
            pending.extend(value.values())
        elif isinstance(value, ArrayObject):
            pending.extend(value)
    count = len(reader.pages)
    if count < 1:
        raise AnalystError(AnalystCode.PDF_TEXT_UNAVAILABLE)
    if count > limits.max_pages:
        raise AnalystError(AnalystCode.PDF_PAGE_LIMIT)
    pages: list[SourcePage] = []
    total = 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        if not text or not text.strip():
            # A page we cannot inspect is not silently sent to Gemini.
            raise AnalystError(AnalystCode.PDF_TEXT_UNAVAILABLE)
        total += len(text)
        if len(text) > limits.max_page_chars or total > limits.max_total_chars:
            raise AnalystError(AnalystCode.PDF_TEXT_LIMIT)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        pages.append(SourcePage(doc_id=doc_id, source_sha256=digest, page=number, text=text))
    return SourceDocument(
        identity=ImmutableSourceIdentity(
            doc_id=doc_id,
            doc_kind=DocumentKind.REGULATION,
            source_sha256=digest,
            page_count=count,
            synthetic=True,
        ),
        pages=tuple(pages),
    )


def _main() -> None:
    logging.disable(sys.maxsize)
    try:
        limits = PdfLimits.model_validate_json(sys.argv[3])
        data = sys.stdin.buffer.read(limits.max_bytes + 1)
        if len(data) > limits.max_bytes:
            raise AnalystError(AnalystCode.PDF_TOO_LARGE)
        output = _extract(data, sys.argv[1], sys.argv[2], limits)
        sys.stdout.buffer.write(output.model_dump_json().encode("utf-8"))
        return
    except AnalystError as error:
        code = error.code
    except Exception:
        code = AnalystCode.PDF_INVALID
    sys.stdout.buffer.write(code.value.encode("ascii"))
    sys.exit(1)


if __name__ == "__main__":
    _main()
