"""Shared deterministic grounding checks for Root Cause Analysis in SentinelOps.

Enforces provider-independent evidence grounding across both mock and real LLM workflows.
Validates concrete citation existence, symbol consistency, baseline commit filtering,
and rejects fabricated methods, fields, and external infrastructure.
"""

import ast
import re
import textwrap
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agents.models import RCAValidation, RootCauseAnalysis
from app.telemetry.models import Evidence

BASELINE_KEYWORDS = {"initial", "baseline", "bootstrap", "scaffold"}
HALLUCINATED_INFRASTRUCTURE = {"redis", "postgresql", "kafka", "rabbitmq", "dynamodb", "mongodb"}
HALLUCINATED_ORDER_FIELDS = {
    "email",
    "shipping_address",
    "billing_address",
    "credit_card",
    "cvv",
    "payment_method",
    "postal_code",
    "zip_code",
}

GENERIC_CONDITION_TERMS = {
    "condition",
    "the condition",
    "controlled condition",
    "controlled failure condition",
    "failure condition",
    "failure mode",
    "controlled failure mode",
    "active controlled failure condition",
    "controlled failure mode active",
    "failure flag enabled",
}


def _norm(val: Any) -> str:
    """Normalize string/ID for robust comparison."""
    return str(val).strip().lower()


VALID_RUNTIME_TYPES = {"runtime", "runtime_log", "runtime-log"}
VALID_CODE_TYPES = {"code", "source_code", "code_chunk"}
VALID_GIT_TYPES = {"git_commit", "git", "commit"}

UNSUPPORTED_ENABLEMENT_PATTERNS = [
    r"failure\s+mode\s+was\s+enabled",
    r"controlled\s+failure(?:\s+mode)?\s+was\s+enabled",
    r"(?:mode|flag|toggle|error)\s+was\s+enabled",
    r"was\s+enabled\s+via",
    r"was\s+enabled\s+by",
    r"\bwas\s+enabled\b",
    r"enable_order_processing_error(?:\(\))?",
    r"enable_order_processing_failure(?:\(\))?",
    r"/admin[/\w-]*",
    r"admin\s+(?:enable\s+)?endpoint",
    r"enablement\s+endpoint",
    r"enabled\s+via\s+.*endpoint",
    r"enabled\s+via\s+.*admin",
]


def _extract_guarded_branches(code_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract if-conditions and their guarded bodies/exceptions from retrieved code chunks."""
    from pathlib import Path
    branches = []
    for c in code_chunks:
        content = c.get("content", "")
        chunk_id = c.get("id", "")
        file_path = c.get("file_path", "")

        if not content and file_path:
            fp = Path(file_path)
            if not fp.exists():
                for cand in (Path("demo_app/services") / fp.name, Path("demo_app") / fp.name):
                    if cand.exists():
                        fp = cand
                        break
            if fp.exists() and fp.is_file():
                try:
                    content = fp.read_text(encoding="utf-8")
                except Exception:
                    pass

        if not content or not content.strip():
            continue

        tree = None
        try:
            tree = ast.parse(textwrap.dedent(content))
        except Exception:
            pass

        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    try:
                        cond_str = ast.unparse(node.test).strip()
                    except Exception:
                        cond_str = ""

                    body_exceptions = set()
                    body_stmts = []
                    for stmt in node.body:
                        for sub in ast.walk(stmt):
                            if isinstance(sub, ast.Raise):
                                if sub.exc:
                                    try:
                                        if isinstance(sub.exc, ast.Call):
                                            body_exceptions.add(ast.unparse(sub.exc.func).split(".")[-1])
                                        elif isinstance(sub.exc, ast.Name):
                                            body_exceptions.add(sub.exc.id)
                                        else:
                                            body_exceptions.add(ast.unparse(sub.exc).split(".")[-1])
                                    except Exception:
                                        pass
                        try:
                            body_stmts.append(ast.unparse(stmt))
                        except Exception:
                            pass

                    if cond_str:
                        branches.append({
                            "condition": cond_str,
                            "branch_type": "truthy",
                            "raised_exceptions": body_exceptions,
                            "body_text": " ".join(body_stmts),
                            "chunk_id": chunk_id,
                            "file_path": file_path,
                        })

                    if node.orelse:
                        else_exceptions = set()
                        else_stmts = []
                        for stmt in node.orelse:
                            for sub in ast.walk(stmt):
                                if isinstance(sub, ast.Raise):
                                    if sub.exc:
                                        try:
                                            if isinstance(sub.exc, ast.Call):
                                                else_exceptions.add(ast.unparse(sub.exc.func).split(".")[-1])
                                            elif isinstance(sub.exc, ast.Name):
                                                else_exceptions.add(sub.exc.id)
                                            else:
                                                else_exceptions.add(ast.unparse(sub.exc).split(".")[-1])
                                        except Exception:
                                            pass
                            try:
                                else_stmts.append(ast.unparse(stmt))
                            except Exception:
                                pass

                        branches.append({
                            "condition": cond_str,
                            "branch_type": "falsey",
                            "raised_exceptions": else_exceptions,
                            "body_text": " ".join(else_stmts),
                            "chunk_id": chunk_id,
                            "file_path": file_path,
                        })

        if not branches:
            pattern = re.compile(r"if\s+([^:#\n]+):[^\n]*\n((?:[ \t]+[^\n]*\n?)+)", re.MULTILINE)
            for match in pattern.finditer(content):
                cond_str = match.group(1).strip()
                body = match.group(2)
                raised = set(re.findall(r"raise\s+([A-Za-z0-9_]+)", body))
                branches.append({
                    "condition": cond_str,
                    "branch_type": "truthy",
                    "raised_exceptions": raised,
                    "body_text": body,
                    "chunk_id": chunk_id,
                    "file_path": file_path,
                })

    return branches


def run_deterministic_grounding_check(
    rca: RootCauseAnalysis,
    evidence: List[Evidence],
    code_chunks: List[Dict[str, Any]],
    git_context: List[Dict[str, Any]],
) -> RCAValidation:
    """Performs strict, provider-independent deterministic checks on proposed RCA."""
    issues: List[str] = []
    unsupported_claims: List[str] = []

    # 1. Triggering condition depth check
    if not rca.triggering_condition or not rca.triggering_condition.strip():
        issues.append("RCA is missing a specific triggering condition underlying the exception.")
        unsupported_claims.append("Missing triggering condition")
    elif (
        rca.failure_location
        and rca.triggering_condition.strip().lower() == rca.failure_location.strip().lower()
    ):
        issues.append("Triggering condition cannot merely restate the failure location.")
        unsupported_claims.append("Redundant triggering condition")

    # Build known text corpus from evidence and retrieved code
    evidence_text_parts = [e.message + " " + e.event + " " + (e.exception_type or "") for e in evidence]
    for c in code_chunks:
        evidence_text_parts.append(c.get("content", ""))
        evidence_text_parts.append(c.get("file_path", ""))
        evidence_text_parts.append(c.get("symbol_name", "") or "")
    known_evidence_text = " ".join(evidence_text_parts).lower()

    rca_text = (
        f"{rca.failure_location} {rca.triggering_condition} {rca.root_cause_hypothesis} "
        f"{rca.affected_component} {rca.summary}"
    ).lower()

    # 2. Check for fabricated infrastructure / third-party technologies
    for tech in HALLUCINATED_INFRASTRUCTURE:
        if tech in rca_text and tech not in known_evidence_text:
            issues.append(f"RCA claims '{tech.capitalize()}' is involved, but no {tech} evidence was supplied.")
            unsupported_claims.append(f"Claim involving {tech}")

    # 3. Check for fabricated request/form fields (e.g. email, shipping_address)
    for field in HALLUCINATED_ORDER_FIELDS:
        if field in rca_text and field not in known_evidence_text:
            issues.append(
                f"RCA claims field or parameter '{field}' is involved, but it does not exist in runtime logs or code."
            )
            unsupported_claims.append(f"Claim involving field '{field}'")

    # 4. Check symbol grounding if code chunks were retrieved
    if code_chunks:
        retrieved_symbols: Set[str] = {
            c["symbol_name"] for c in code_chunks if c.get("symbol_name")
        }
        retrieved_short_symbols: Set[str] = {
            sym.split(".")[-1] for sym in retrieved_symbols
        }

        # Check failure_location
        if rca.failure_location:
            fl_short = rca.failure_location.split(".")[-1]
            if (
                rca.failure_location not in retrieved_symbols
                and fl_short not in retrieved_short_symbols
            ):
                issues.append(
                    f"Failure location '{rca.failure_location}' does not match any retrieved code symbol "
                    f"({', '.join(sorted(retrieved_symbols)) or 'none'})."
                )
                unsupported_claims.append(f"Unretrieved failure location '{rca.failure_location}'")

        # Check for hallucinated method invocations in hypothesis (e.g. checkout_order)
        symbol_pattern = re.findall(r"([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)", rca.root_cause_hypothesis)
        for sym in symbol_pattern:
            if "." in sym:
                # If the prefix matches one of our classes, verify the method exists
                for ret in retrieved_symbols:
                    if "." in ret:
                        ret_class = ret.split(".")[0]
                        if sym.startswith(ret_class + ".") and sym not in retrieved_symbols:
                            issues.append(
                                f"RCA asserts method '{sym}' which does not exist in retrieved class '{ret_class}'."
                            )
                            unsupported_claims.append(f"Invented symbol '{sym}'")
                            break

    # 5. Check concrete evidence citation validity and completeness
    valid_runtime_ids = {_norm(e.id) for e in evidence}
    valid_chunk_ids = {_norm(c["id"]) for c in code_chunks if c.get("id")}
    valid_commit_ids: Set[str] = set()
    commit_messages: Dict[str, str] = {}

    for gc in git_context:
        for cm in gc.get("commits", []):
            chash = cm.get("commit_hash")
            shash = cm.get("short_hash")
            msg = cm.get("message", "")
            if chash:
                valid_commit_ids.add(_norm(chash))
                commit_messages[_norm(chash)] = msg
            if shash:
                valid_commit_ids.add(_norm(shash))
                commit_messages[_norm(shash)] = msg

    cited_runtime_refs = []
    cited_code_refs = []

    for ref in rca.supporting_evidence:
        ref_type = _norm(ref.type)
        ref_id = _norm(ref.id)

        if ref_type in VALID_RUNTIME_TYPES:
            if ref_id not in valid_runtime_ids:
                issues.append(f"Cited runtime evidence ID '{ref.id}' does not exist in incident evidence.")
                unsupported_claims.append(f"Runtime reference {ref.id}")
            else:
                cited_runtime_refs.append(ref)
        elif ref_type in VALID_CODE_TYPES:
            if ref_id not in valid_chunk_ids:
                issues.append(f"Cited code chunk ID '{ref.id}' does not exist in retrieved chunks.")
                unsupported_claims.append(f"Code chunk reference {ref.id}")
            else:
                cited_code_refs.append(ref)
        elif ref_type in VALID_GIT_TYPES:
            if valid_commit_ids and ref_id not in valid_commit_ids:
                issues.append(f"Cited commit ID '{ref.id}' does not exist in retrieved Git context.")
                unsupported_claims.append(f"Commit reference {ref.id}")
            else:
                msg = commit_messages.get(ref_id, "").lower()
                if any(kw in msg for kw in BASELINE_KEYWORDS):
                    issues.append(
                        f"Cited commit '{ref.id}' is a baseline commit and does not support causation."
                    )
                    unsupported_claims.append(f"Baseline commit {ref.id}")
        else:
            issues.append(
                f"Unknown supporting evidence type '{ref.type}'. Must be 'runtime', 'code', or 'git_commit'."
            )
            unsupported_claims.append(f"Invalid evidence type {ref.type}")

    # Enforce mandatory runtime evidence citation when runtime evidence exists
    if evidence and not cited_runtime_refs:
        issues.append(
            "RCA relies on runtime incident evidence but does not cite any valid runtime evidence ID in supporting_evidence."
        )
        unsupported_claims.append("Missing runtime evidence citation")

    # Enforce mandatory code evidence citation when code evidence exists and code-level claims are made
    has_code_claims = bool(
        rca.failure_location
        or rca.affected_component
        or (code_chunks and any(c.get("symbol_name") and c["symbol_name"] in rca_text for c in code_chunks))
    )
    if code_chunks and has_code_claims and not cited_code_refs:
        issues.append(
            "RCA makes code-level causal claims but does not cite any valid retrieved source code chunk ID in supporting_evidence."
        )
        unsupported_claims.append("Missing code chunk citation")

    # 6. Check for unevidenced endpoint-specific enablement claims
    # (e.g. claiming failure mode was enabled via an admin or enablement endpoint not present in telemetry)
    observed_endpoints = {_norm(e.endpoint) for e in evidence if e.endpoint}
    observed_events = {_norm(e.event) for e in evidence if e.event}
    has_admin_evidence = any(
        "/admin" in ep or "enable" in ep for ep in observed_endpoints
    ) or any(
        "enable" in ev or "admin" in ev for ev in observed_events
    )

    if not has_admin_evidence:
        for pattern in UNSUPPORTED_ENABLEMENT_PATTERNS:
            matches = re.findall(pattern, rca_text, flags=re.IGNORECASE)
            if matches:
                matched_str = matches[0]
                issues.append(
                    f"RCA claims that '{matched_str}', which asserts how the condition became true, "
                    f"but no telemetry or evidence from that action or endpoint was observed in the incident."
                )
                unsupported_claims.append(f"Unsupported enablement assertion: '{matched_str}'")
                break

    # 7. Check control-flow condition inference grounding
    # Grounded control-flow inference allows claiming that a branch condition evaluated truthy/falsey
    # IF runtime evidence proves execution reached code inside that branch, AND source code guards that execution.
    candidate_assertions: List[Tuple[str, str]] = []
    tc_clean = rca.triggering_condition.strip() if rca.triggering_condition else ""

    # Quoted condition pattern: e.g. Controlled condition 'failure_enabled' evaluated to True
    quoted_match = re.search(
        r"['\"`]([^'\"`]+)['\"`]\s+(?:evaluated\s+(?:to\s+)?|is\s+|was\s+)(true|truthy|false|falsey)\b",
        tc_clean,
        re.IGNORECASE,
    )
    if quoted_match:
        candidate_assertions.append(
            (quoted_match.group(1).strip(), "truthy" if quoted_match.group(2).lower() in ("true", "truthy") else "falsey")
        )
    else:
        # Match condition expression anchored at start of triggering_condition or after when/because/if
        m = re.search(
            r"(?:^(?:controlled\s+condition\s+)?|(?:because|when|if)\s+)['\"`]?([A-Za-z0-9_\.()\[\]=><! -]+?)['\"`]?\s+"
            r"(?:evaluated\s+(?:to\s+)?|is\s+|was\s+)(true|truthy|false|falsey)\b",
            tc_clean,
            re.IGNORECASE,
        )
        if m:
            candidate_assertions.append(
                (m.group(1).strip(), "truthy" if m.group(2).lower() in ("true", "truthy") else "falsey")
            )

    # Also detect when triggering_condition directly states a code expression without "evaluated true"
    if not candidate_assertions and tc_clean and ("." in tc_clean or "(" in tc_clean):
        if re.search(r"^[A-Za-z0-9_\.]+(?:\([^)]*\))?$", tc_clean):
            candidate_assertions.append((tc_clean, "truthy"))

    if candidate_assertions and code_chunks:
        from pathlib import Path
        chunks_code_text_parts = []
        for c in code_chunks:
            cnt = c.get("content", "")
            if not cnt and c.get("file_path"):
                fp = Path(c["file_path"])
                if not fp.exists():
                    for cand_fp in (Path("demo_app/services") / fp.name, Path("demo_app") / fp.name):
                        if cand_fp.exists():
                            fp = cand_fp
                            break
                if fp.exists() and fp.is_file():
                    try:
                        cnt = fp.read_text(encoding="utf-8")
                    except Exception:
                        pass
            if cnt:
                chunks_code_text_parts.append(cnt)
        chunks_code_text = " ".join(chunks_code_text_parts).lower()

        observed_exceptions = {e.exception_type for e in evidence if e.exception_type}
        ev_messages = [e.message.lower() for e in evidence if e.message] + [
            e.event.lower() for e in evidence if e.event
        ] + [str(e.metadata.get("traceback", "")).lower() for e in evidence if e.metadata]
        ev_full_text = " ".join(ev_messages)

        branches = _extract_guarded_branches(code_chunks)

        for cand, val_type in candidate_assertions:
            cand_norm = _norm(cand).strip("'\"`")
            if cand_norm in GENERIC_CONDITION_TERMS:
                continue

            # Check if condition identifier exists anywhere in retrieved code chunks
            tokens = [
                t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", cand_norm)
                if len(t) > 2 and t not in ("self", "get", "is", "not", "true", "false")
            ]
            cand_in_code = cand_norm in chunks_code_text or (bool(tokens) and any(tok in chunks_code_text for tok in tokens))

            if not cand_in_code:
                # Fabricated condition not present in retrieved code
                issues.append(
                    f"RCA asserts condition '{cand}' evaluated {val_type}, but '{cand}' does not exist in any retrieved code chunk."
                )
                unsupported_claims.append(f"Fabricated condition '{cand}'")
                continue

            # Find matching branches in retrieved code
            matching_branches = []
            for b in branches:
                b_cond_norm = _norm(b["condition"])
                if cand_norm in b_cond_norm or b_cond_norm in cand_norm or any(tok in b_cond_norm for tok in tokens):
                    matching_branches.append(b)

            if matching_branches:
                # Check if runtime evidence proves execution reached that branch body
                reached = False
                for mb in matching_branches:
                    if mb["raised_exceptions"] & observed_exceptions:
                        reached = True
                        break
                    if any(_norm(exc) in ev_full_text for exc in mb["raised_exceptions"]):
                        reached = True
                        break
                    for stmt in mb.get("body_text", "").splitlines():
                        s_clean = stmt.strip().lower()
                        if len(s_clean) > 10 and s_clean in ev_full_text:
                            reached = True
                            break

                if not reached:
                    issues.append(
                        f"RCA claims condition '{cand}' evaluated {val_type}, but runtime evidence does not prove execution reached that branch body."
                    )
                    unsupported_claims.append(f"Ungrounded branch condition claim '{cand}'")

    is_valid = len(issues) == 0
    missing = [f"Provide proof for: {c}" for c in unsupported_claims] if unsupported_claims else []
    if is_valid:
        missing = []
    elif not missing and issues:
        missing = [f"Provide proof for: {iss}" for iss in issues]

    return RCAValidation(
        valid=is_valid,
        issues=issues,
        unsupported_claims=unsupported_claims,
        missing_evidence=missing,
    )


def is_grounded_control_flow_claim(
    rca: RootCauseAnalysis,
    evidence: List[Evidence],
    code_chunks: List[Dict[str, Any]],
) -> bool:
    """Verifies whether the RCA's triggering condition is a valid grounded control-flow inference."""
    if not code_chunks or not evidence:
        return False
    branches = _extract_guarded_branches(code_chunks)
    if not branches:
        return False

    observed_exceptions = {e.exception_type for e in evidence if e.exception_type}
    ev_messages = [e.message.lower() for e in evidence if e.message] + [
        e.event.lower() for e in evidence if e.event
    ] + [str(e.metadata.get("traceback", "")).lower() for e in evidence if e.metadata]
    ev_full_text = " ".join(ev_messages)

    reached_branches = []
    for b in branches:
        if b["raised_exceptions"] & observed_exceptions:
            reached_branches.append(b)
        elif any(_norm(exc) in ev_full_text for exc in b["raised_exceptions"]):
            reached_branches.append(b)

    if not reached_branches:
        return False

    tc = _norm(rca.triggering_condition or "")
    hypo = _norm(rca.root_cause_hypothesis or "")
    for rb in reached_branches:
        b_cond = _norm(rb["condition"])
        tokens = [
            t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", b_cond)
            if len(t) > 2 and t not in ("self", "get", "is", "not", "true", "false")
        ]
        if b_cond in tc or b_cond in hypo or any(t in tc for t in tokens):
            return True
    return False


def get_rca_text_corpus(rca: RootCauseAnalysis) -> str:
    """Extracts all text components from an RCA for claim-presence verification."""
    components = [
        rca.failure_location or "",
        rca.triggering_condition or "",
        rca.root_cause_hypothesis or "",
        rca.affected_component or "",
        rca.summary or "",
    ]
    if rca.supporting_evidence:
        for ref in rca.supporting_evidence:
            if ref.description:
                components.append(ref.description)
    if rca.uncertainties:
        components.extend(rca.uncertainties)
    return " ".join(components).lower()


def rca_contains_enablement_claim(rca_text: str) -> bool:
    """Checks whether the RCA text actually makes an assertion that a failure mode was enabled."""
    return any(re.search(pat, rca_text, flags=re.IGNORECASE) for pat in UNSUPPORTED_ENABLEMENT_PATTERNS)


def reconcile_semantic_validation_findings(
    rca: RootCauseAnalysis,
    det_validation: RCAValidation,
    llm_valid: bool,
    llm_issues: List[str],
    llm_unsupported: List[str],
    llm_missing: List[str],
    code_chunks: Optional[List[Dict[str, Any]]] = None,
    evidence: Optional[List[Evidence]] = None,
) -> RCAValidation:
    """Reconciles semantic validator findings with deterministic grounding and actual RCA content.

    Ensures that alleged unsupported claims correspond to actual text produced in the RCA,
    discarding validator false-positive allegations (such as conflating 'condition evaluated true'
    with 'failure mode was enabled').
    """
    rca_corpus = get_rca_text_corpus(rca)
    has_rca_enablement = rca_contains_enablement_claim(rca_corpus)

    valid_runtime_in_rca = False
    if evidence:
        valid_ev_ids = {_norm(e.id) for e in evidence}
        valid_runtime_in_rca = any(
            _norm(ref.type) in VALID_RUNTIME_TYPES and _norm(ref.id) in valid_ev_ids
            for ref in (rca.supporting_evidence or [])
        )

    valid_code_in_rca = False
    if code_chunks:
        valid_chunk_ids = {_norm(c["id"]) for c in code_chunks if c.get("id")}
        valid_code_in_rca = any(
            _norm(ref.type) in VALID_CODE_TYPES and _norm(ref.id) in valid_chunk_ids
            for ref in (rca.supporting_evidence or [])
        )

    enablement_keywords = (
        "was enabled",
        "is enabled",
        "'was enabled'",
        '"was enabled"',
        "admin endpoint",
        "admin",
        "endpoint",
        "enable_order_processing",
        "enablement",
    )

    cond_terms = (
        "condition",
        "boolean",
        "evaluated true",
        "evaluat",
        "is_order_processing_error_enabled",
        "failure_controller",
    )
    telemetry_terms = (
        "telemetry",
        "direct telemetry",
        "telemetry evidence",
        "direct evidence",
        "proof",
        "logs",
        "logging",
    )
    triggering_cond = (rca.triggering_condition or "").lower()

    def _should_discard_finding(finding: str) -> bool:
        if not finding or not str(finding).strip():
            return True
        f_lower = str(finding).lower()

        # 1. Enablement / admin action allegation:
        # If the validator alleges the failure mode was enabled or an admin action occurred,
        # but the RCA itself makes NO enablement claim, this finding is a false-positive hallucination.
        is_enablement_allegation = any(kw in f_lower for kw in enablement_keywords)
        if is_enablement_allegation and not has_rca_enablement:
            return True

        # 2. Spurious citation complaints when citations are already present and verified:
        if valid_runtime_in_rca and any(
            w in f_lower for w in ("runtime evidence reference", "runtime citation", "missing runtime", "runtime log reference")
        ):
            return True
        if valid_code_in_rca and any(
            w in f_lower for w in ("code chunk reference", "missing code", "valid code", "code citation")
        ):
            return True

        # 3. Spurious boolean telemetry complaints when control-flow inference is grounded:
        if det_validation.valid:
            if triggering_cond and triggering_cond in f_lower:
                return True
            has_cond = any(w in f_lower for w in cond_terms)
            has_telem = any(w in f_lower for w in telemetry_terms)
            if has_cond or has_telem:
                # Do not discard if it's an enablement claim that the RCA actually asserted
                if not (is_enablement_allegation and has_rca_enablement):
                    return True

        # 4. Invented symbol/field/infrastructure allegations where the entity is absent from RCA:
        for tech in HALLUCINATED_INFRASTRUCTURE:
            if tech in f_lower and tech not in rca_corpus:
                return True
        for field in HALLUCINATED_ORDER_FIELDS:
            if field in f_lower and field not in rca_corpus:
                return True
        if "checkout_order" in f_lower and "checkout_order" not in rca_corpus:
            return True

        return False

    filtered_issues = [iss for iss in llm_issues if not _should_discard_finding(iss)]
    filtered_unsupported = [u for u in llm_unsupported if not _should_discard_finding(u)]
    filtered_missing = [m for m in llm_missing if not _should_discard_finding(m)]

    # If all LLM findings were false positives or LLM marked it valid:
    semantic_valid = llm_valid or (
        len(filtered_issues) == 0 and len(filtered_unsupported) == 0 and len(filtered_missing) == 0
    )
    is_valid = det_validation.valid and semantic_valid

    if is_valid:
        return RCAValidation(
            valid=True,
            issues=[],
            unsupported_claims=[],
            missing_evidence=[],
        )
    else:
        merged_issues = list(dict.fromkeys(det_validation.issues + filtered_issues))
        merged_unsupported = list(dict.fromkeys(det_validation.unsupported_claims + filtered_unsupported))
        merged_missing = list(dict.fromkeys(det_validation.missing_evidence + filtered_missing))

        # Enforce invariant: missing_evidence must be non-empty when valid=False
        if not merged_missing and (merged_issues or merged_unsupported):
            merged_missing = [f"Provide evidence for: {c}" for c in (merged_unsupported or merged_issues)]

        return RCAValidation(
            valid=False,
            issues=merged_issues,
            unsupported_claims=merged_unsupported,
            missing_evidence=merged_missing,
        )
