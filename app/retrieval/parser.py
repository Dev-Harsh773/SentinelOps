"""AST-based Python source code parser for chunk extraction in SentinelOps."""

import ast
from pathlib import Path
from typing import List, Optional, Tuple

from app.retrieval.models import CodeChunk


class ParseError(Exception):
    """Raised when a Python source file cannot be parsed into an AST."""

    def __init__(self, file_path: str, cause: Exception):
        super().__init__(f"Failed to parse source file '{file_path}': {cause}")
        self.file_path = file_path
        self.cause = cause


def _trim_line_range(
    lines: List[str], start_1based: int, end_1based: int
) -> Optional[Tuple[int, int, str]]:
    """Trims leading and trailing blank lines from a 1-based line interval.

    Returns:
        (trimmed_start_1based, trimmed_end_1based, content_string) or None if entirely blank.
    """
    start_idx = max(0, start_1based - 1)
    end_idx = min(len(lines), end_1based)

    while start_idx < end_idx and not lines[start_idx].strip():
        start_idx += 1
    while end_idx > start_idx and not lines[end_idx - 1].strip():
        end_idx -= 1

    if start_idx >= end_idx:
        return None

    content = "\n".join(lines[start_idx:end_idx])
    return start_idx + 1, end_idx, content


class PythonAstParser:
    """Parses Python source files into semantic, non-overlapping CodeChunk units."""

    def parse_file(self, file_path: str, abs_path: Path) -> List[CodeChunk]:
        """Parses a Python file and returns extracted CodeChunks.

        Raises:
            ParseError: If ast.parse encounters a syntax or decoding error.
        """
        try:
            source_code = abs_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise ParseError(file_path, exc) from exc

        try:
            tree = ast.parse(source_code, filename=file_path)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            raise ParseError(file_path, exc) from exc

        lines = source_code.splitlines()
        chunks: List[CodeChunk] = []

        # Identify top-level definitions (functions, classes) and their line ranges
        def_intervals: List[Tuple[int, int]] = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                node_start = (
                    min(d.lineno for d in node.decorator_list)
                    if node.decorator_list
                    else node.lineno
                )
                node_end = getattr(node, "end_lineno", node_start)
                def_intervals.append((node_start, node_end))

        # Sort intervals by start line
        def_intervals.sort(key=lambda span: span[0])

        # 1. Extract Module-level chunks (code outside top-level functions and classes)
        total_lines = len(lines)
        curr_line = 1
        for def_start, def_end in def_intervals:
            if def_start > curr_line:
                trimmed = _trim_line_range(lines, curr_line, def_start - 1)
                if trimmed:
                    start_l, end_l, content = trimmed
                    chunks.append(
                        CodeChunk.create(
                            file_path=file_path,
                            symbol_name=None,
                            symbol_type="module",
                            start_line=start_l,
                            end_line=end_l,
                            content=content,
                        )
                    )
            curr_line = max(curr_line, def_end + 1)

        # Remaining module code after the last definition
        if curr_line <= total_lines:
            trimmed = _trim_line_range(lines, curr_line, total_lines)
            if trimmed:
                start_l, end_l, content = trimmed
                chunks.append(
                    CodeChunk.create(
                        file_path=file_path,
                        symbol_name=None,
                        symbol_type="module",
                        start_line=start_l,
                        end_line=end_l,
                        content=content,
                    )
                )

        # 2. Extract Top-level Functions and Classes
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_start = (
                    min(d.lineno for d in node.decorator_list)
                    if node.decorator_list
                    else node.lineno
                )
                fn_end = getattr(node, "end_lineno", fn_start)
                trimmed = _trim_line_range(lines, fn_start, fn_end)
                if trimmed:
                    start_l, end_l, content = trimmed
                    chunks.append(
                        CodeChunk.create(
                            file_path=file_path,
                            symbol_name=node.name,
                            symbol_type="function",
                            start_line=start_l,
                            end_line=end_l,
                            content=content,
                        )
                    )

            elif isinstance(node, ast.ClassDef):
                cls_start = (
                    min(d.lineno for d in node.decorator_list)
                    if node.decorator_list
                    else node.lineno
                )
                cls_end = getattr(node, "end_lineno", cls_start)

                # Find methods inside class
                methods = [
                    m
                    for m in node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]

                if methods:
                    first_method_start = (
                        min(d.lineno for d in methods[0].decorator_list)
                        if methods[0].decorator_list
                        else methods[0].lineno
                    )
                    cls_header_end = max(cls_start, first_method_start - 1)
                else:
                    cls_header_end = cls_end

                # Class header chunk
                trimmed_cls = _trim_line_range(lines, cls_start, cls_header_end)
                if trimmed_cls:
                    start_l, end_l, content = trimmed_cls
                    chunks.append(
                        CodeChunk.create(
                            file_path=file_path,
                            symbol_name=node.name,
                            symbol_type="class",
                            start_line=start_l,
                            end_line=end_l,
                            content=content,
                        )
                    )

                # Individual method chunks
                for method in methods:
                    m_start = (
                        min(d.lineno for d in method.decorator_list)
                        if method.decorator_list
                        else method.lineno
                    )
                    m_end = getattr(method, "end_lineno", m_start)
                    trimmed_m = _trim_line_range(lines, m_start, m_end)
                    if trimmed_m:
                        start_l, end_l, content = trimmed_m
                        chunks.append(
                            CodeChunk.create(
                                file_path=file_path,
                                symbol_name=f"{node.name}.{method.name}",
                                symbol_type="method",
                                start_line=start_l,
                                end_line=end_l,
                                content=content,
                            )
                        )

        # Deterministic sorting within file by start_line, then symbol_name
        chunks.sort(key=lambda c: (c.start_line, c.symbol_name or ""))
        return chunks
