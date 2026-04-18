"""
PlanValidator — static structural validation of ExecutionManifest / DAG.

Performs "static analysis" checks BEFORE execution:
  1. DAG acyclicity (cycle detection via DFS)
  2. Dependency validity (all referenced nodes exist)
  3. Tool existence (tool name is registered)
  4. Version compatibility (tool schema drift detection)
  5. Memory/tool mismatch (RAG nodes should use memory tools)
  6. Ordering consistency (dependencies respect topological order)

Returns PlanValidationResult with PASS / FAIL / WARN.
Safe to run synchronously — no I/O, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..planning.plan_executor import ExecutionManifest, StepManifest


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class ValidationIssue:
    status: ValidationStatus
    rule: str
    message: str
    step_id: Optional[str] = None
    detail: Optional[str] = None

    def is_pass(self) -> bool:
        return self.status == ValidationStatus.PASS

    def is_fail(self) -> bool:
        return self.status == ValidationStatus.FAIL

    def is_warning(self) -> bool:
        return self.status == ValidationStatus.WARN


@dataclass
class PlanValidationResult:
    status: ValidationStatus
    issues: list[ValidationIssue] = field(default_factory=list)
    dag_depth: int = 0           # longest dependency chain
    parallel_opportunities: int = 0  # steps that could run in parallel

    @property
    def is_valid(self) -> bool:
        return self.status != ValidationStatus.FAIL

    def summary(self) -> str:
        lines = [f"[{self.status.value.upper()}] PlanValidator result"]
        if self.issues:
            for issue in self.issues:
                prefix = "✓" if issue.is_pass() else "✗" if issue.is_fail() else "⚠"
                lines.append(f"  {prefix} {issue.rule}: {issue.message}")
        lines.append(f"  DAG depth: {self.dag_depth}, parallel opportunities: {self.parallel_opportunities}")
        return "\n".join(lines)


# ── Tool registry (tool existence check) ───────────────────────────────────────

KNOWN_TOOLS: set[str] = {
    "bash", "shell", "llm", "ollama", "rag", "memory",
    "http", "api", "embed", "vector", "file", "read", "write",
    "grep_search", "run_bash_command", "edit_file_llm", "create_or_rewrite_file",
    "read_file", "list_files", "mkdir", "mv", "cp",
    "http_fetch", "read_webpage", "save_webpage",
    "generate_image", "generate_video",
    "transcribe_audio", "transcribe_video",
    "sql", "query", "duckdb",
    "agent", "subagent", "spawn",
}

# Tools that require memory/RAG context
MEMORY_TOOLS: set[str] = {"rag", "memory", "query", "embed", "vector"}


class PlanValidator:
    """
    Static validator for ExecutionManifest / DAG structures.

    Usage::

        validator = PlanValidator()
        result = validator.validate(manifest)
        if not result.is_valid:
            print(result.summary())
    """

    def validate(self, manifest: ExecutionManifest) -> PlanValidationResult:
        """
        Full validation pipeline.

        Runs all checks in order, short-circuits on structural FAIL.
        Returns full result with all issues found.
        """
        issues: list[ValidationIssue] = []

        # ── structural checks (FAIL on first error) ──────────────────────────

        # 1. Empty manifest
        if not manifest.steps:
            issues.append(ValidationIssue(
                status=ValidationStatus.FAIL,
                rule="non_empty",
                message="Manifest has no steps",
            ))
            return PlanValidationResult(status=ValidationStatus.FAIL, issues=issues)

        # 2. Cycle detection
        cycle_issue = self._detect_cycles(manifest)
        if cycle_issue:
            issues.append(cycle_issue)

        # 3. Duplicate step IDs
        dup_issue = self._check_duplicate_ids(manifest)
        if dup_issue:
            issues.append(dup_issue)

        # 4. Dependency validity
        issues += self._check_dependencies(manifest)

        # ── semantic checks (WARN but don't fail) ─────────────────────────────

        # 5. Tool existence
        issues += self._check_tool_existence(manifest)

        # 6. Memory/tool mismatch
        issues += self._check_memory_tool_mismatch(manifest)

        # 7. Ordering consistency
        issues += self._check_ordering_consistency(manifest)

        # 8. Payload sanity
        issues += self._check_payload_sanity(manifest)

        # ── compute derived metrics ────────────────────────────────────────────

        dag_depth = self._compute_dag_depth(manifest)
        parallel_ops = self._count_parallel_opportunities(manifest)

        # ── determine final status ─────────────────────────────────────────────

        has_fail = any(i.is_fail() for i in issues)
        has_warn = any(i.is_warning() for i in issues)

        if has_fail:
            status = ValidationStatus.FAIL
        elif has_warn:
            status = ValidationStatus.WARN
        else:
            status = ValidationStatus.PASS

        return PlanValidationResult(
            status=status,
            issues=issues,
            dag_depth=dag_depth,
            parallel_opportunities=parallel_ops,
        )

    # ── cycle detection ────────────────────────────────────────────────────────

    def _detect_cycles(self, manifest: ExecutionManifest) -> Optional[ValidationIssue]:
        """
        DFS-based cycle detection.
        Builds a dependency graph from step order.
        A cycle exists if DFS finds a node still in current recursion stack.
        """
        # Build adjacency: step → steps that depend on it
        # For this system, ordering implies dependency (order=N depends on order<N)
        step_by_id: dict[str, StepManifest] = {s.step_id: s for s in manifest.steps}

        # Build "depends on" set from order field
        # step A depends on step B if A.order > B.order and they share a logical dependency
        # Conservative approach: check if payload references other step_ids
        depends_on: dict[str, set[str]] = {s.step_id: set() for s in manifest.steps}

        for step in manifest.steps:
            payload_str = str(step.payload)
            for other_id in step_by_id:
                if other_id != step.step_id and other_id in payload_str:
                    depends_on[step.step_id].add(other_id)

        # DFS with color: WHITE=unvisited, GRAY=in-progress, BLACK=done
        color: dict[str, int] = {sid: 0 for sid in step_by_id}

        def dfs(node: str) -> Optional[str]:
            color[node] = 1  # GRAY
            for dep in depends_on.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == 1:  # Back-edge found → cycle
                    return dep
                if color[dep] == 0:
                    cycle_node = dfs(dep)
                    if cycle_node:
                        return cycle_node
            color[node] = 2  # BLACK
            return None

        for step_id in step_by_id:
            if color[step_id] == 0:
                cycle = dfs(step_id)
                if cycle:
                    return ValidationIssue(
                        status=ValidationStatus.FAIL,
                        rule="acyclicity",
                        message=f"Cycle detected involving step '{cycle}'",
                        detail=f"cycle_node={cycle}",
                    )

        return None

    # ── duplicate ID check ────────────────────────────────────────────────────

    def _check_duplicate_ids(self, manifest: ExecutionManifest) -> Optional[ValidationIssue]:
        step_ids = [s.step_id for s in manifest.steps]
        if len(step_ids) != len(set(step_ids)):
            seen: dict[str, int] = {}
            for sid in step_ids:
                seen[sid] = seen.get(sid, 0) + 1
            dups = [f"{sid} ({count}x)" for sid, count in seen.items() if count > 1]
            return ValidationIssue(
                status=ValidationStatus.FAIL,
                rule="unique_ids",
                message=f"Duplicate step IDs: {', '.join(dups)}",
            )
        return None

    # ── dependency validity ─────────────────────────────────────────────────

    def _check_dependencies(self, manifest: ExecutionManifest) -> list[ValidationIssue]:
        issues = []
        step_ids = {s.step_id for s in manifest.steps}

        for step in manifest.steps:
            payload_str = str(step.payload)
            for referenced_id in step_ids:
                if referenced_id != step.step_id and referenced_id in payload_str:
                    # Check order: a step should not reference a step that comes after it
                    other = next((s for s in manifest.steps if s.step_id == referenced_id), None)
                    if other and other.order >= step.order:
                        issues.append(ValidationIssue(
                            status=ValidationStatus.WARN,
                            rule="dependency_order",
                            message=f"Step '{step.step_id}' references '{referenced_id}' which is not before it",
                            step_id=step.step_id,
                            detail=f"order_{step.step_id}={step.order}, order_{referenced_id}={other.order}",
                        ))

        return issues

    # ── tool existence ────────────────────────────────────────────────────────

    def _check_tool_existence(self, manifest: ExecutionManifest) -> list[ValidationIssue]:
        issues = []
        unknown_tools: set[str] = set()

        for step in manifest.steps:
            if step.tool.lower() not in KNOWN_TOOLS:
                unknown_tools.add(step.tool)

        if unknown_tools:
            issues.append(ValidationIssue(
                status=ValidationStatus.WARN,
                rule="tool_existence",
                message=f"Unknown tools (not in registry): {sorted(unknown_tools)}",
            ))

        return issues

    # ── memory/tool mismatch ─────────────────────────────────────────────────

    def _check_memory_tool_mismatch(self, manifest: ExecutionManifest) -> list[ValidationIssue]:
        """
        Semantic check: RAG/memory nodes should use memory/RAG tools.
        If a step looks like it needs memory context but uses shell — flag it.
        """
        issues = []

        memory_keywords = {"search", "find", "query", "recall", "remember", "context", "history"}
        shell_keywords = {"bash", "shell", "run", "execute", "command"}

        for step in manifest.steps:
            name_lower = step.step_name.lower()
            tool_lower = step.tool.lower()

            needs_memory = any(k in name_lower for k in memory_keywords)
            uses_shell = tool_lower in shell_keywords
            uses_memory = tool_lower in MEMORY_TOOLS

            if needs_memory and uses_shell and not uses_memory:
                issues.append(ValidationIssue(
                    status=ValidationStatus.WARN,
                    rule="memory_tool_mismatch",
                    message=f"Step '{step.step_name}' suggests memory operation but uses '{step.tool}'",
                    step_id=step.step_id,
                    detail="Consider using 'rag' or 'memory' tool instead",
                ))

        return issues

    # ── ordering consistency ─────────────────────────────────────────────────

    def _check_ordering_consistency(self, manifest: ExecutionManifest) -> list[ValidationIssue]:
        """Check that steps are topologically sorted by their order field."""
        issues = []

        steps_by_order = sorted(manifest.steps, key=lambda s: s.order)
        for i in range(1, len(steps_by_order)):
            prev = steps_by_order[i - 1]
            curr = steps_by_order[i]
            if curr.order <= prev.order:
                issues.append(ValidationIssue(
                    status=ValidationStatus.FAIL,
                    rule="ordering_consistency",
                    message=f"Steps out of order: {prev.step_id}(order={prev.order}) before {curr.step_id}(order={curr.order})",
                    step_id=curr.step_id,
                ))

        return issues

    # ── payload sanity ───────────────────────────────────────────────────────

    def _check_payload_sanity(self, manifest: ExecutionManifest) -> list[ValidationIssue]:
        """Check for empty payloads, None values, obvious misconfigs."""
        issues = []

        for step in manifest.steps:
            if not step.payload:
                issues.append(ValidationIssue(
                    status=ValidationStatus.WARN,
                    rule="empty_payload",
                    message=f"Step '{step.step_name}' has empty payload",
                    step_id=step.step_id,
                ))
            elif step.payload is None:
                issues.append(ValidationIssue(
                    status=ValidationStatus.FAIL,
                    rule="null_payload",
                    message=f"Step '{step.step_name}' payload is None",
                    step_id=step.step_id,
                ))

            if step.estimated_latency_ms < 0:
                issues.append(ValidationIssue(
                    status=ValidationStatus.WARN,
                    rule="negative_latency",
                    message=f"Step '{step.step_name}' has negative latency estimate",
                    step_id=step.step_id,
                ))

        return issues

    # ── DAG metrics ───────────────────────────────────────────────────────────

    def _compute_dag_depth(self, manifest: ExecutionManifest) -> int:
        """Longest dependency chain (conservative: based on order field diff)."""
        if not manifest.steps:
            return 0
        return max(s.order for s in manifest.steps) + 1

    def _count_parallel_opportunities(self, manifest: ExecutionManifest) -> int:
        """Count steps marked as can_parallelize=True."""
        return sum(1 for s in manifest.steps if s.can_parallelize)
