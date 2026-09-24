"""LangGraph incident investigation workflow orchestrator."""

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from app.agents.llm import InvestigationLLM
from app.agents.models import RCAValidation
from app.common.config import config
from app.memory.models import HistoricalSearchQuery
from app.memory.service import IncidentMemoryService
from app.repository.service import GitService
from app.retrieval.index import RepositoryNotIndexedError
from app.retrieval.service import RetrievalService
from app.workflows.investigation_state import InvestigationState

logger = logging.getLogger(__name__)


def synthesize_rca_node(state: InvestigationState, llm: InvestigationLLM) -> Dict[str, Any]:
    """Synthesizes Root Cause Analysis, enforcing preconditions on required upstream reasoning."""
    logger.info("Executing synthesize_rca node")
    ra = state.get("runtime_analysis")
    ca = state.get("code_analysis")

    # Defensive precondition: require both runtime_analysis and code_analysis
    if ra is None or ca is None:
        missing = []
        if ra is None:
            missing.append("runtime_analysis")
        if ca is None:
            missing.append("code_analysis")
        err_msg = f"RCA synthesis aborted: required upstream reasoning missing ({', '.join(missing)})."
        logger.error(err_msg)
        return {
            "rca": None,
            "errors": state.get("errors", []) + [err_msg],
        }

    try:
        rca = llm.synthesize_rca(
            incident=state["incident"],
            runtime_analysis=ra,
            code_analysis=ca,
            change_analysis=state.get("change_analysis"),
            evidence=state["runtime_evidence"],
            code_chunks=state.get("code_results", []),
            git_context=state.get("git_context", []),
            historical_context=state.get("historical_context", []),
        )
        return {"rca": rca}
    except Exception as exc:
        logger.error("synthesize_rca failed: %s", exc)
        return {
            "rca": None,
            "errors": state.get("errors", []) + [f"RCA synthesis failed: {exc}"],
        }


def build_investigation_graph(
    llm: InvestigationLLM,
    retrieval_service: RetrievalService,
    git_service: GitService,
    git_limit: int = 3,
    max_revisions: int = 1,
    memory_service: Optional[IncidentMemoryService] = None,
) -> StateGraph:
    """Constructs and compiles the multi-node LangGraph investigation workflow."""

    def analyze_runtime_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing analyze_runtime node for incident %s", state["incident"].id)
        try:
            analysis = llm.analyze_runtime(state["incident"], state["runtime_evidence"])
            return {"runtime_analysis": analysis}
        except Exception as exc:
            logger.error("analyze_runtime failed: %s", exc)
            return {
                "runtime_analysis": None,
                "errors": state.get("errors", []) + [f"Runtime analysis failed: {exc}"],
            }

    def route_after_runtime(state: InvestigationState) -> str:
        if state.get("runtime_analysis") is not None:
            return "continue"
        logger.warning("Halting investigation: required runtime analysis failed.")
        return "end"

    def retrieve_code_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing retrieve_code node")
        ra = state.get("runtime_analysis")
        query_parts: List[str] = []

        if ra and ra.exception_type:
            query_parts.append(ra.exception_type)

        # Extract normalized event phrases from runtime evidence
        for ev in state.get("runtime_evidence", []):
            if ev.event:
                clean_ev = ev.event.replace("_", " ").replace(".", " ").replace("-", " ")
                clean_ev = re.sub(r"\s+", " ", clean_ev).strip()
                if clean_ev and clean_ev not in query_parts:
                    query_parts.append(clean_ev)
                    break

        query = " ".join(query_parts).strip()
        if not query:
            query = state["incident"].title

        code_results: List[Dict[str, Any]] = []
        errors = list(state.get("errors", []))

        try:
            search_response = retrieval_service.search(query=query, limit=5)
            for item in search_response.results:
                code_results.append({
                    "id": item.id,
                    "file_path": item.file_path,
                    "symbol_name": item.symbol_name,
                    "symbol_type": item.symbol_type,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "content": item.content,
                    "score": item.score,
                })
        except RepositoryNotIndexedError:
            logger.warning("Repository index has not been built yet during code retrieval.")
            errors.append("Code repository index is empty or not yet built.")
        except Exception as exc:
            logger.warning("Code retrieval search failed: %s", exc)
            errors.append(f"Code retrieval failed: {exc}")

        return {"code_query": query, "code_results": code_results, "errors": errors}

    def analyze_code_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing analyze_code node")
        ra = state.get("runtime_analysis")
        chunks = state.get("code_results", [])
        if ra is None:
            logger.error("analyze_code skipped: runtime_analysis is missing.")
            return {
                "code_analysis": None,
                "errors": state.get("errors", []) + ["Code analysis failed: runtime analysis is missing."],
            }
        try:
            analysis = llm.analyze_code(ra, chunks)
            return {"code_analysis": analysis}
        except Exception as exc:
            logger.error("analyze_code failed: %s", exc)
            return {
                "code_analysis": None,
                "errors": state.get("errors", []) + [f"Code analysis failed: {exc}"],
            }

    def route_after_code(state: InvestigationState) -> str:
        if state.get("code_analysis") is not None:
            return "continue"
        logger.warning("Halting investigation: required code analysis failed.")
        return "end"

    def retrieve_git_context_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing retrieve_git_context node")
        ca = state.get("code_analysis")
        chunks = state.get("code_results", [])

        # Identify unique files to query
        candidate_files: List[str] = []
        if ca and ca.relevant_files:
            candidate_files.extend(ca.relevant_files)
        for c in chunks:
            fp = c.get("file_path")
            if fp and fp not in candidate_files:
                candidate_files.append(fp)

        # Limit to top 2 files to avoid unbounded Git queries
        target_files = candidate_files[:2]
        git_context: List[Dict[str, Any]] = []
        errors = list(state.get("errors", []))

        for file_path in target_files:
            try:
                _, commits = git_service.get_file_history(path=file_path, limit=git_limit)
                commit_summaries = []
                for cm in commits:
                    commit_summaries.append({
                        "commit_hash": cm.commit_hash,
                        "short_hash": cm.short_hash,
                        "author_name": cm.author_name,
                        "committed_at": cm.committed_at.isoformat() if cm.committed_at else None,
                        "message": cm.message,
                    })

                # Fetch diff for the most recent commit touching this file if present
                file_diff = None
                if commits:
                    try:
                        diff_res = git_service.get_commit_diff(
                            commit_hash=commits[0].commit_hash,
                            path=file_path,
                            max_chars=5000,
                        )
                        file_diff = diff_res.diff
                    except Exception as diff_exc:
                        logger.debug("Diff retrieval skipped for %s: %s", file_path, diff_exc)

                # Case A: Normal condition if commits is empty (no error appended to errors)
                git_context.append({
                    "file_path": file_path,
                    "commits": commit_summaries,
                    "latest_diff": file_diff,
                })
            except Exception as exc:
                # Case B: Subsystem/read failure (record operational limitation in errors)
                logger.warning("Git inspection for file '%s' failed: %s", file_path, exc)
                errors.append(f"Git inspection unavailable for file '{file_path}': {exc}")
                git_context.append({
                    "file_path": file_path,
                    "commits": [],
                    "note": f"Git inspection unavailable: {exc}",
                })

        return {"git_context": git_context, "errors": errors}

    def analyze_changes_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing analyze_changes node")
        ra = state.get("runtime_analysis")
        ca = state.get("code_analysis")
        gc = state.get("git_context", [])

        # If Git context is completely empty, it's a normal condition (Case A)
        has_any_commits = any(bool(item.get("commits")) for item in gc)
        if not gc or not has_any_commits:
            logger.info("Skipping change analysis: no Git history found for investigated files (Case A).")
            return {"change_analysis": None}

        try:
            analysis = llm.analyze_changes(ra, ca, gc)
            return {"change_analysis": analysis}
        except Exception as exc:
            # Case C: LLM change-analysis failure -> record limitation, continue with runtime + code
            logger.warning("Change analysis reasoning failed (proceeding with runtime and code evidence): %s", exc)
            return {
                "change_analysis": None,
                "errors": state.get("errors", []) + [
                    f"Git change analysis reasoning failed: {exc} (proceeding with runtime and code evidence only)"
                ],
            }

    def retrieve_historical_context_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing retrieve_historical_context node")
        if memory_service is None:
            return {"historical_context": []}

        ra = state.get("runtime_analysis")
        ca = state.get("code_analysis")
        incident = state["incident"]

        query_parts: List[str] = [incident.title]
        if ra:
            if ra.important_messages:
                query_parts.extend(ra.important_messages)
            if ra.observed_failures:
                query_parts.extend(ra.observed_failures)

        query = HistoricalSearchQuery(
            current_incident_id=incident.id,
            service=ra.service if ra and ra.service else incident.service,
            environment=incident.environment,
            exception_type=ra.exception_type if ra else None,
            endpoint=ra.endpoint if ra else None,
            query_text=" ".join(query_parts).strip(),
            relevant_symbols=list(ca.relevant_symbols) if ca and ca.relevant_symbols else [],
            relevant_files=list(ca.relevant_files) if ca and ca.relevant_files else [],
            limit=2,
        )

        try:
            matches = memory_service.search_history(query)
            logger.info("Retrieved %d historical incident contexts.", len(matches))
            return {"historical_context": matches}
        except Exception as exc:
            logger.warning("Historical memory retrieval failed: %s", exc)
            return {
                "historical_context": [],
                "errors": list(state.get("errors", [])) + [f"Historical memory retrieval failed: {exc}"],
            }

    def _synthesize_rca_node(state: InvestigationState) -> Dict[str, Any]:
        return synthesize_rca_node(state, llm)

    def route_after_synthesis(state: InvestigationState) -> str:
        if state.get("rca") is not None:
            return "validate"
        logger.warning("Halting investigation graph: no RCA was synthesized.")
        return "end"

    def validate_rca_node(state: InvestigationState) -> Dict[str, Any]:
        logger.info("Executing validate_rca node")
        rca = state.get("rca")
        if not rca:
            return {"validation": RCAValidation(valid=False, issues=["No RCA was generated."])}

        try:
            validation = llm.validate_rca(
                rca=rca,
                incident=state["incident"],
                runtime_analysis=state.get("runtime_analysis"),
                code_analysis=state.get("code_analysis"),
                change_analysis=state.get("change_analysis"),
                evidence=state["runtime_evidence"],
                code_chunks=state.get("code_results", []),
                git_context=state.get("git_context", []),
            )
            return {"validation": validation}
        except Exception as exc:
            logger.error("validate_rca failed: %s", exc)
            return {
                "validation": RCAValidation(valid=False, issues=[f"Validation error: {exc}"]),
                "errors": state.get("errors", []) + [f"Validation error: {exc}"],
            }

    def route_after_validation(state: InvestigationState) -> str:
        validation = state.get("validation")
        rev_count = state.get("revision_count", 0)
        max_rev = state.get("max_revisions", max_revisions)

        if validation and validation.valid:
            logger.info("RCA validation passed; terminating workflow.")
            return "end"

        if rev_count < max_rev:
            logger.info("RCA validation failed; triggering revision (attempt %d/%d).", rev_count + 1, max_rev)
            return "revise"

        logger.warning("RCA validation failed and max revisions (%d) reached; terminating workflow.", max_rev)
        return "end"

    def revise_rca_node(state: InvestigationState) -> Dict[str, Any]:
        current_rev = state.get("revision_count", 0)
        logger.info("Executing revise_rca node (revision %d)", current_rev + 1)
        rca = state.get("rca")
        validation = state.get("validation")

        try:
            revised_rca = llm.revise_rca(
                rca=rca,
                validation=validation,
                incident=state["incident"],
                runtime_analysis=state.get("runtime_analysis"),
                code_analysis=state.get("code_analysis"),
                change_analysis=state.get("change_analysis"),
                evidence=state["runtime_evidence"],
                code_chunks=state.get("code_results", []),
                git_context=state.get("git_context", []),
                historical_context=state.get("historical_context", []),
            )
            return {
                "rca": revised_rca,
                "revision_count": current_rev + 1,
            }
        except Exception as exc:
            logger.error("revise_rca failed: %s", exc)
            return {
                "revision_count": current_rev + 1,
                "errors": state.get("errors", []) + [f"RCA revision failed: {exc}"],
            }

    # Graph construction
    workflow = StateGraph(InvestigationState)

    workflow.add_node("analyze_runtime", analyze_runtime_node)
    workflow.add_node("retrieve_code", retrieve_code_node)
    workflow.add_node("analyze_code", analyze_code_node)
    workflow.add_node("retrieve_git_context", retrieve_git_context_node)
    workflow.add_node("analyze_changes", analyze_changes_node)
    workflow.add_node("retrieve_historical_context", retrieve_historical_context_node)
    workflow.add_node("synthesize_rca", _synthesize_rca_node)
    workflow.add_node("validate_rca", validate_rca_node)
    workflow.add_node("revise_rca", revise_rca_node)

    workflow.add_edge(START, "analyze_runtime")
    workflow.add_conditional_edges(
        "analyze_runtime",
        route_after_runtime,
        {
            "continue": "retrieve_code",
            "end": END,
        },
    )
    workflow.add_edge("retrieve_code", "analyze_code")
    workflow.add_conditional_edges(
        "analyze_code",
        route_after_code,
        {
            "continue": "retrieve_git_context",
            "end": END,
        },
    )
    workflow.add_edge("retrieve_git_context", "analyze_changes")
    workflow.add_edge("analyze_changes", "retrieve_historical_context")
    workflow.add_edge("retrieve_historical_context", "synthesize_rca")
    workflow.add_conditional_edges(
        "synthesize_rca",
        route_after_synthesis,
        {
            "validate": "validate_rca",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "validate_rca",
        route_after_validation,
        {
            "revise": "revise_rca",
            "end": END,
        },
    )
    workflow.add_edge("revise_rca", "validate_rca")

    return workflow.compile()
