"""Single ADK topology with deterministic ordering and structural least privilege.

Phase 1B.2C defines the application and its one-shot Investigator boundary only.
It deliberately does not wire API intake, persistence, state transitions, actions,
or approval handling; those remain backend-owned orchestration work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import vertexai
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.sessions import InMemorySessionService
from google.genai import types
from vertexai.agent_engines import AdkApp

from regops_api.adk_investigator import (
    AdkImpactInvestigator,
    build_impact_investigator_agent,
)
from regops_api.corpus import TOOL_NAMES, ImmutableSyntheticCorpus
from regops_api.gemini_analyst import analyst_prompt
from regops_api.worker_models import AnalystDraftOutput, WorkerModel

RUNTIME_APP_NAME = "regops-phase1b2-worker"
ROOT_AGENT_NAME = "regops_phase1b2_root"
ANALYST_AGENT_NAME = "regulation_analyst"

FORBIDDEN_MODEL_CAPABILITIES = frozenset(
    {
        "firestore",
        "repository",
        "approval",
        "reviewer_identity",
        "action_policy",
        "action_controller",
        "draft_amendment",
        "write_contract",
        "workflow",
        "network",
        "web_search",
        "code_execution",
    }
)


class CapabilityRegistry(WorkerModel):
    role: Literal["analyst", "investigator"]
    callable_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegOpsAdkApplication:
    root_agent: SequentialAgent
    analyst_agent: LlmAgent
    investigator_agent: LlmAgent
    investigator: AdkImpactInvestigator
    analyst_capabilities: CapabilityRegistry
    investigator_capabilities: CapabilityRegistry


def build_regulation_analyst_agent(*, model: str = "gemini-3.5-flash") -> LlmAgent:
    """ADK component metadata; the guarded 1B.2B adapter owns actual extraction."""
    return LlmAgent(
        name=ANALYST_AGENT_NAME,
        description="Candidate-only extraction from one root-supplied synthetic source.",
        model=model,
        instruction=analyst_prompt(),
        tools=[],
        output_schema=AnalystDraftOutput,
        mode="single_turn",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            candidate_count=1,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        ),
    )


def build_adk_application(
    *, corpus: ImmutableSyntheticCorpus, model: str = "gemini-3.5-flash"
) -> RegOpsAdkApplication:
    analyst = build_regulation_analyst_agent(model=model)
    investigator_agent = build_impact_investigator_agent(corpus=corpus, model=model)
    root = SequentialAgent(
        name=ROOT_AGENT_NAME,
        description="Deterministic fixed-order RegOps Phase 1B.2 component topology.",
        sub_agents=[analyst, investigator_agent],
    )
    investigator = AdkImpactInvestigator(
        corpus=corpus,
        model=model,
        agent=investigator_agent,
    )
    return RegOpsAdkApplication(
        root_agent=root,
        analyst_agent=analyst,
        investigator_agent=investigator_agent,
        investigator=investigator,
        analyst_capabilities=CapabilityRegistry(role="analyst", callable_tools=()),
        investigator_capabilities=CapabilityRegistry(
            role="investigator", callable_tools=TOOL_NAMES
        ),
    )


def build_agent_runtime_app(
    application: RegOpsAdkApplication, *, project_id: str, location: str
) -> AdkApp:
    """Create one explicitly configured wrapper without ADC or persistent memory."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", project_id) or not re.fullmatch(
        r"[a-z][a-z0-9-]{1,62}", location
    ):
        raise ValueError("ADK_RUNTIME_CONFIGURATION_INVALID")
    vertexai.init(project=project_id, location=location)
    return AdkApp(
        agent=application.root_agent,
        app_name=RUNTIME_APP_NAME,
        enable_tracing=False,
        session_service_builder=InMemorySessionService,
    )
