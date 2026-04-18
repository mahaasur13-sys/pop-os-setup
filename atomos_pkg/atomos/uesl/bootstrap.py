"""UESL v1 — Bootstrap: pre-import all submodules to prevent circular import chains."""
import importlib
import enum as _enum
import dataclasses as _dc
import typing as _typing
import abc as _abc
import time as _time
import hashlib as _hashlib

# Must be first: standard library only
import enum
import dataclasses
import typing
import abc

# Load submodules first (bypass package __init__.py chain)
importlib.import_module("atomos.uesl.types")
importlib.import_module("atomos.drl.message")
importlib.import_module("atomos.drl.transport")
importlib.import_module("atomos.drl.failures")
importlib.import_module("atomos.drl.partition")
importlib.import_module("atomos.drl.clock")
importlib.import_module("atomos.drl.gateway")
importlib.import_module("atomos.runtime.ccl_v1")
importlib.import_module("atomos.uesl.adapter")
importlib.import_module("atomos.uesl.state")
importlib.import_module("atomos.uesl.engine")

# Re-export public symbols for convenience
from atomos.uesl.semtypes import (
    ExecutionResult, ContractDecision, PartitionState,
    ExecutionContract, UESLEvent, UESLEventType,
)
from atomos.uesl.engine import UESLEngine
from atomos.uesl.adapter import DRLToCCLAdapter
from atomos.uesl.statestore import UESLState, UESLSnapshot
from atomos.drl.message import DRLMessage
from atomos.drl.gateway import DRLGateway
from atomos.drl.transport import DRLTransportLayer, TransportConfig
from atomos.drl.failures import FailureEngine, FailureConfig
from atomos.drl.partition import PartitionModel, PartitionConfig
from atomos.drl.clock import DRLClock, ClockType
from atomos.runtime.ccl_v1 import (
    QuorumContract, InvariantEngine, TrackerSnapshot,
    AckDecision, AckSemantic, StateMachineDSL,
)
