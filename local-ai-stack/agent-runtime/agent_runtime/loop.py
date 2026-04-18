from agent_runtime.engine import plan
from agent_runtime.memory import store_result
from agent_runtime.tool_router import execute_tools


def run_task(payload: dict):
    # 1. PLAN
    plan_result = plan(payload)

    # 2. EXECUTE
    execution_result = execute_tools(plan_result)

    # 3. OBSERVE
    observation = {
        "input": payload,
        "plan": plan_result,
        "output": execution_result
    }

    # 4. STORE
    store_result(observation)

    return observation
