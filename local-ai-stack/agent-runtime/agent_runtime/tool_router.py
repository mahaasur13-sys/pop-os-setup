import subprocess


def execute_tools(plan: dict):
    # minimal deterministic executor
    steps = plan.get("steps", [])

    results = []

    for step in steps:
        if step.get("type") == "shell":
            cmd = step.get("cmd")
            out = subprocess.getoutput(cmd)
            results.append(out)

    return results
