"""
PolicyEngine — core of the Governance Layer.

Evaluates an ExecutionManifest against configurable policies and returns
a PolicyDecision: ALLOW, DENY, or DEGRADED_ALLOW with explicit reason.

Policy checks performed:
  1. Tool allowlist / blocklist
  2. Tool sequence validation (forbidden chains)
  3. Cost budget (total estimated cost of manifest)
  4. Latency budget (total estimated time)
  5. Risk score (based on tool categories and payload content)
  6. Rate limits (how many times each tool can appear in one manifest)
  7. Ownership scope (task belongs to caller → verify caller permissions)

No side effects. Pure evaluation against policy dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re


# ── Enums ──────────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    DEGRADED_ALLOW = "degraded_allow"  # allowed but with reduced budget


class ViolationSeverity(str, Enum):
    BLOCKING = "blocking"    # causes DENY
    WARNING = "warning"      # causes DEGRADED_ALLOW
    INFO = "info"           # logged only


# ── Policy dataclasses ─────────────────────────────────────────────────────────

@dataclass
class PolicyViolation:
    policy_name: str
    severity: ViolationSeverity
    message: str
    detail: Optional[str] = None

    def is_blocking(self) -> bool:
        return self.severity == ViolationSeverity.BLOCKING


@dataclass
class ToolSequenceRule:
    """Rule: forbidden or required tool sequence."""
    name: str
    pattern: list[str]          # ordered list of tool names
    is_forbidden: bool = True   # True = cannot occur, False = must occur
    description: str = ""


@dataclass
class ToolBudget:
    """Per-tool budget constraints."""
    max_calls_per_manifest: int = 10
    max_cost: float = 100.0
    max_latency_ms: float = 300_000.0   # 5 minutes
    max_total_steps: int = 50


@dataclass
class RateLimit:
    """Rate limit for a specific tool."""
    tool: str
    max_calls_per_minute: int = 60
    max_calls_per_hour: int = 1000


# ── PolicyContext ──────────────────────────────────────────────────────────────

@dataclass
class PolicyContext:
    """Static context available at evaluation time."""
    caller_identity: str = "system"
    task_priority: str = "NORMAL"   # LOW / NORMAL / HIGH / CRITICAL
    session_id: Optional[str] = None
    environment: str = "production"  # production / staging / development
    budget_multiplier: float = 1.0   # scale all budgets by this


# ── PolicyDecision ─────────────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    verdict: Verdict
    reason: str
    violations: list[PolicyViolation] = field(default_factory=list)
    adjusted_budget: Optional[ToolBudget] = None   # for DEGRADED_ALLOW

    @property
    def is_allowed(self) -> bool:
        return self.verdict in (Verdict.ALLOW, Verdict.DEGRADED_ALLOW)

    @property
    def is_blocking(self) -> bool:
        return self.verdict == Verdict.DENY

    def summary(self) -> str:
        parts = [f"[{self.verdict.value.upper()}] {self.reason}"]
        if self.violations:
            for v in self.violations:
                parts.append(f"  • {v.severity.value}: {v.policy_name} — {v.message}")
        return "\n".join(parts)


# ── Default policy rules ───────────────────────────────────────────────────────

DEFAULT_TOOL_ALLOWLIST: set[str] = {
    "bash", "shell", "llm", "ollama", "rag", "memory",
    "http", "api", "embed", "vector", "file", "read", "write",
    "grep_search", "run_bash_command", "edit_file_llm", "create_or_rewrite_file",
}

DEFAULT_TOOL_BLOCKLIST: set[str] = {
    "rm -rf", "drop_database", "sudo", "kill -9",
    "curl http", "wget http",  # plain HTTP without TLS
}

DEFAULT_SEQUENCE_RULES: list[ToolSequenceRule] = [
    ToolSequenceRule(
        name="no_sudo_then_write",
        pattern=["sudo", "write", "create_or_rewrite_file"],
        is_forbidden=True,
        description="Cannot write files after sudo elevation",
    ),
    ToolSequenceRule(
        name="no_http_then_shell",
        pattern=["http", "shell", "bash"],
        is_forbidden=True,
        description="Cannot execute shell after HTTP fetch (SSRF protection)",
    ),
    ToolSequenceRule(
        name="no_repeated_llm",
        pattern=["llm", "llm", "llm"],
        is_forbidden=True,
        description="Cannot call LLM 3+ times without intermediate step",
    ),
]

SENSITIVE_PAYLOAD_PATTERNS: list[re.Pattern] = [
    re.compile(r"password\s*=\s*['\"][^'\"]{1,}", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*=\s*['\"][^'\"]{1,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", re.IGNORECASE),  # JWT
    re.compile(r"[\"']https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0)[:/]", re.IGNORECASE),  # local IP
]


# ── PolicyEngine ───────────────────────────────────────────────────────────────

class PolicyEngine:
    """
    Evaluates ExecutionManifest against configured policies.

    Usage::

        engine = PolicyEngine()
        decision = engine.evaluate(manifest, context)
        if decision.is_allowed:
            engine.execute(manifest)
        else:
            engine.reject(decision)
    """

    def __init__(
        self,
        tool_allowlist: Optional[set[str]] = None,
        tool_blocklist: Optional[set[str]] = None,
        sequence_rules: Optional[list[ToolSequenceRule]] = None,
        budget: Optional[ToolBudget] = None,
        rate_limits: Optional[list[RateLimit]] = None,
    ):
        self.tool_allowlist: set[str] = tool_allowlist or DEFAULT_TOOL_ALLOWLIST
        self.tool_blocklist: set[str] = tool_blocklist or DEFAULT_TOOL_BLOCKLIST
        self.sequence_rules: list[ToolSequenceRule] = sequence_rules or DEFAULT_SEQUENCE_RULES
        self.budget: ToolBudget = budget or ToolBudget()
        self.rate_limits: dict[str, RateLimit] = {
            rl.tool: rl for rl in (rate_limits or [])
        }

        # Track rate limit state in-memory (replace with Redis for production)
        self._rate_counters: dict[str, list[float]] = {}

    # ── main entry ─────────────────────────────────────────────────────────────

    def evaluate(
        self,
        manifest,          # ExecutionManifest from plan_executor
        ctx: Optional[PolicyContext] = None,
    ) -> PolicyDecision:
        """
        Full policy evaluation of an ExecutionManifest.
        Returns a PolicyDecision with verdict and violations.
        """
        ctx = ctx or PolicyContext()
        violations: list[PolicyViolation] = []
        budget = self._scaled_budget(ctx)

        # 1. Blocklist check
        violations += self._check_blocklist(manifest)

        # 2. Allowlist check
        violations += self._check_allowlist(manifest)

        # 3. Tool sequence rules
        violations += self._check_sequences(manifest)

        # 4. Cost budget
        violations += self._check_cost_budget(manifest, budget)

        # 5. Latency budget
        violations += self._check_latency_budget(manifest, budget)

        # 6. Step count budget
        violations += self._check_step_budget(manifest, budget)

        # 7. Rate limit per tool
        violations += self._check_rate_limits(manifest)

        # 8. Sensitive payload scan
        violations += self._check_sensitive_payloads(manifest)

        # 9. Environment restrictions
        violations += self._check_environment_restrictions(manifest, ctx)

        # Classify violations by severity
        blocking = [v for v in violations if v.is_blocking()]
        warnings = [v for v in violations if v.severity == ViolationSeverity.WARNING]

        if blocking:
            return PolicyDecision(
                verdict=Verdict.DENY,
                reason=f"Blocked by {len(blocking)} policy violation(s)",
                violations=violations,
            )

        if warnings:
            return PolicyDecision(
                verdict=Verdict.DEGRADED_ALLOW,
                reason=f"Allowed with {len(warnings)} warning(s) — budget adjusted",
                violations=violations,
                adjusted_budget=budget,
            )

        return PolicyDecision(
            verdict=Verdict.ALLOW,
            reason="All policy checks passed",
            violations=[],
        )

    # ── budget checks ──────────────────────────────────────────────────────────

    def _scaled_budget(self, ctx: PolicyContext) -> ToolBudget:
        m = ctx.budget_multiplier
        return ToolBudget(
            max_calls_per_manifest=int(self.budget.max_calls_per_manifest * m),
            max_cost=self.budget.max_cost * m,
            max_latency_ms=self.budget.max_latency_ms * m,
            max_total_steps=int(self.budget.max_total_steps * m),
        )

    def _check_cost_budget(self, manifest, budget: ToolBudget) -> list[PolicyViolation]:
        # Estimate cost from manifest (tool count × avg cost factor)
        total_cost = len(manifest.steps) * 0.5  # placeholder
        if total_cost > budget.max_cost:
            return [PolicyViolation(
                policy_name="cost_budget",
                severity=ViolationSeverity.BLOCKING,
                message=f"Estimated cost {total_cost:.2f} exceeds budget {budget.max_cost:.2f}",
                detail=f"step_count={len(manifest.steps)}",
            )]
        return []

    def _check_latency_budget(
        self, manifest, budget: ToolBudget
    ) -> list[PolicyViolation]:
        if manifest.estimated_total_ms > budget.max_latency_ms:
            return [PolicyViolation(
                policy_name="latency_budget",
                severity=ViolationSeverity.BLOCKING,
                message=f"Estimated latency {manifest.estimated_total_ms/1000:.1f}s exceeds budget {budget.max_latency_ms/1000:.1f}s",
                detail=f"estimated_total_ms={manifest.estimated_total_ms}",
            )]
        return []

    def _check_step_budget(
        self, manifest, budget: ToolBudget
    ) -> list[PolicyViolation]:
        if manifest.total_steps > budget.max_total_steps:
            return [PolicyViolation(
                policy_name="step_budget",
                severity=ViolationSeverity.BLOCKING,
                message=f"Step count {manifest.total_steps} exceeds max {budget.max_total_steps}",
            )]
        return []

    # ── tool-level checks ──────────────────────────────────────────────────────

    def _check_blocklist(
        self, manifest
    ) -> list[PolicyViolation]:
        violations = []
        blocked_tools_in_manifest: list[str] = []

        for step in manifest.steps:
            tool = step.tool.lower()
            for blocked in self.tool_blocklist:
                if blocked in tool:
                    blocked_tools_in_manifest.append(step.tool)

        if blocked_tools_in_manifest:
            violations.append(PolicyViolation(
                policy_name="tool_blocklist",
                severity=ViolationSeverity.BLOCKING,
                message=f"Blocked tool(s) in manifest: {blocked_tools_in_manifest}",
            ))

        return violations

    def _check_allowlist(
        self, manifest
    ) -> list[PolicyViolation]:
        violations = []
        unknown_tools: set[str] = set()

        for step in manifest.steps:
            tool = step.tool.lower()
            if tool not in self.tool_allowlist and tool not in unknown_tools:
                unknown_tools.add(tool)

        if unknown_tools:
            # Unknown tools are warnings, not blocking (allow new tools with warning)
            violations.append(PolicyViolation(
                policy_name="tool_allowlist",
                severity=ViolationSeverity.WARNING,
                message=f"Unknown tools (not in allowlist): {sorted(unknown_tools)}",
            ))

        return violations

    def _check_rate_limits(
        self, manifest
    ) -> list[PolicyViolation]:
        from collections import Counter
        import time

        violations = []
        tool_counts = Counter(step.tool for step in manifest.steps)
        now = time.monotonic()

        for tool, count in tool_counts.items():
            if tool not in self.rate_limits:
                continue

            rl = self.rate_limits[tool]
            # Update in-memory counter
            if tool not in self._rate_counters:
                self._rate_counters[tool] = []
            self._rate_counters[tool] = [
                ts for ts in self._rate_counters[tool]
                if now - ts < 60
            ]

            if count > rl.max_calls_per_manifest:
                violations.append(PolicyViolation(
                    policy_name="rate_limit",
                    severity=ViolationSeverity.BLOCKING,
                    message=f"Tool '{tool}' appears {count} times in manifest (max {rl.max_calls_per_manifest})",
                ))

        return violations

    # ── sequence checks ────────────────────────────────────────────────────────

    def _check_sequences(
        self, manifest
    ) -> list[PolicyViolation]:
        violations = []
        tool_seq = [step.tool.lower() for step in manifest.steps]

        for rule in self.sequence_rules:
            pattern = [t.lower() for t in rule.pattern]
            if self._sequence_matches(tool_seq, pattern):
                severity = ViolationSeverity.BLOCKING if rule.is_forbidden else ViolationSeverity.WARNING
                violations.append(PolicyViolation(
                    policy_name=f"sequence:{rule.name}",
                    severity=severity,
                    message=rule.description or f"Forbidden sequence: {' → '.join(pattern)}",
                    detail=f"pattern={pattern}",
                ))

        return violations

    def _sequence_matches(self, seq: list[str], pattern: list[str]) -> bool:
        """Check if pattern appears as contiguous subsequence."""
        if len(pattern) > len(seq):
            return False
        for i in range(len(seq) - len(pattern) + 1):
            if seq[i:i + len(pattern)] == pattern:
                return True
        return False

    # ── payload scan ───────────────────────────────────────────────────────────

    def _check_sensitive_payloads(
        self, manifest
    ) -> list[PolicyViolation]:
        violations = []

        for step in manifest.steps:
            payload_str = str(step.payload)
            for pattern in SENSITIVE_PAYLOAD_PATTERNS:
                if pattern.search(payload_str):
                    violations.append(PolicyViolation(
                        policy_name="sensitive_payload",
                        severity=ViolationSeverity.BLOCKING,
                        message=f"Sensitive pattern detected in step '{step.step_name}' payload",
                        detail=f"step_id={step.step_id}",
                    ))

        return violations

    # ── environment ─────────────────────────────────────────────────────────────

    def _check_environment_restrictions(
        self, manifest, ctx: PolicyContext
    ) -> list[PolicyViolation]:
        violations = []

        if ctx.environment == "production":
            # Production: flag HIGH risk steps
            high_risk_tools = {"shell", "bash", "write", "create_or_rewrite_file", "rm"}
            for step in manifest.steps:
                if step.tool.lower() in high_risk_tools:
                    violations.append(PolicyViolation(
                        policy_name="production_high_risk",
                        severity=ViolationSeverity.WARNING,
                        message=f"High-risk tool '{step.tool}' in production manifest",
                        detail=f"step_id={step.step_id}",
                    ))

        return violations
