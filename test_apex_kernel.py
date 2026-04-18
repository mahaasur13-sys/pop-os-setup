#!/usr/bin/env python3
import sys
sys.path.insert(0, 'agents')
sys.path.insert(0, '.')

from apex_execution_kernel import APEXExecutionKernel, ExecutionState

kernel = APEXExecutionKernel(dry_run=True)

tests = [
    ('ci failed: ruff F401 agents/tools_adapter.py', 'DEVOPS'),
    ('build and test all modules', 'SINGLE'),
    ('scan workspace for unused imports', 'SWARM'),
    ('rm -rf /home/workspace/agents', 'VETOED'),
]

print('=== APEX Kernel Tests ===')
all_pass = True
for task, expected in tests:
    r = kernel.execute(task)
    # Get fresh verdict for display (kernel stores enum, not tuple)
    pv, pe = kernel.kernel.evaluate(
        {"task_id": r.task_id, "task_text": task, "plan": r.plan}, {}
    )
    reason = pe[0].reason if pe else "ok"
    verdict_val = pv.value
    state = r.execution_state.value
    ok = (verdict_val == 'allow' and state == 'completed') or (verdict_val in ('block', 'veto') and expected == 'VETOED')
    status = 'PASS' if ok else 'FAIL'
    print(f'[{status}] expected={expected} | verdict={verdict_val} | state={state}')
    print(f'  task: {task[:60]}')
    print(f'  plan: {len(r.plan)} steps | audit={r.audit_entry_id[:12]} | duration={r.duration_ms:.1f}ms')
    if not ok:
        all_pass = False

valid, errs = kernel.audit_graph.verify_chain()
print(f'\n[APEX] Chain valid: {valid} | Entries: {len(kernel.audit_graph.nodes)}')
print(f'All tests: {"PASS" if all_pass else "FAIL"}')
