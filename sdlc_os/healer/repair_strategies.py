"""Repair strategies for SDLC OS Healer Engine."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class RepairCategory(Enum):
    """Categories of repair actions."""
    MODULE_ADD = "module_add"
    MODULE_REMOVE = "module_remove"
    DEPENDENCY_FIX = "dependency_fix"
    CONFIG_PATCH = "config_patch"
    STRUCTURAL_REPAIR = "structural_repair"
    ORPHAN_LINK = "orphan_link"


class RepairPriority(Enum):
    """Priority levels for repair actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RepairStrategy:
    """
    Defines a repair strategy for a specific issue type.
    
    Attributes:
        category: The category of repair
        priority: How urgent this repair is
        reversible: Whether the repair can be safely undone
        requires_approval: Whether human approval is needed
        description: Human-readable description of the strategy
    """
    category: RepairCategory
    priority: RepairPriority
    reversible: bool
    requires_approval: bool
    description: str


class StrategyRegistry:
    """
    Registry of all known repair strategies.
    Maps issue types to available repair strategies.
    """
    
    STRATEGIES = {
        "orphan_modules": RepairStrategy(
            category=RepairCategory.ORPHAN_LINK,
            priority=RepairPriority.LOW,
            reversible=True,
            requires_approval=True,
            description="Link orphan modules to parent modules or create __init__.py"
        ),
        "unexpected_new_nodes": RepairStrategy(
            category=RepairCategory.STRUCTURAL_REPAIR,
            priority=RepairPriority.MEDIUM,
            reversible=True,
            requires_approval=True,
            description="Classify unexpected nodes and establish proper module boundaries"
        ),
        "dependency_inconsistency": RepairStrategy(
            category=RepairCategory.DEPENDENCY_FIX,
            priority=RepairPriority.HIGH,
            reversible=False,
            requires_approval=True,
            description="Reconcile import graph with actual dependency usage"
        ),
        "structural_drift": RepairStrategy(
            category=RepairCategory.STRUCTURAL_REPAIR,
            priority=RepairPriority.HIGH,
            reversible=False,
            requires_approval=True,
            description="Restore architectural integrity after significant structural changes"
        ),
        "missing_init": RepairStrategy(
            category=RepairCategory.MODULE_ADD,
            priority=RepairPriority.MEDIUM,
            reversible=True,
            requires_approval=True,
            description="Add missing __init__.py files to establish package boundaries"
        ),
        "circular_dependency": RepairStrategy(
            category=RepairCategory.DEPENDENCY_FIX,
            priority=RepairPriority.CRITICAL,
            reversible=False,
            requires_approval=True,
            description="Break circular dependencies by refactoring imports"
        ),
    }
    
    @classmethod
    def get_strategy(cls, issue_type: str) -> Optional[RepairStrategy]:
        """Get repair strategy for an issue type."""
        return cls.STRATEGIES.get(issue_type)
    
    @classmethod
    def get_all_strategies(cls) -> list[RepairStrategy]:
        """Return all registered strategies."""
        return list(cls.STRATEGIES.values())