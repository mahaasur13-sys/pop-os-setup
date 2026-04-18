#!/usr/bin/env python3
import sys
sys.path.insert(0, 'agents')
sys.path.insert(0, '.')

from policy_kernel import PolicyKernel
pk = PolicyKernel()
pv, pe = pk.evaluate({'task_text': 'rm -rf /home/workspace/agents', 'plan': []}, {})
print('verdict:', pv.value)
for e in pe:
    print('  rule:', e.rule_name, 'passed:', e.passed, 'reason:', e.reason)

from immutable_audit_graph import ImmutableAuditGraph
iag = ImmutableAuditGraph()
print('verify_chain:', iag.verify_chain())
print('nodes attr:', hasattr(iag, 'nodes'))
