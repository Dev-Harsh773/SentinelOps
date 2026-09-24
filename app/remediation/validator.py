"""Deterministic grounding and provenance validator for remediation proposals."""

from typing import Any, Dict, List, Optional, Set

from app.agents.models import Investigation
from app.remediation.models import ChangeType, ProposedChange, RemediationProposal, RemediationValidation
from app.telemetry.models import Evidence


class RemediationValidator:
    """Enforces evidence provenance, target file grounding, and structural completeness on remediation proposals."""

    def validate(
        self,
        proposal: RemediationProposal,
        investigation: Investigation,
        runtime_evidence: List[Evidence],
        code_chunks: List[Dict[str, Any]],
        git_context: List[Dict[str, Any]],
    ) -> RemediationValidation:
        issues: List[str] = []
        unsupported_files: List[str] = []
        unsupported_symbols: List[str] = []
        missing_elements: List[str] = []

        # -------------------------------------------------------------
        # 1. Establish Verified Grounding Sets from Current Investigation
        # -------------------------------------------------------------
        retrieved_files: Set[str] = set()
        for chunk in code_chunks:
            fp = chunk.get("file_path")
            if fp:
                retrieved_files.add(fp.strip().replace("\\", "/"))

        if investigation.code_analysis and investigation.code_analysis.relevant_files:
            for rf in investigation.code_analysis.relevant_files:
                if rf:
                    retrieved_files.add(rf.strip().replace("\\", "/"))

        retrieved_symbols: Set[str] = set()
        for chunk in code_chunks:
            sym = chunk.get("symbol_name")
            if sym:
                retrieved_symbols.add(sym.strip())

        if investigation.code_analysis and investigation.code_analysis.relevant_symbols:
            for rs in investigation.code_analysis.relevant_symbols:
                if rs:
                    retrieved_symbols.add(rs.strip())

        valid_runtime_ids = {e.id for e in runtime_evidence}
        valid_chunk_ids = {c.get("id") for c in code_chunks if c.get("id")}
        valid_commit_hashes = set()
        for gc in git_context:
            for cm in gc.get("commits", []):
                h = cm.get("commit_hash") or cm.get("short_hash")
                if h:
                    valid_commit_hashes.add(h)

        # -------------------------------------------------------------
        # 2. Strong Target File Grounding (Current Investigation Only)
        # -------------------------------------------------------------
        for tf in proposal.target_files:
            norm_tf = tf.strip().replace("\\", "/")
            if norm_tf not in retrieved_files:
                unsupported_files.append(tf)
                issues.append(
                    f"Target file '{tf}' was not retrieved in the current investigation. "
                    "Remediation must not target unretrieved or unrelated repository files."
                )

        for pc in proposal.proposed_changes:
            norm_pc_file = pc.file_path.strip().replace("\\", "/")
            if norm_pc_file not in retrieved_files and norm_pc_file not in unsupported_files:
                unsupported_files.append(pc.file_path)
                issues.append(
                    f"Proposed change targets unretrieved file '{pc.file_path}'. "
                    "All changes must target files grounded in current investigation."
                )

        # -------------------------------------------------------------
        # 3. Target Symbol Grounding (Grounded when Provided)
        # -------------------------------------------------------------
        for sym in proposal.target_symbols:
            if sym and not self._is_symbol_grounded(sym, retrieved_symbols):
                unsupported_symbols.append(sym)
                issues.append(
                    f"Target symbol '{sym}' was not found in retrieved code chunks or code analysis."
                )

        for pc in proposal.proposed_changes:
            # Symbols are optional (e.g. configuration or file-level changes)
            if pc.symbol:
                if not self._is_symbol_grounded(pc.symbol, retrieved_symbols):
                    if pc.symbol not in unsupported_symbols:
                        unsupported_symbols.append(pc.symbol)
                        issues.append(
                            f"Proposed change references ungrounded symbol '{pc.symbol}'."
                        )

            # Check semantic compatibility of change with target symbol and retrieved code
            compat_issue = self._check_change_semantic_compatibility(
                change=pc,
                code_chunks=code_chunks,
                investigation=investigation,
            )
            if compat_issue:
                issues.append(compat_issue)
                if pc.symbol and pc.symbol not in unsupported_symbols:
                    unsupported_symbols.append(pc.symbol)

        # -------------------------------------------------------------
        # 4. Evidence Provenance Verification (No Historical Leaks)
        # -------------------------------------------------------------
        if not proposal.evidence_references:
            missing_elements.append("evidence_references")
            issues.append("Proposal must cite at least one evidence reference from current investigation.")
        else:
            for ref in proposal.evidence_references:
                ref_type = ref.type.lower()
                ref_id = ref.id.strip()

                # Historical incident IDs cannot masquerade as current grounding evidence
                if ref_id.startswith("inc-") or ref_type == "incident":
                    issues.append(
                        f"Evidence reference '{ref_id}' refers to historical incident data. "
                        "Remediation evidence_references must cite only current investigation evidence."
                    )
                    continue

                if ref_type in ("runtime", "runtime_log", "runtime-log"):
                    if ref_id not in valid_runtime_ids:
                        issues.append(f"Runtime evidence ID '{ref_id}' does not exist in current incident evidence.")
                elif ref_type in ("code", "source_code", "code_chunk"):
                    if ref_id not in valid_chunk_ids:
                        issues.append(f"Code chunk ID '{ref_id}' does not exist in current retrieved code chunks.")
                elif ref_type in ("git_commit", "git", "commit"):
                    if ref_id not in valid_commit_hashes:
                        issues.append(f"Git commit hash '{ref_id}' does not exist in current Git context.")
                else:
                    issues.append(f"Unknown evidence reference type '{ref.type}'.")

        # -------------------------------------------------------------
        # 5. Structural Completeness & Rationale
        # -------------------------------------------------------------
        if not proposal.proposed_changes:
            missing_elements.append("proposed_changes")
            issues.append("Proposal must contain at least one structured proposed change.")

        if not proposal.rationale or len(proposal.rationale.strip()) < 20:
            missing_elements.append("rationale")
            issues.append("Proposal must contain a substantive causal rationale.")

        if not proposal.risks:
            missing_elements.append("risks")
            issues.append("Proposal must explicitly identify potential side-effects or risks.")

        if not proposal.validation_steps:
            missing_elements.append("validation_steps")
            issues.append("Proposal must provide verification or validation steps.")

        valid = (
            len(issues) == 0
            and len(unsupported_files) == 0
            and len(unsupported_symbols) == 0
            and len(missing_elements) == 0
        )

        return RemediationValidation(
            valid=valid,
            issues=issues,
            unsupported_files=unsupported_files,
            unsupported_symbols=unsupported_symbols,
            missing_elements=missing_elements,
        )

    def _is_symbol_grounded(self, symbol: str, retrieved_symbols: Set[str]) -> bool:
        """Check if symbol matches any retrieved symbol directly or via qualification."""
        clean_sym = symbol.strip()
        if clean_sym in retrieved_symbols:
            return True

        clean_lower = clean_sym.lower()
        for rs in retrieved_symbols:
            rs_lower = rs.lower()
            if clean_lower == rs_lower:
                return True
            if clean_lower.endswith(f".{rs_lower}") or rs_lower.endswith(f".{clean_lower}"):
                return True

        return False

    def _check_change_semantic_compatibility(
        self,
        change: ProposedChange,
        code_chunks: List[Dict[str, Any]],
        investigation: Investigation,
    ) -> Optional[str]:
        """Verify that proposed changes are logically and semantically compatible with retrieved code.

        Specifically enforces:
        1. Source-code modify/add/remove proposals must not target an existing control function
           to redundantly 'add' the very disabling/reset behavior that the function already implements.
        2. Source-code modify/add/remove proposals must not place caller/order-creation logic inside
           administrative or control endpoints.
        3. Properly represented configuration/operational mitigations (change_type == CONFIGURATION)
           using existing controls are allowed and exempted from source-code modification checks.
        """
        # Configuration/operational mitigations are not source-code modifications
        if change.change_type == ChangeType.CONFIGURATION:
            return None

        # Only apply checks if a symbol is targeted or file is specified
        norm_file = change.file_path.strip().replace("\\", "/").lower()
        change_sym = (change.symbol or "").strip()
        change_sym_lower = change_sym.lower()
        desc_lower = change.description.lower()
        reason_lower = change.reason.lower()

        # Find matching chunk for symbol
        matching_chunk: Optional[Dict[str, Any]] = None
        for c in code_chunks:
            c_fp = (c.get("file_path") or "").strip().replace("\\", "/").lower()
            c_sym = (c.get("symbol_name") or "").strip()
            if change_sym and self._is_symbol_grounded(change_sym, {c_sym}):
                matching_chunk = c
                break

        if not matching_chunk:
            return None

        chunk_content = matching_chunk.get("content", "")
        chunk_content_lower = chunk_content.lower()
        chunk_sym_name = (matching_chunk.get("symbol_name") or change_sym_lower).lower()

        # 1. Redundant disabling behavior check on existing control functions
        is_disable_symbol = (
            chunk_sym_name.startswith("disable_")
            or chunk_sym_name.startswith("deactivate_")
            or chunk_sym_name.startswith("reset_")
            or "_disable" in chunk_sym_name
        )
        already_disables_in_content = (
            "disable" in chunk_content_lower
            and (
                "controller.disable" in chunk_content_lower
                or ".disable_" in chunk_content_lower
                or "failure_mode_disabled" in chunk_content_lower
                or "disabled" in chunk_content_lower
                or 'order_processing_error": false' in chunk_content_lower
                or 'error_enabled": false' in chunk_content_lower
            )
        )

        describes_adding_disable = (
            "disable" in desc_lower
            or "disable" in reason_lower
            or "turn off" in desc_lower
            or "turn off" in reason_lower
            or "deactivate" in desc_lower
            or "deactivate" in reason_lower
        )

        if is_disable_symbol and already_disables_in_content and describes_adding_disable:
            return (
                f"Target symbol '{change.symbol}' in '{change.file_path}' already implements disabling "
                "behavior in its retrieved definition. Proposing a source-code modification to add disabling "
                "behavior to this function is redundant. If the intention is to invoke this control to "
                "mitigate the incident, represent it as a 'configuration' change type rather than a "
                "source-code modification."
            )

        # 2. Execution-path mismatch: Caller/order creation logic proposed inside administrative control
        is_admin_endpoint = (
            "admin" in norm_file
            or chunk_sym_name.startswith("disable_")
            or chunk_sym_name.startswith("enable_")
        )
        describes_order_creation_flow = (
            "before creating an order" in desc_lower
            or "when creating an order" in desc_lower
            or "during order creation" in desc_lower
            or "in create_order" in desc_lower
            or "in the order creation path" in desc_lower
            or "before order creation" in desc_lower
        )
        if is_admin_endpoint and describes_order_creation_flow:
            return (
                f"Proposed source-code modification targets administrative control '{change.symbol}' in "
                f"'{change.file_path}', but the description describes modifying the order creation execution path. "
                "Administrative endpoints must not be modified to inject order-creation logic. Target the "
                "actual execution path (e.g. OrderService.create_order) or represent operational mitigation "
                "as a 'configuration' change."
            )

        return None

