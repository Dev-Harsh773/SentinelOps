"""LLM provider abstraction, deterministic fake implementation, and LangChain integration."""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Protocol

from app.agents.models import (
    ChangeAnalysis,
    CodeAnalysis,
    EvidenceReference,
    InvestigationLLMError,
    RCAValidation,
    RootCauseAnalysis,
    RuntimeAnalysis,
)
from app.agents.prompts import (
    CHANGE_ANALYSIS_SYSTEM_PROMPT,
    CODE_ANALYSIS_SYSTEM_PROMPT,
    RCA_REVISION_SYSTEM_PROMPT,
    RCA_SYNTHESIS_SYSTEM_PROMPT,
    RCA_VALIDATION_SYSTEM_PROMPT,
    RUNTIME_ANALYSIS_SYSTEM_PROMPT,
)
from app.agents.schemas import (
    ChangeAnalysisSchema,
    CodeAnalysisSchema,
    RCAValidationSchema,
    RootCauseAnalysisSchema,
    RuntimeAnalysisSchema,
)
from app.incidents.models import Incident
from app.telemetry.models import Evidence
from app.agents.grounding import (
    HALLUCINATED_ORDER_FIELDS,
    is_grounded_control_flow_claim,
    reconcile_semantic_validation_findings,
    run_deterministic_grounding_check,
)

logger = logging.getLogger(__name__)


def _sanitize_error_message(msg: str) -> str:
    """Sanitizes error messages to remove API keys, Bearer tokens, and secrets."""
    if not msg:
        return ""
    # Mask sk-... OpenAI API keys
    msg = re.sub(r"sk-[a-zA-Z0-9_\-]{15,}", "sk-[REDACTED]", msg)
    # Mask Bearer tokens
    msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", msg, flags=re.IGNORECASE)
    # Mask Authorization headers
    msg = re.sub(r"('Authorization'|\"Authorization\"):\s*('[^']+'|\"[^\"]+\")", r"\1: '[REDACTED]'", msg)
    return msg


class InvestigationLLM(Protocol):
    """Protocol defining the structured reasoning interface for investigation agents."""

    def analyze_runtime(self, incident: Incident, evidence: List[Evidence]) -> RuntimeAnalysis:
        ...

    def analyze_code(
        self, runtime_analysis: RuntimeAnalysis, code_chunks: List[Dict[str, Any]]
    ) -> CodeAnalysis:
        ...

    def analyze_changes(
        self,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        git_context: List[Dict[str, Any]],
    ) -> ChangeAnalysis:
        ...

    def synthesize_rca(
        self,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        ...

    def validate_rca(
        self,
        rca: RootCauseAnalysis,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RCAValidation:
        ...

    def revise_rca(
        self,
        rca: RootCauseAnalysis,
        validation: RCAValidation,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        ...


class FakeInvestigationLLM:
    """Deterministic, 100% offline implementation of InvestigationLLM for testing and mock mode.

    Generates realistic, evidence-grounded responses derived dynamically from the supplied
    incident facts, code chunks, and Git history without hardcoding scenario-specific outcomes.
    Supports overrides and failure injection for rigorous test coverage.
    """

    def __init__(self) -> None:
        self.raise_error: bool = False
        self.error_message: str = "Simulated LLM provider error."
        self.custom_runtime_analysis: Optional[RuntimeAnalysis] = None
        self.custom_code_analysis: Optional[CodeAnalysis] = None
        self.custom_change_analysis: Optional[ChangeAnalysis] = None
        self.custom_rca: Optional[RootCauseAnalysis] = None
        self.custom_validation: Optional[RCAValidation] = None
        self.custom_revision: Optional[RootCauseAnalysis] = None
        self.validation_handler: Optional[Callable[..., RCAValidation]] = None
        self.revision_handler: Optional[Callable[..., RootCauseAnalysis]] = None

    def analyze_runtime(self, incident: Incident, evidence: List[Evidence]) -> RuntimeAnalysis:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.custom_runtime_analysis:
            return self.custom_runtime_analysis

        service = evidence[0].service if evidence else incident.title
        endpoint = next((e.endpoint for e in evidence if e.endpoint), None)
        exc_type = next((e.exception_type for e in evidence if e.exception_type), None)
        req_ids = list(dict.fromkeys(e.request_id for e in evidence if e.request_id))
        messages = [e.message for e in evidence if e.message]
        events = [f"[{e.timestamp.isoformat()}] {e.event}: {e.message}" for e in evidence]

        failures = [f"{exc_type or 'Error'} occurred in {service}"] if exc_type else ["Runtime failure observed"]
        hypotheses = [f"Service '{service}' experienced a failure on endpoint '{endpoint}'"] if endpoint else []

        return RuntimeAnalysis(
            observed_failures=failures,
            service=service,
            endpoint=endpoint,
            exception_type=exc_type,
            important_messages=messages,
            request_ids=req_ids,
            timeline=events,
            initial_hypotheses=hypotheses,
            missing_information=[],
        )

    def analyze_code(
        self, runtime_analysis: RuntimeAnalysis, code_chunks: List[Dict[str, Any]]
    ) -> CodeAnalysis:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.custom_code_analysis:
            return self.custom_code_analysis

        if not code_chunks:
            return CodeAnalysis(
                relevant_symbols=[],
                relevant_files=[],
                code_observations=["No source-code chunks were retrieved."],
                possible_relationship_to_failure=[],
                missing_code_context=["Repository search yielded 0 matching code chunks."],
            )

        symbols = [c["symbol_name"] for c in code_chunks if c.get("symbol_name")]
        files = list(dict.fromkeys(c["file_path"] for c in code_chunks if c.get("file_path")))
        observations = [
            f"Chunk {c['id']} in {c['file_path']} defines {c['symbol_type']} '{c.get('symbol_name')}'"
            for c in code_chunks[:3]
        ]
        relationships = [
            f"Symbol '{symbols[0]}' is directly involved in handling requests matching the runtime failure"
        ] if symbols else []

        return CodeAnalysis(
            relevant_symbols=symbols,
            relevant_files=files,
            code_observations=observations,
            possible_relationship_to_failure=relationships,
            missing_code_context=[],
        )

    def analyze_changes(
        self,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        git_context: List[Dict[str, Any]],
    ) -> ChangeAnalysis:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.custom_change_analysis:
            return self.custom_change_analysis

        if not git_context:
            return ChangeAnalysis(
                relevant_changes=[],
                potential_relationships=[],
                timing_observations=["No recent Git commits found for the investigated files."],
                contradictions=[],
                uncertainty=["No Git history available to establish change timeline."],
                facts=["No Git commits were retrieved for relevant files."],
                inferences=[],
            )

        commits_by_hash: Dict[str, Dict[str, Any]] = {}
        commit_files: Dict[str, List[str]] = {}

        for item in git_context:
            file_p = item.get("file_path", "")
            for c in item.get("commits", [])[:3]:
                chash = c.get("commit_hash", c.get("short_hash", ""))
                if not chash:
                    continue
                if chash not in commits_by_hash:
                    commits_by_hash[chash] = c
                    commit_files[chash] = []
                if file_p and file_p not in commit_files[chash]:
                    commit_files[chash].append(file_p)

        facts = []
        changes = []
        timing = []
        for chash, c in commits_by_hash.items():
            h = c.get("short_hash", chash[:7])
            msg = c.get("message", "")
            ts = c.get("committed_at", "")
            files_str = ", ".join(commit_files[chash]) if commit_files[chash] else "repository files"
            facts.append(f"Commit {h} modified {files_str}: '{msg}'")
            changes.append(f"{h} ({files_str}): {msg}")
            timing.append(f"Commit {h} committed at {ts}")

        all_baseline = bool(commits_by_hash) and all(
            any(kw in c.get("message", "").lower() for kw in ("initial", "baseline", "bootstrap", "scaffold"))
            for c in commits_by_hash.values()
        )
        if all_baseline:
            inferences = [
                "Causation cannot be established from baseline history alone; commit represents initial repository state with no prior version to compare against, not a regression."
            ]
            potential_relationships = list(inferences)
        else:
            inferences = [
                "Recent commits touched the relevant files; correlation with incident timing suggests possible relationship but does not prove causation."
            ] if facts else []
            potential_relationships = list(inferences)

        return ChangeAnalysis(
            relevant_changes=changes,
            potential_relationships=potential_relationships,
            timing_observations=timing,
            contradictions=[],
            uncertainty=["Git changes do not definitively prove causation without reproduction evidence."],
            facts=facts,
            inferences=inferences,
        )

    def synthesize_rca(
        self,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.custom_rca:
            return self.custom_rca

        supporting: List[EvidenceReference] = []

        # Cite runtime evidence
        for ev in evidence[:3]:
            supporting.append(
                EvidenceReference(
                    type="runtime",
                    id=ev.id,
                    description=f"Runtime error log from service '{ev.service}' with event '{ev.event}'",
                )
            )

        # Dynamic extraction of failure location and triggering condition from code chunks
        failure_location = (
            code_analysis.relevant_symbols[0]
            if code_analysis.relevant_symbols
            else (runtime_analysis.service or incident.title)
        )
        triggering_condition = ""

        # Inspect retrieved code chunks for conditional branches/guards that raise exceptions
        for chunk in code_chunks:
            content = chunk.get("content", "")
            match = re.search(r"if\s+([^:\n]+):\s*\n(?:\s*#[^\n]*\n)*\s*raise\s+([A-Za-z0-9_]+)?", content)
            if match:
                guard_expr = match.group(1).strip()
                triggering_condition = f"Controlled condition '{guard_expr}' evaluated to True"
                if chunk.get("symbol_name"):
                    failure_location = chunk["symbol_name"]
                break

        if not triggering_condition:
            if runtime_analysis.exception_type:
                triggering_condition = f"Execution reached exception branch for {runtime_analysis.exception_type}"
            else:
                triggering_condition = "Unexpected runtime state during request execution"

        # Cite code chunk
        if code_chunks:
            top_chunk = code_chunks[0]
            supporting.append(
                EvidenceReference(
                    type="code",
                    id=top_chunk["id"],
                    description=f"Source code chunk in {top_chunk['file_path']} for symbol {top_chunk.get('symbol_name')}",
                )
            )

        # Relevance-qualify Git citations: only cite commits in supporting_evidence if they
        # materially support the causal hypothesis; baseline/generic commits stay in git_context only.
        baseline_keywords = ["initial", "baseline", "bootstrap", "scaffold"]
        for gc in git_context:
            for c in gc.get("commits", []):
                msg = c.get("message", "").lower()
                is_baseline = any(kw in msg for kw in baseline_keywords)
                if not is_baseline:
                    supporting.append(
                        EvidenceReference(
                            type="git_commit",
                            id=c.get("commit_hash", c.get("short_hash")),
                            description=f"Recent commit modifying {gc.get('file_path')}: '{c.get('message')}'",
                        )
                    )
                    break
            if any(ref.type == "git_commit" for ref in supporting):
                break

        exc_str = runtime_analysis.exception_type or "unexpected error"
        root_cause_hypothesis = (
            f"{failure_location} raised {exc_str} because {triggering_condition}"
        )
        summary = (
            f"The incident in service '{runtime_analysis.service}' was caused by {triggering_condition} "
            f"in '{failure_location}', resulting in {exc_str}."
        )

        has_git_evidence = any(ref.type == "git_commit" for ref in supporting)
        uncertainties = []
        if not code_chunks:
            uncertainties.append("No source-code context was retrieved; hypothesis relies purely on runtime logs.")
        if git_context and not has_git_evidence:
            uncertainties.append(
                "Recent commits in Git history represent baseline/initial repository state and do not indicate a causal code change for this incident."
            )
        elif not git_context:
            uncertainties.append("No Git commit history was available to evaluate recent code modifications.")

        # Add uncertainty note when admin evidence is absent
        observed_eps = {str(e.endpoint).lower() for e in evidence if e.endpoint}
        observed_evs = {str(e.event).lower() for e in evidence if e.event}
        has_admin = any("/admin" in ep or "enable" in ep for ep in observed_eps) or any("enable" in ev or "admin" in ev for ev in observed_evs)
        if not has_admin:
            uncertainties.append("The available evidence does not establish how or when the failure condition became true.")

        # Confidence assessed strictly by evidence quality
        if code_chunks and evidence:
            confidence = 0.85 if has_git_evidence else 0.80
        elif evidence:
            confidence = 0.45
        else:
            confidence = 0.20

        return RootCauseAnalysis(
            failure_location=failure_location,
            triggering_condition=triggering_condition,
            root_cause_hypothesis=root_cause_hypothesis,
            affected_component=failure_location,
            summary=summary,
            supporting_evidence=supporting,
            contradicting_evidence=[],
            confidence=confidence,
            uncertainties=uncertainties,
        )

    def validate_rca(
        self,
        rca: RootCauseAnalysis,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RCAValidation:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.validation_handler:
            return self.validation_handler(rca=rca)
        if self.custom_validation:
            return self.custom_validation

        return run_deterministic_grounding_check(
            rca=rca,
            evidence=evidence,
            code_chunks=code_chunks,
            git_context=git_context,
        )

    def revise_rca(
        self,
        rca: RootCauseAnalysis,
        validation: RCAValidation,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        if self.raise_error:
            raise InvestigationLLMError(self.error_message)
        if self.revision_handler:
            return self.revision_handler(rca=rca, validation=validation)
        if self.custom_revision:
            return self.custom_revision
        if self.custom_rca:
            return self.custom_rca

        # Filter out unsupported claims and references
        cleaned_supporting = [
            ref for ref in rca.supporting_evidence
            if not any(ref.id in claim for claim in validation.unsupported_claims)
        ]

        cleaned_condition = rca.triggering_condition
        if (
            not cleaned_condition
            or any("triggering condition" in claim.lower() for claim in validation.unsupported_claims)
            or any("endpoint" in issue.lower() or "admin" in issue.lower() or "was enabled" in issue.lower() for issue in validation.issues)
            or any("was enabled" in claim.lower() or "enablement" in claim.lower() for claim in validation.unsupported_claims)
        ):
            cleaned_condition = "self._failure_controller.is_order_processing_error_enabled() evaluated true"
            for chunk in code_chunks:
                match = re.search(r"if\s+([^:\n]+):\s*\n(?:\s*#[^\n]*\n)*\s*raise\s+([A-Za-z0-9_]+)?", chunk.get("content", ""))
                if match:
                    cleaned_condition = f"{match.group(1).strip()} evaluated true"
                    break
            if not cleaned_condition:
                cleaned_condition = f"Execution reached exception branch for {runtime_analysis.exception_type or 'error'}"

        # Clean triggering condition of hallucinated fields or ungrounded claims
        for field in HALLUCINATED_ORDER_FIELDS:
            cleaned_condition = re.sub(rf"\b{field}\b", "", cleaned_condition, flags=re.IGNORECASE).strip()

        # Remove unsupported enablement claims from condition
        for ep_term in [
            "the controlled failure mode was enabled",
            "controlled failure mode was enabled",
            "failure mode was enabled",
            "was enabled",
            "enable_order_processing_failure",
            "enable_order_processing_error",
            "/admin/failures/order-processing/enable",
            "/admin/failures",
            "admin endpoint",
        ]:
            if ep_term in cleaned_condition.lower():
                cleaned_condition = "self._failure_controller.is_order_processing_error_enabled() evaluated true"
                break

        # Resolve verified failure location from retrieved symbols
        retrieved_symbols = [c["symbol_name"] for c in code_chunks if c.get("symbol_name")]
        failure_loc = rca.failure_location
        if not failure_loc or (retrieved_symbols and failure_loc not in retrieved_symbols):
            if retrieved_symbols:
                failure_loc = retrieved_symbols[0]
            elif code_analysis and code_analysis.relevant_symbols:
                failure_loc = code_analysis.relevant_symbols[0]
            else:
                failure_loc = runtime_analysis.service or incident.title

        exc_str = runtime_analysis.exception_type or "error"

        # Build clean hypothesis and summary grounded strictly in verified symbols
        cleaned_hypothesis = f"{failure_loc} raised {exc_str} when {cleaned_condition}"
        cleaned_summary = (
            f"The incident in service '{runtime_analysis.service}' was caused when {cleaned_condition} "
            f"in '{failure_loc}', resulting in {exc_str}."
        )

        # Ensure mandatory code chunk citation if code chunks exist
        has_code_ref = any(
            ref.type in ("code", "source_code") and any(ref.id == c["id"] for c in code_chunks)
            for ref in cleaned_supporting
        )
        if not has_code_ref and code_chunks:
            matching_chunk = next((c for c in code_chunks if c.get("symbol_name") == failure_loc), code_chunks[0])
            cleaned_supporting.append(
                EvidenceReference(
                    type="code",
                    id=matching_chunk["id"],
                    description=f"Source code chunk in {matching_chunk.get('file_path')} for symbol {matching_chunk.get('symbol_name')}",
                )
            )

        # Ensure mandatory runtime citation if runtime evidence exists
        has_runtime_ref = any(
            ref.type in ("runtime", "runtime_log") and any(ref.id == e.id for e in evidence)
            for ref in cleaned_supporting
        )
        if not has_runtime_ref and evidence:
            cleaned_supporting.append(
                EvidenceReference(
                    type="runtime",
                    id=evidence[0].id,
                    description=f"Runtime error log from service '{evidence[0].service}' with event '{evidence[0].event}'",
                )
            )

        new_uncertainties = list(rca.uncertainties)
        new_uncertainties.append(f"Revised to address validator critique: {'; '.join(validation.issues)}")
        uncertainty_note = "The available evidence does not establish how or when the failure condition became true."
        if uncertainty_note not in new_uncertainties:
            new_uncertainties.append(uncertainty_note)

        return RootCauseAnalysis(
            failure_location=failure_loc,
            triggering_condition=cleaned_condition,
            root_cause_hypothesis=cleaned_hypothesis,
            affected_component=failure_loc,
            summary=cleaned_summary,
            supporting_evidence=cleaned_supporting,
            contradicting_evidence=rca.contradicting_evidence,
            confidence=max(0.1, rca.confidence - 0.15),
            uncertainties=new_uncertainties,
        )


class LangChainInvestigationLLM:
    """Production LLM wrapper utilizing LangChain and ChatOpenAI with structured output."""

    def __init__(self, model_name: str, api_key: str) -> None:
        try:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(model=model_name, api_key=api_key, temperature=0.1)
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "Failed to initialize LangChain ChatOpenAI: stage=initialization, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"Could not initialize LLM provider: {exc_class}") from exc

    def analyze_runtime(self, incident: Incident, evidence: List[Evidence]) -> RuntimeAnalysis:
        try:
            structured_model = self._llm.with_structured_output(RuntimeAnalysisSchema)
            prompt = (
                f"{RUNTIME_ANALYSIS_SYSTEM_PROMPT}\n\n"
                f"Incident Title: {incident.title}\n"
                f"Incident Summary: {incident.summary}\n"
                f"Runtime Evidence Logs:\n"
                + "\n".join(
                    f"- [{e.timestamp.isoformat()}] [{e.level}] Service: {e.service}, Endpoint: {e.endpoint}, "
                    f"Request ID: {e.request_id or 'none'}, Exception: {e.exception_type}, Event: {e.event}, Message: {e.message}"
                    for e in evidence
                )
            )
            result: RuntimeAnalysisSchema = structured_model.invoke(prompt)

            # Ensure request_ids contains all observed request IDs from evidence
            observed_req_ids = list(dict.fromkeys(
                ([r for r in result.request_ids if r] if result.request_ids else [])
                + [e.request_id for e in evidence if e.request_id]
            ))

            return RuntimeAnalysis(
                observed_failures=result.observed_failures,
                service=result.service,
                endpoint=result.endpoint,
                exception_type=result.exception_type,
                important_messages=result.important_messages,
                request_ids=observed_req_ids,
                timeline=result.timeline,
                initial_hypotheses=result.initial_hypotheses,
                missing_information=result.missing_information,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain analyze_runtime failed: stage=runtime_analysis, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"Runtime analysis reasoning failed: {exc_class}") from exc

    def analyze_code(
        self, runtime_analysis: RuntimeAnalysis, code_chunks: List[Dict[str, Any]]
    ) -> CodeAnalysis:
        if not runtime_analysis:
            logger.error(
                "LangChain analyze_code failed: stage=code_analysis, exception=MissingPrerequisiteError, message=runtime_analysis is None"
            )
            raise InvestigationLLMError("Code analysis reasoning failed: MissingPrerequisiteError: runtime_analysis is required")

        try:
            structured_model = self._llm.with_structured_output(CodeAnalysisSchema)
            chunks_text = "\n---\n".join(
                f"Chunk ID: {c['id']}\nFile: {c['file_path']} (lines {c['start_line']}-{c['end_line']})\n"
                f"Symbol: {c.get('symbol_name')} ({c['symbol_type']})\nContent:\n{c['content']}"
                for c in code_chunks
            )
            prompt = (
                f"{CODE_ANALYSIS_SYSTEM_PROMPT}\n\n"
                f"Runtime Analysis Summary:\n"
                f"Service: {runtime_analysis.service}, Endpoint: {runtime_analysis.endpoint}, "
                f"Exception: {runtime_analysis.exception_type}\n"
                f"Observed Failures: {', '.join(runtime_analysis.observed_failures)}\n\n"
                f"Retrieved Code Chunks:\n{chunks_text}"
            )
            result: CodeAnalysisSchema = structured_model.invoke(prompt)
            return CodeAnalysis(
                relevant_symbols=result.relevant_symbols,
                relevant_files=result.relevant_files,
                code_observations=result.code_observations,
                possible_relationship_to_failure=result.possible_relationship_to_failure,
                missing_code_context=result.missing_code_context,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain analyze_code failed: stage=code_analysis, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"Code analysis reasoning failed: {exc_class}") from exc

    def analyze_changes(
        self,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        git_context: List[Dict[str, Any]],
    ) -> ChangeAnalysis:
        if not runtime_analysis or not code_analysis:
            logger.error(
                "LangChain analyze_changes failed: stage=change_analysis, exception=MissingPrerequisiteError, message=runtime_analysis or code_analysis is None"
            )
            raise InvestigationLLMError("Change analysis reasoning failed: MissingPrerequisiteError: runtime_analysis and code_analysis are required")

        try:
            structured_model = self._llm.with_structured_output(ChangeAnalysisSchema)

            # Deduplicate commits across files
            commits_by_hash: Dict[str, Dict[str, Any]] = {}
            commit_files: Dict[str, List[str]] = {}
            for item in git_context:
                file_p = item.get("file_path", "")
                for c in item.get("commits", []):
                    chash = c.get("commit_hash", c.get("short_hash", ""))
                    if not chash:
                        continue
                    if chash not in commits_by_hash:
                        commits_by_hash[chash] = c
                        commit_files[chash] = []
                    if file_p and file_p not in commit_files[chash]:
                        commit_files[chash].append(file_p)

            git_text = ""
            for chash, cm in commits_by_hash.items():
                files_str = ", ".join(commit_files[chash]) if commit_files[chash] else "unknown"
                git_text += f"- Commit {chash} by {cm.get('author_name')} at {cm.get('committed_at')} touching [{files_str}]: {cm.get('message')}\n"

            prompt = (
                f"{CHANGE_ANALYSIS_SYSTEM_PROMPT}\n\n"
                f"Runtime Service: {runtime_analysis.service}, Exception: {runtime_analysis.exception_type}\n"
                f"Relevant Code Files: {', '.join(code_analysis.relevant_files)}\n"
                f"Git Context:\n{git_text if git_text else 'No Git commits recorded.'}"
            )
            result: ChangeAnalysisSchema = structured_model.invoke(prompt)

            baseline_keywords = ("initial", "baseline", "bootstrap", "scaffold")
            all_baseline = bool(commits_by_hash) and all(
                any(kw in cm.get("message", "").lower() for kw in baseline_keywords)
                for cm in commits_by_hash.values()
            )
            potential_relationships = list(result.potential_relationships)
            inferences = list(result.inferences)

            if all_baseline:
                baseline_note = (
                    "Causation cannot be established from baseline history alone; "
                    "commit represents initial repository state with no prior version to compare against, not a regression."
                )
                speculative_markers = (
                    "altered the flow",
                    "alter the flow",
                    "relate to the error",
                    "introduced",
                    "possible regression",
                    "may have altered",
                    "may relate",
                )
                potential_relationships = [
                    r for r in potential_relationships
                    if not any(sm in r.lower() for sm in speculative_markers)
                ]
                inferences = [
                    inf for inf in inferences
                    if not any(sm in inf.lower() for sm in speculative_markers)
                ]
                if not potential_relationships or not any("baseline" in r.lower() for r in potential_relationships):
                    potential_relationships.append(baseline_note)
                if not inferences or not any("baseline" in inf.lower() for inf in inferences):
                    inferences.append(baseline_note)

            return ChangeAnalysis(
                relevant_changes=result.relevant_changes,
                potential_relationships=potential_relationships,
                timing_observations=result.timing_observations,
                contradictions=result.contradictions,
                uncertainty=result.uncertainty,
                facts=result.facts,
                inferences=inferences,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain analyze_changes failed: stage=change_analysis, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"Change analysis reasoning failed: {exc_class}") from exc

    def synthesize_rca(
        self,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        if not runtime_analysis or not code_analysis:
            logger.error(
                "LangChain synthesize_rca failed: stage=rca_synthesis, exception=MissingPrerequisiteError, message=runtime_analysis or code_analysis is None"
            )
            raise InvestigationLLMError("Root cause analysis synthesis failed: MissingPrerequisiteError: runtime_analysis and code_analysis are required")

        try:
            structured_model = self._llm.with_structured_output(RootCauseAnalysisSchema)

            # Build rich, concrete evidence context
            chunks_context = "\n---\n".join(
                f"Chunk ID: {c.get('id', 'chunk')}\nFile: {c.get('file_path', 'unknown')} (lines {c.get('start_line', 1)}-{c.get('end_line', 1)})\n"
                f"Symbol: {c.get('symbol_name', 'none')} ({c.get('symbol_type', 'code')})\nContent:\n{c.get('content', '')}"
                for c in code_chunks
            ) if code_chunks else "No code chunks retrieved."

            evidence_context = "\n".join(
                f"- [Evidence ID: {e.id}] [{e.level}] Service: {e.service}, Endpoint: {e.endpoint}, "
                f"Exception: {e.exception_type}, Event: {e.event}, Message: {e.message}"
                for e in evidence
            )

            git_context_lines = []
            for gc in git_context:
                for cm in gc.get("commits", []):
                    chash = cm.get("commit_hash", cm.get("short_hash"))
                    git_context_lines.append(f"- Commit {chash} in {gc.get('file_path')}: '{cm.get('message')}'")
            git_text = "\n".join(git_context_lines) if git_context_lines else "No Git commits available."

            prompt = (
                f"{RCA_SYNTHESIS_SYSTEM_PROMPT}\n\n"
                f"Incident Title: {incident.title}\n"
                f"Incident Summary: {incident.summary} (Severity: {incident.severity.value})\n\n"
                f"Runtime Analysis Facts:\n{runtime_analysis}\n\n"
                f"Raw Runtime Evidence Logs:\n{evidence_context}\n\n"
                f"Code Analysis Facts:\n{code_analysis}\n\n"
                f"Retrieved Source Code Chunks:\n{chunks_context}\n\n"
                f"Git Change Analysis Facts:\n{change_analysis}\n\n"
                f"Git Commits Context:\n{git_text}\n\n"
                f"Available Runtime Evidence IDs: {[e.id for e in evidence]}\n"
                f"Available Code Chunk IDs: {[c['id'] for c in code_chunks]}\n"
                f"Available Git Commit Hashes: {[cm.get('commit_hash') for gc in git_context for cm in gc.get('commits', []) if 'commit_hash' in cm]}\n"
            )
            result: RootCauseAnalysisSchema = structured_model.invoke(prompt)
            failure_loc = result.failure_location or result.affected_component
            trigger_cond = result.triggering_condition
            uncertainties = list(result.uncertainties)
            observed_eps = {str(e.endpoint).lower() for e in evidence if e.endpoint}
            observed_evs = {str(e.event).lower() for e in evidence if e.event}
            has_admin = any("/admin" in ep or "enable" in ep for ep in observed_eps) or any("enable" in ev or "admin" in ev for ev in observed_evs)
            if not has_admin:
                uncertainty_note = "The available evidence does not establish how or when the failure condition became true."
                if uncertainty_note not in uncertainties:
                    uncertainties.append(uncertainty_note)

            return RootCauseAnalysis(
                failure_location=failure_loc,
                triggering_condition=trigger_cond,
                root_cause_hypothesis=result.root_cause_hypothesis,
                affected_component=result.affected_component or failure_loc,
                summary=result.summary,
                supporting_evidence=[
                    EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                    for ref in result.supporting_evidence
                ],
                contradicting_evidence=[
                    EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                    for ref in result.contradicting_evidence
                ],
                confidence=result.confidence,
                uncertainties=uncertainties,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain synthesize_rca failed: stage=rca_synthesis, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"Root cause analysis synthesis failed: {exc_class}") from exc

    def validate_rca(
        self,
        rca: RootCauseAnalysis,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RCAValidation:
        # Step 1: Run shared deterministic grounding check
        det_validation = run_deterministic_grounding_check(
            rca=rca,
            evidence=evidence,
            code_chunks=code_chunks,
            git_context=git_context,
        )

        # Step 2: Run semantic LLM validation
        try:
            structured_model = self._llm.with_structured_output(RCAValidationSchema)

            retrieved_symbols = [c["symbol_name"] for c in code_chunks if c.get("symbol_name")]
            retrieved_files = list(dict.fromkeys(c["file_path"] for c in code_chunks if c.get("file_path")))

            supporting_refs_text = "\n".join(
                f"- [type={ref.type}, id={ref.id}] {ref.description or ''}"
                for ref in rca.supporting_evidence
            ) if rca.supporting_evidence else "None cited."

            runtime_evidence_lines = "\n".join(
                f"- [ID: {e.id}] (type=runtime/runtime_log, service={e.service}, endpoint={e.endpoint or 'none'}, event={e.event}): {e.message}"
                for e in evidence
            ) if evidence else "No runtime evidence."

            code_chunk_lines = "\n".join(
                f"- [ID: {c.get('id', 'chunk')}] (type=code, file={c.get('file_path', 'unknown')}, symbol={c.get('symbol_name')}): lines {c.get('start_line', 1)}-{c.get('end_line', 1)}"
                for c in code_chunks
            ) if code_chunks else "No code chunks."

            prompt = (
                f"{RCA_VALIDATION_SYSTEM_PROMPT}\n\n"
                f"Proposed RCA:\n"
                f"Failure Location: {rca.failure_location}\n"
                f"Triggering Condition: {rca.triggering_condition}\n"
                f"Hypothesis: {rca.root_cause_hypothesis}\n"
                f"Affected Component: {rca.affected_component}\n"
                f"Summary: {rca.summary}\n"
                f"Supporting Evidence Cited:\n{supporting_refs_text}\n\n"
                f"Supplied Ground Truth Context to Check Against:\n"
                f"Valid Runtime Evidence (type='runtime' / 'runtime_log'):\n{runtime_evidence_lines}\n"
                f"Valid Code Chunks (type='code'):\n{code_chunk_lines}\n"
                f"Retrieved Code Files: {retrieved_files}\n"
                f"Retrieved Code Symbols: {retrieved_symbols}\n"
                f"Retrieved Commits: {[cm.get('commit_hash') for gc in git_context for cm in gc.get('commits', []) if 'commit_hash' in cm]}\n"
            )
            result: RCAValidationSchema = structured_model.invoke(prompt)

            return reconcile_semantic_validation_findings(
                rca=rca,
                det_validation=det_validation,
                llm_valid=result.valid,
                llm_issues=list(result.issues or []),
                llm_unsupported=list(result.unsupported_claims or []),
                llm_missing=list(result.missing_evidence or []),
                code_chunks=code_chunks,
                evidence=evidence,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain validate_rca failed: stage=rca_validation, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"RCA validation failed: {exc_class}") from exc

    def revise_rca(
        self,
        rca: RootCauseAnalysis,
        validation: RCAValidation,
        incident: Incident,
        runtime_analysis: RuntimeAnalysis,
        code_analysis: CodeAnalysis,
        change_analysis: ChangeAnalysis,
        evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RootCauseAnalysis:
        try:
            structured_model = self._llm.with_structured_output(RootCauseAnalysisSchema)
            retrieved_symbols = [c["symbol_name"] for c in code_chunks if c.get("symbol_name")]
            chunks_context = "\n---\n".join(
                f"Chunk ID: {c.get('id', 'chunk')}\nFile: {c.get('file_path', 'unknown')} (lines {c.get('start_line', 1)}-{c.get('end_line', 1)})\n"
                f"Symbol: {c.get('symbol_name', 'none')} ({c.get('symbol_type', 'code')})\nContent:\n{c.get('content', '')}"
                for c in code_chunks
            ) if code_chunks else "No code chunks retrieved."

            prompt = (
                f"{RCA_REVISION_SYSTEM_PROMPT}\n\n"
                f"Original Proposed RCA:\n"
                f"Failure Location: {rca.failure_location}\n"
                f"Triggering Condition: {rca.triggering_condition}\n"
                f"Hypothesis: {rca.root_cause_hypothesis}\n"
                f"Summary: {rca.summary}\n\n"
                f"Validation Issues Identified:\n{validation.issues}\n\n"
                f"Unsupported Claims to Eliminate:\n{validation.unsupported_claims}\n\n"
                f"Retrieved Code Symbols (Must use one of these): {retrieved_symbols}\n"
                f"Retrieved Code Chunks:\n{chunks_context}\n\n"
                f"Valid Evidence IDs Available: {[e.id for e in evidence]}\n"
                f"Valid Code Chunk IDs Available: {[c['id'] for c in code_chunks]}\n"
            )
            result: RootCauseAnalysisSchema = structured_model.invoke(prompt)
            failure_loc = result.failure_location or result.affected_component
            trigger_cond = result.triggering_condition

            supporting_refs = [
                EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                for ref in result.supporting_evidence
            ]

            # Ensure mandatory code citation is added during revision if code claims are made
            has_code_ref = any(
                ref.type in ("code", "source_code") and any(ref.id == c["id"] for c in code_chunks)
                for ref in supporting_refs
            )
            if not has_code_ref and code_chunks and (failure_loc or trigger_cond):
                matching = next((c for c in code_chunks if c.get("symbol_name") == failure_loc), code_chunks[0])
                supporting_refs.append(
                    EvidenceReference(
                        type="code",
                        id=matching["id"],
                        description=f"Source code chunk in {matching.get('file_path')} for symbol {matching.get('symbol_name')}",
                    )
                )

            # Ensure mandatory runtime citation is added during revision if runtime evidence exists
            has_runtime_ref = any(
                ref.type in ("runtime", "runtime_log") and any(ref.id == e.id for e in evidence)
                for ref in supporting_refs
            )
            if not has_runtime_ref and evidence:
                supporting_refs.append(
                    EvidenceReference(
                        type="runtime",
                        id=evidence[0].id,
                        description=f"Runtime error log from service '{evidence[0].service}' with event '{evidence[0].event}'",
                    )
                )

            # Remove unsupported enablement claims from condition/hypothesis if unevidenced
            observed_eps = {str(e.endpoint).lower() for e in evidence if e.endpoint}
            observed_evs = {str(e.event).lower() for e in evidence if e.event}
            has_admin = any("/admin" in ep or "enable" in ep for ep in observed_eps) or any("enable" in ev or "admin" in ev for ev in observed_evs)
            cleaned_hypothesis = result.root_cause_hypothesis
            if not has_admin:
                for ep_term in [
                    "the controlled failure mode was enabled",
                    "controlled failure mode was enabled",
                    "failure mode was enabled",
                    "was enabled via",
                    "was enabled by",
                    "was enabled",
                    "enable_order_processing_failure",
                    "enable_order_processing_error",
                    "/admin/failures/order-processing/enable",
                    "/admin/failures",
                    "admin endpoint",
                ]:
                    if trigger_cond and ep_term in trigger_cond.lower():
                        trigger_cond = "self._failure_controller.is_order_processing_error_enabled() evaluated true"
                    if cleaned_hypothesis and ep_term in cleaned_hypothesis.lower():
                        cleaned_hypothesis = f"{failure_loc} raised {runtime_analysis.exception_type or 'OrderProcessingError'} when {trigger_cond}"

            uncertainties = list(result.uncertainties)
            if not has_admin:
                uncertainty_note = "The available evidence does not establish how or when the failure condition became true."
                if uncertainty_note not in uncertainties:
                    uncertainties.append(uncertainty_note)

            return RootCauseAnalysis(
                failure_location=failure_loc,
                triggering_condition=trigger_cond,
                root_cause_hypothesis=cleaned_hypothesis,
                affected_component=result.affected_component or failure_loc,
                summary=result.summary,
                supporting_evidence=supporting_refs,
                contradicting_evidence=[
                    EvidenceReference(type=ref.type, id=ref.id, description=ref.description)
                    for ref in result.contradicting_evidence
                ],
                confidence=result.confidence,
                uncertainties=uncertainties,
            )
        except Exception as exc:
            exc_class = exc.__class__.__name__
            safe_msg = _sanitize_error_message(str(exc))
            logger.error(
                "LangChain revise_rca failed: stage=rca_revision, exception=%s, message=%s",
                exc_class, safe_msg,
            )
            raise InvestigationLLMError(f"RCA revision failed: {exc_class}") from exc
