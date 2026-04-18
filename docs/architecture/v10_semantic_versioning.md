# RFC-001: v10 — Versioned Semantic System

**Status:** Draft  
**Layer:** Architecture Extension  
**Replaces:** v9.10 (semantic identity without versioning)  
**Target:** v10.0 implementation

---

## 1. Problem Statement

### 1.1 Current State (v9.10)

v9.10 фиксирует **semantic identity** — система понимает, что событие означает, но **не отслеживает** его версию во времени.

**v9.10 фиксирует:**
- Semantic meaning of events
- Invariant constraints
- Execution semantics

**v9.10 НЕ умеет:**
- Различать версии одного артефакта во времени
- Эволюционировать схемы без потери совместимости
- Гарантировать backward compatibility при миграциях
- Воспроизводить поведение на разных версиях одной сущности
- Достигать консенсуса по версии между узлами

### 1.2 The Gap

```
v9.10: "Что это значит?"
v10:   "Что это значило тогда И что значит сейчас И как связано?"
```

Переход из класса **semantic consistency** → **semantic evolution**.

---

## 2. Design Goals

| Goal | Description |
|------|-------------|
| **Backward Compatibility** | older versions remain valid after upgrade |
| **Deterministic Replay** | same sequence produces same result across versions |
| **Cross-node Version Consensus** | all nodes agree on version state |
| **Schema Evolution without Drift** | schemas evolve predictably |
| **Version-aware Invariants** | constraints checked against correct version context |

---

## 3. Core Model

### 3.1 SemanticVersion

```yaml
SemanticVersion:
  major: uint  # breaking semantic identity change
  minor: uint  # compatible semantic extension
  patch: uint  # non-semantic change (fix, optimization)

  # Computed properties:
  breaking?: bool    # major > 0
  compatible?: bool  # minor increased, major same
  comparable?: bool  # full tuple equality
```

**Semantics:**
- `major:breaking` — семантическая идентичность изменилась; старые events несовместимы
- `minor:extension` — добавлена семантика, старые events остаются совместимыми
- `patch:fix` — внутреннее исправление, семантика unchanged

### 3.2 VersionedEvent

```yaml
VersionedEvent:
  base: Event           # from v9.10
  version: SemanticVersion  # schema version at creation
  schema_hash: string   # SHA-256(base.schema)

  # Lineage tracking:
  migrated_from?: SemanticVersion  # if this event was migrated
  migration_path: [SemanticVersion]  # history of migrations
```

### 3.3 Version Semantics Table

| Change Type | Rule | Compatibility |
|-------------|------|---------------|
| `PATCH` | Same semantics, internal fix | Full backward |
| `MINOR` | Compatible semantic extension | Backward compatible |
| `MAJOR` | Breaking semantic identity | Incompatible (requires migration) |

---

## 4. Schema Evolution Engine

### 4.1 Schema Hash Tracking

```yaml
SchemaEvolution:
  schema_registry: Map[schema_hash, SchemaDefinition]
  
  # Each schema has:
  hash: string          # SHA-256(structure + constraints)
  version: SemanticVersion
  fields: [FieldDefinition]
  constraints: [Constraint]
  migration_to: Map[target_hash, MigrationFunction]
```

### 4.2 Migration Functions

**Critical:** Migrations MUST be **bidirectional** for replay.

```yaml
Migration_v1_to_v2:
  name: "transform_v1_to_v2"
  direction: bidirectional
  
  forward:
    input: Event_v1
    output: Event_v2
  
  backward:
    input: Event_v2
    output: Event_v1

  # Invariant: forward(backward(x)) == x
  # Invariant: backward(forward(x)) == x
```

### 4.3 Schema Compatibility Matrix

```
v1 → v2: if minor or patch
v1 → v3: if migrations exist for v1→v2 and v2→v3
v1 → vN: compose migrations
MAJOR jump: NOT allowed without explicit migration
```

---

## 5. Replay Across Versions (CRITICAL)

### 5.1 The Problem

Events are created with one version, replayed with another. Without proper handling, invariants break.

### 5.2 Migration Pipeline

```
Event(original_version)
  → migrate_to(target_version)
  → Event(target_version)
  → execute
  → result

Result can be:
  → back_migrate_to(original_version)
  → Event(original_version)
```

### 5.3 Guarantees

```
INV-5.3.1: Event(v1).migrate(v2).execute() 
           ≡ Event(v2).execute()

INV-5.3.2: migrated_event.schema_hash == target_version

INV-5.3.3: replay_invariants MUST hold across ALL versions
           (checked by validator before replay)
```

### 5.4 Version Resolution

```
resolve_version(event, target):
  if event.version == target: return event
  if can_migrate(event.version, target):
    return migrate(event, target)
  else:
    raise VersionIncompatibleError(event.version, target)
```

---

## 6. Integration Points

### 6.1 Memory ← v10

```
Memory.snapshot():
  NOW: save current state
  v10: save state + version_metadata + schema_hash
  
Memory.replay():
  NOW: restore state
  v10: restore + migrate to current version
  
Memory.gc():
  NOW: delete old snapshots
  v10: version-aware retention + compatibility check
```

### 6.2 Loop ← v10

```
Planner.plan():
  NOW: generate steps
  v10: generate steps + annotate with version_requirements
  
Executor.execute():
  NOW: run step
  v10: check version_gates before execution
  
Validator.validate():
  NOW: check invariants
  v10: check versioned_invariants
```

### 6.3 Sandbox ← v10

```
Sandbox.run(event):
  NOW: execute in isolation
  v10: execute + verify version_gate + log schema_hash
  
Sandbox.rollback():
  NOW: revert state
  v10: revert + restore correct version
```

### 6.4 Swarm ← v10

```
Coordinator.sync():
  NOW: broadcast state
  v10: broadcast + version_consensus + schema_hash
  
Worker.execute():
  NOW: local execution
  v10: local + version_check + migration if needed
  
Consensus.reach():
  NOW: agree on state
  v10: agree on state + version + schema
```

---

## 7. New Invariants

### INV-7.1: VERSION_COMPATIBILITY

```
∀ event, version:
  event.version IS compatible_with(registry[event.schema_hash])
```

### INV-7.2: SCHEMA_MIGRATION_DETERMINISM

```
∀ schema_a, schema_b, migration_path:
  migrate(migrate(event, a→b), b→a) == event
  
  AND:
  migrate(event, a→b) == deterministic(event, a, b)
```

### INV-7.3: REPLAY_CROSS_VERSION_EQUIVALENCE

```
∀ event_v1, target_version:
  execute(migrate(event_v1, target)) 
    ≡ execute(event_at_target_version)
```

### INV-7.4: VERSION_CONSENSUS

```
∀ nodes [n1, n2, ...]:
  latest_version(node) → consensus →
  ∀ node: agreed_version IS same
```

---

## 8. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Version drift across nodes** | HIGH | Version consensus protocol in Swarm |
| **Migration non-determinism** | CRITICAL | Determinism tests, formal verification |
| **Replay divergence** | CRITICAL | Cross-version test suite, invariant checks |
| **Schema hash collision** | LOW | Use SHA-256 + namespace prefix |
| **Circular migrations** | MEDIUM | Migration DAG validation |
| **Upgrade race condition** | MEDIUM | Version gating with coordination |

### 8.1 Mitigation Details

**Version drift:**
- Swarm introduces version heartbeat
- Quorum-based version agreement
- Rollback if consensus lost

**Migration determinism:**
- Pure functions only (no side effects)
- Formal property tests
- 100% coverage of migration paths

**Replay divergence:**
- Golden test vectors per version
- Automated regression suite
- CI gates on version compatibility

---

## 9. Rollout Plan

### Phase 1: v10.0 — Version Metadata Only

```
Deliverables:
- SemanticVersion model
- VersionedEvent model
- schema_hash tracking (read-only)
- Version compatibility check (no migration)

Changes:
- Memory: add version to snapshots
- Events: add version metadata
- Validation: check version compatibility
```

### Phase 2: v10.1 — Schema Evolution

```
Deliverables:
- Schema registry
- Migration function framework
- Bidirectional migrations
- Compatibility matrix

Changes:
- SchemaEvolution engine
- Migration API
- Schema validation
```

### Phase 3: v10.2 — Cross-Version Replay

```
Deliverables:
- Full replay pipeline
- Version resolution engine
- Cross-version test suite
- Consensus protocol

Changes:
- Replay with migration
- Version consensus in Swarm
- Invariant validation across versions
```

---

## 10. What NOT to do now

```
❌ DO NOT write implementation code
❌ DO NOT create artifact registry
❌ DO NOT modify Runtime
❌ DO NOT add persistence layer
❌ DO NOT integrate with external systems
```

**Current scope:** RFC only. Implementation follows after approval.

---

## 11. Summary

v10 introduces **semantic evolution** on top of v9.10's **semantic identity**:

```
v9.10: "What does this mean?"
v10:   "What did this mean when created, what does it mean now, 
        how did it evolve, and how do I ensure compatibility?"
```

**Key principles:**
1. Every event has a version
2. Every version can migrate bidirectionally  
3. Replay must be equivalent across versions
4. Nodes must agree on version state

**Next step:** Review RFC, identify gaps, produce v10.0 implementation plan.