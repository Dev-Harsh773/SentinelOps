"""Remediation LLM abstractions, deterministic fake provider, and LangChain implementation."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol
from pydantic import BaseModel, Field

from app.agents.models import EvidenceReference, Investigation, RootCauseAnalysis
from app.incidents.models import Incident
from app.memory.models import HistoricalIncidentContext
from app.remediation.models import (
    ChangeType,
    ProposedChange,
    ProposedChangeSchema,
    RemediationEvidenceReferenceSchema,
    RemediationProposal,
    RemediationStatus,
    RemediationValidation,
)
from app.remediation.prompts import (
    REMEDIATION_PROPOSAL_SYSTEM_PROMPT,
    REMEDIATION_REVISION_SYSTEM_PROMPT,
)
from app.telemetry.models import Evidence

logger = logging.getLogger(__name__)


# =====================================================================
# Structured Output Schema for LangChain LLM Provider
# =====================================================================


class LLMRemediationProposalOutput(BaseModel):
    """Structured Pydantic schema returned by LangChain provider for remediation."""

    summary: str = Field(description="High-level summary of the remediation recommendation")
    target_files: List[str] = Field(description="List of repository-relative files to change")
    target_symbols: List[str] = Field(default_factory=list, description="Targeted functions or classes")
    proposed_changes: List[ProposedChangeSchema] = Field(description="List of granular proposed changes")
    rationale: str = Field(description="Causal explanation of why this change resolves the failure")
    risks: List[str] = Field(description="Potential regressions, side effects, or operational risks")
    validation_steps: List[str] = Field(description="Concrete test commands or validation actions")
    evidence_references: List[RemediationEvidenceReferenceSchema] = Field(
        description="References to concrete current investigation evidence"
    )
    assumptions: List[str] = Field(default_factory=list, description="Explicit assumptions made")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Model-assessed remediation confidence")


# =====================================================================
# Remediation LLM Protocol
# =====================================================================


class RemediationLLM(Protocol):
    """Protocol defining the structured reasoning interface for remediation proposals."""

    def propose_remediation(
        self,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        ...

    def revise_remediation(
        self,
        proposal: RemediationProposal,
        validation: RemediationValidation,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        ...


# =====================================================================
# Deterministic Offline Fake Provider
# =====================================================================


class FakeRemediationLLM:
    """Deterministic, 100% offline implementation of RemediationLLM for testing and mock mode."""

    def __init__(self) -> None:
        self.raise_error: bool = False
        self.error_message: str = "Simulated Remediation LLM provider error."
        self.custom_proposal: Optional[RemediationProposal] = None
        self.custom_revision: Optional[RemediationProposal] = None
        self.revision_handler: Optional[Callable[..., RemediationProposal]] = None

    def propose_remediation(
        self,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        if self.raise_error:
            raise RuntimeError(self.error_message)
        if self.custom_proposal:
            return self.custom_proposal

        now = datetime.now(timezone.utc)
        rca: RootCauseAnalysis = investigation.rca  # Guaranteed present by eligibility gate

        target_files: List[str] = []
        target_symbols: List[str] = []
        proposed_changes: List[ProposedChange] = []

        if code_chunks:
            top_chunk = code_chunks[0]
            fp = top_chunk.get("file_path", "app/main.py")
            sym = top_chunk.get("symbol_name") or rca.failure_location or None
            target_files.append(fp)
            if sym:
                target_symbols.append(sym)

            sym_lower = (sym or "").lower()
            chunk_content = top_chunk.get("content", "").lower()
            if "disable" in sym_lower and ("controller.disable" in chunk_content or "disabled" in chunk_content):
                proposed_changes.append(
                    ProposedChange(
                        file_path=fp,
                        change_type=ChangeType.CONFIGURATION,
                        description=f"Invoke existing operational control {sym or fp} to disable the failure mode",
                        reason=f"Safely deactivates triggering condition: {rca.triggering_condition}",
                        symbol=sym,
                    )
                )
            else:
                proposed_changes.append(
                    ProposedChange(
                        file_path=fp,
                        change_type=ChangeType.MODIFY,
                        description=f"Add defensive handling around failure condition in {sym or fp}",
                        reason=f"Safely neutralizes triggering condition: {rca.triggering_condition}",
                        symbol=sym,
                    )
                )
        elif investigation.code_analysis and investigation.code_analysis.relevant_files:
            fp = investigation.code_analysis.relevant_files[0]
            sym = investigation.code_analysis.relevant_symbols[0] if investigation.code_analysis.relevant_symbols else None
            target_files.append(fp)
            if sym:
                target_symbols.append(sym)
            proposed_changes.append(
                ProposedChange(
                    file_path=fp,
                    change_type=ChangeType.MODIFY,
                    description=f"Modify {sym or fp} to prevent uncaught error",
                    reason=f"Addresses RCA: {rca.root_cause_hypothesis}",
                    symbol=sym,
                )
            )

        evidence_refs: List[EvidenceReference] = []
        if runtime_evidence:
            evidence_refs.append(
                EvidenceReference(
                    type="runtime",
                    id=runtime_evidence[0].id,
                    description=f"Runtime error log for event '{runtime_evidence[0].event}'",
                )
            )
        if code_chunks and code_chunks[0].get("id"):
            evidence_refs.append(
                EvidenceReference(
                    type="code",
                    id=code_chunks[0]["id"],
                    description=f"Source code chunk in {code_chunks[0].get('file_path')}",
                )
            )

        rationale = (
            f"This proposal addresses the verified root cause in {rca.failure_location} where "
            f"{rca.triggering_condition}. Modifying the execution branch ensures errors are handled safely."
        )

        risks = [
            "Low risk: change is localized to the verified failing method and guarded by tests.",
        ]

        validation_steps = [
            f"Run automated regression tests for {target_files[0] if target_files else incident.service}",
            "Verify endpoint response under simulated fault conditions",
        ]

        return RemediationProposal(
            remediation_id=str(uuid.uuid4()),
            incident_id=incident.id,
            investigation_id=investigation.investigation_id,
            status=RemediationStatus.VALIDATED,
            summary=f"Defensive remediation for {rca.failure_location or incident.service}",
            target_files=target_files,
            target_symbols=target_symbols,
            proposed_changes=proposed_changes,
            rationale=rationale,
            risks=risks,
            validation_steps=validation_steps,
            evidence_references=evidence_refs,
            assumptions=["System dependencies remain unchanged."],
            advisory_historical_context=[h.incident_id for h in historical_context],
            confidence=0.85,
            created_at=now,
            updated_at=now,
        )

    def revise_remediation(
        self,
        proposal: RemediationProposal,
        validation: RemediationValidation,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        if self.raise_error:
            raise RuntimeError(self.error_message)
        if self.revision_handler:
            return self.revision_handler(proposal=proposal, validation=validation)
        if self.custom_revision:
            return self.custom_revision

        # Clean unsupported files and symbols
        valid_files = [c["file_path"] for c in code_chunks if c.get("file_path")]
        cleaned_target_files = [f for f in proposal.target_files if f in valid_files]
        if not cleaned_target_files and valid_files:
            cleaned_target_files = [valid_files[0]]

        valid_symbols = [c["symbol_name"] for c in code_chunks if c.get("symbol_name")]
        cleaned_target_symbols = [s for s in proposal.target_symbols if s in valid_symbols]

        cleaned_changes: List[ProposedChange] = []
        for pc in proposal.proposed_changes:
            target_fp = pc.file_path if pc.file_path in valid_files else (valid_files[0] if valid_files else pc.file_path)
            target_sym = pc.symbol if pc.symbol in valid_symbols else (valid_symbols[0] if valid_symbols else None)
            change_type = pc.change_type
            desc = pc.description

            # If the revision addresses a redundant modify on an existing disable control:
            if target_sym and "disable" in target_sym.lower() and change_type != ChangeType.CONFIGURATION:
                change_type = ChangeType.CONFIGURATION
                desc = f"Invoke existing operational control {target_sym} to disable the failure mode"

            cleaned_changes.append(
                ProposedChange(
                    file_path=target_fp,
                    change_type=change_type,
                    description=desc,
                    reason=pc.reason,
                    symbol=target_sym,
                )
            )

        # Ensure valid evidence references
        valid_ev_refs = [
            ref for ref in proposal.evidence_references
            if not ref.id.startswith("inc-")
        ]
        if not valid_ev_refs:
            if runtime_evidence:
                valid_ev_refs.append(
                    EvidenceReference(type="runtime", id=runtime_evidence[0].id, description="Current runtime log")
                )
            if code_chunks:
                valid_ev_refs.append(
                    EvidenceReference(type="code", id=code_chunks[0]["id"], description="Current code chunk")
                )

        return RemediationProposal(
            remediation_id=proposal.remediation_id,
            incident_id=incident.id,
            investigation_id=investigation.investigation_id,
            status=RemediationStatus.VALIDATED,
            summary=proposal.summary,
            target_files=cleaned_target_files,
            target_symbols=cleaned_target_symbols,
            proposed_changes=cleaned_changes,
            rationale=proposal.rationale,
            risks=proposal.risks,
            validation_steps=proposal.validation_steps,
            evidence_references=valid_ev_refs,
            assumptions=proposal.assumptions,
            advisory_historical_context=proposal.advisory_historical_context,
            confidence=max(0.1, proposal.confidence - 0.1),
            created_at=proposal.created_at,
            updated_at=datetime.now(timezone.utc),
        )


# =====================================================================
# LangChain / OpenAI Provider Implementation
# =====================================================================


class LangChainRemediationLLM:
    """Production Remediation LLM implementation using LangChain ChatOpenAI and structured output."""

    def __init__(self, model_name: str, api_key: str) -> None:
        try:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(model=model_name, api_key=api_key, temperature=0.1)
        except Exception as exc:
            logger.error("Failed to initialize LangChain ChatOpenAI for remediation: %s", exc)
            raise RuntimeError(f"Could not initialize Remediation LLM provider: {exc}") from exc

    def propose_remediation(
        self,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        structured_model = self._llm.with_structured_output(LLMRemediationProposalOutput)

        chunks_context = "\n---\n".join(
            f"Chunk ID: {c.get('id', 'chunk')}\nFile: {c.get('file_path', 'unknown')}\n"
            f"Symbol: {c.get('symbol_name', 'none')}\nContent:\n{c.get('content', '')}"
            for c in code_chunks
        ) if code_chunks else "No code chunks retrieved."

        runtime_evidence_lines = "\n".join(
            f"- [ID: {e.id}] Service: {e.service}, Endpoint: {e.endpoint}, Event: {e.event}, Message: {e.message}"
            for e in runtime_evidence
        ) if runtime_evidence else "No runtime evidence."

        hist_lines = [
            f"- Past Incident {h.incident_id} ('{h.title}'): RCA hypothesis was '{h.root_cause_hypothesis}'"
            for h in historical_context
        ]
        hist_text = "\n".join(hist_lines) if hist_lines else "No past incidents found."

        rca = investigation.rca

        prompt = (
            f"{REMEDIATION_PROPOSAL_SYSTEM_PROMPT}\n\n"
            f"Incident: {incident.title} (Service: {incident.service}, Severity: {incident.severity.value})\n\n"
            f"Validated RCA:\n"
            f"Failure Location: {rca.failure_location}\n"
            f"Triggering Condition: {rca.triggering_condition}\n"
            f"Root Cause Hypothesis: {rca.root_cause_hypothesis}\n"
            f"Summary: {rca.summary}\n\n"
            f"Valid Retrieved Code Chunks (Allowed Target Files & Symbols):\n{chunks_context}\n\n"
            f"Current Runtime Evidence (Valid Evidence IDs):\n{runtime_evidence_lines}\n\n"
            f"Available Runtime Evidence IDs: {[e.id for e in runtime_evidence]}\n"
            f"Available Code Chunk IDs: {[c['id'] for c in code_chunks if 'id' in c]}\n\n"
            f"Advisory Historical Context (DO NOT cite as current evidence):\n{hist_text}\n"
        )

        result: LLMRemediationProposalOutput = structured_model.invoke(prompt)
        now = datetime.now(timezone.utc)

        return RemediationProposal(
            remediation_id=str(uuid.uuid4()),
            incident_id=incident.id,
            investigation_id=investigation.investigation_id,
            status=RemediationStatus.VALIDATED,
            summary=result.summary,
            target_files=result.target_files,
            target_symbols=result.target_symbols,
            proposed_changes=[
                ProposedChange(
                    file_path=pc.file_path,
                    change_type=pc.change_type,
                    description=pc.description,
                    reason=pc.reason,
                    symbol=pc.symbol,
                )
                for pc in result.proposed_changes
            ],
            rationale=result.rationale,
            risks=result.risks,
            validation_steps=result.validation_steps,
            evidence_references=[
                EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                for ref in result.evidence_references
            ],
            assumptions=result.assumptions,
            advisory_historical_context=[h.incident_id for h in historical_context],
            confidence=result.confidence,
            created_at=now,
            updated_at=now,
        )

    def revise_remediation(
        self,
        proposal: RemediationProposal,
        validation: RemediationValidation,
        incident: Incident,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
        historical_context: List[HistoricalIncidentContext],
    ) -> RemediationProposal:
        structured_model = self._llm.with_structured_output(LLMRemediationProposalOutput)

        chunks_context = "\n---\n".join(
            f"Chunk ID: {c.get('id', 'chunk')}\nFile: {c.get('file_path', 'unknown')}\n"
            f"Symbol: {c.get('symbol_name', 'none')}\nContent:\n{c.get('content', '')}"
            for c in code_chunks
        ) if code_chunks else "No code chunks retrieved."

        prompt = (
            f"{REMEDIATION_REVISION_SYSTEM_PROMPT}\n\n"
            f"Prior Remediation Proposal:\n"
            f"Summary: {proposal.summary}\n"
            f"Target Files: {proposal.target_files}\n"
            f"Target Symbols: {proposal.target_symbols}\n"
            f"Rationale: {proposal.rationale}\n\n"
            f"Validation Critique to Fix:\n"
            f"Issues: {validation.issues}\n"
            f"Unsupported Files: {validation.unsupported_files}\n"
            f"Unsupported Symbols: {validation.unsupported_symbols}\n"
            f"Missing Elements: {validation.missing_elements}\n\n"
            f"Valid Retrieved Code Chunks:\n{chunks_context}\n\n"
            f"Available Runtime Evidence IDs: {[e.id for e in runtime_evidence]}\n"
            f"Available Code Chunk IDs: {[c['id'] for c in code_chunks if 'id' in c]}\n"
        )

        result: LLMRemediationProposalOutput = structured_model.invoke(prompt)

        return RemediationProposal(
            remediation_id=proposal.remediation_id,
            incident_id=incident.id,
            investigation_id=investigation.investigation_id,
            status=RemediationStatus.VALIDATED,
            summary=result.summary,
            target_files=result.target_files,
            target_symbols=result.target_symbols,
            proposed_changes=[
                ProposedChange(
                    file_path=pc.file_path,
                    change_type=pc.change_type,
                    description=pc.description,
                    reason=pc.reason,
                    symbol=pc.symbol,
                )
                for pc in result.proposed_changes
            ],
            rationale=result.rationale,
            risks=result.risks,
            validation_steps=result.validation_steps,
            evidence_references=[
                EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                for ref in result.evidence_references
            ],
            assumptions=result.assumptions,
            advisory_historical_context=proposal.advisory_historical_context,
            confidence=result.confidence,
            created_at=proposal.created_at,
            updated_at=datetime.now(timezone.utc),
        )
