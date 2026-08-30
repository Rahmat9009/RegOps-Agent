"""Opt-in, content-free live diagnosis of Gemini output through Model Armor."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from typing import cast

import pytest
from google import genai
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1
from google.genai import types

from regops_api.adapter_logging import sensitive_io
from regops_api.analyst_errors import AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.gemini_analyst import GeminiRegulationAnalyst, _decode_model_response
from regops_api.model_armor import ArmorOutcome, ArmorResult, GoogleModelArmor, TextInspection
from tests.test_pdf_reader import SAMPLE
from tests.test_worker_models import source_fixture

_ENABLED = os.getenv("REGOPS_LIVE_GEMINI_ARMOR_DIAGNOSTIC") == "1"


class _UnusedInspection:
    def inspect(self, *, text: str, direction: str, timeout: float) -> ArmorResult:
        raise AssertionError("DIAGNOSTIC_INSPECTION_PORT_WAS_NOT_EXPECTED")


def _template_location(template: str, project: str) -> str:
    match = re.fullmatch(
        rf"projects/{re.escape(project)}/locations/([a-z][a-z0-9-]{{1,62}})/"
        r"templates/regops-output",
        template,
    )
    if match is None:
        raise ValueError("INVALID_OUTPUT_TEMPLATE_RESOURCE")
    return match.group(1)


@pytest.mark.live_gemini
@pytest.mark.skipif(not _ENABLED, reason="live Gemini/Armor diagnostic explicitly disabled")
def test_live_gemini_output_reports_only_fixed_armor_categories() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    gemini_location = os.getenv("REGOPS_GEMINI_LOCATION") or os.getenv("REGOPS_REGION")
    if not project or not gemini_location:
        pytest.skip("explicit Gemini project/location configuration is incomplete")
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        pytest.fail("ADC_REQUIRED", pytrace=False)

    raw_outcome: ArmorOutcome | None = None
    decoded_outcome: ArmorOutcome | None = None
    candidate_count = 0
    text_part_count = 0
    failure = "LIVE_DIAGNOSTIC_DEPENDENCY_FAILED"
    with sensitive_io():
        discovery: modelarmor_v1.ModelArmorClient | None = None
        armor_client: modelarmor_v1.ModelArmorClient | None = None
        gemini: genai.Client | None = None
        try:
            discovery = modelarmor_v1.ModelArmorClient()
            matches = [
                template.name
                for template in discovery.list_templates(
                    parent=f"projects/{project}/locations/-",
                    retry=None,
                    timeout=20,
                )
                if template.name.endswith("/templates/regops-output")
            ]
            if len(matches) != 1:
                failure = "REGOPS_OUTPUT_TEMPLATE_NOT_UNIQUE"
                raise RuntimeError
            output_template = matches[0]
            armor_location = _template_location(output_template, project)
            armor_client = modelarmor_v1.ModelArmorClient(
                client_options=ClientOptions(
                    api_endpoint=f"modelarmor.{armor_location}.rep.googleapis.com"
                )
            )
            armor = GoogleModelArmor(
                client=armor_client,
                input_template=output_template,
                output_template=output_template,
            )
            gemini = genai.Client(
                enterprise=True,
                project=project,
                location=gemini_location,
                http_options=types.HttpOptions(
                    api_version="v1",
                    timeout=90_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            source = source_fixture()
            if sha256(SAMPLE.read_bytes()).hexdigest() != source.identity.source_sha256:
                failure = "TRACKED_SYNTHETIC_SOURCE_MISMATCH"
                raise RuntimeError
            unused = cast(TextInspection, _UnusedInspection())
            analyst = GeminiRegulationAnalyst(
                content=SAMPLE.read_bytes(),
                settings=AnalystSettings(),
                client=gemini.models,
                input_inspector=unused,
                output_inspector=unused,
            )
            raw = analyst._generate(source, 90)
            raw_outcome = armor.inspect(text=raw, direction="output", timeout=10).outcome
            decoded = _decode_model_response(raw, max_output_chars=32_000)
            decoded_outcome = armor.inspect(
                text=decoded.text,
                direction="output",
                timeout=10,
            ).outcome
            candidate_count = decoded.candidate_count
            text_part_count = decoded.text_part_count
            del raw
            del decoded
            output_template = ""
            matches.clear()
        except AnalystError as error:
            failure = error.code.value
        except Exception:
            pass
        finally:
            if gemini is not None:
                gemini.close()
            if armor_client is not None:
                armor_client.transport.close()  # type: ignore[no-untyped-call]
            if discovery is not None:
                discovery.transport.close()  # type: ignore[no-untyped-call]

    if raw_outcome is None or decoded_outcome is None:
        pytest.fail(failure, pytrace=False)
    print(f"LIVE_MODEL_ARMOR RAW_OUTCOME={raw_outcome.value}")
    print(f"LIVE_MODEL_ARMOR DECODED_TEXT_OUTCOME={decoded_outcome.value}")
    print(f"LIVE_MODEL_ARMOR CANDIDATES={candidate_count}")
    print(f"LIVE_MODEL_ARMOR TEXT_PARTS={text_part_count}")
    if candidate_count != 1 or text_part_count < 1:
        pytest.fail("LIVE_RESPONSE_STRUCTURE_CHANGED", pytrace=False)
