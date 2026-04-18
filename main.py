#!/usr/bin/env python3
"""
TAAR — Tool-Augmented Agent Runtime
Entry point: TASK → GRAPH → EXEC → RESULT

Usage:
    python main.py "your task here"
    python main.py --interactive
    python main.py --test
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

# Add agents/ to path AND workspace root (for 'from agents.x' imports in devops_agent)
_WORKSPACE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_WORKSPACE / "agents"))   # for 'from langgraph_core'
sys.path.insert(0, str(_WORKSPACE))               # for 'from agents.x' in devops_agent

from langgraph_core import run_task, get_compiled_graph, TOOL_REGISTRY
from memory import get_memory, VectorMemory
from swarm import SwarmEngine
from devops_agent import DevOpsAgent
from orchestrator import TAAROrchestrator
from control_plane import ControlPlane, ExecutionMode, Decision

# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

def run_interactive():
    """Interactive REPL loop."""
    session_id = f"taar-{uuid.uuid4().hex[:8]}"
    mem = get_memory(session_id=session_id)

    print("🧠 TAAR Interactive Mode")
    print("Type 'exit' to quit, 'history' to see memory, 'plan' to see last plan\n")

    while True:
        try:
            user_input = input(">>> ").strip()
        except EOFError:
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break

        if user_input.lower() == "history":
            records = mem.get_history(limit=20)
            for r in records:
                print(f"[{r.role}] {r.content[:120]}")
            continue

        if user_input.lower() == "plan":
            print("Use run_task() to see plan structure.")
            continue

        # Store user message
        mem.add_user(user_input)

        # Run task
        print(f"Running TAAR graph...")
        result = run_task(user_input, max_iterations=20)

        # Store assistant response
        final = result.get("final_result", result.get("error", "No result"))
        mem.add_assistant(final)

        # Output
        print(f"\n{'='*60}")
        print("RESULT:")
        print(final)
        print(f"{'='*60}\n")

        # Show plan summary
        plan = result.get("plan", [])
        if plan:
            done = sum(1 for s in plan if s.get("status") == "done")
            print(f"Plan: {done}/{len(plan)} steps completed")


def run_single_task(task: str, max_iterations: int = 20, verbose: bool = False,
                    use_swarm: bool = False, swarm_workers: int | None = None):
    """Run task as a full TAAR v4 Mission."""
    from taar_os import TAAR_OS

    session_id = f"taar-{uuid.uuid4().hex[:8]}"
    print(f"🎯 Mission: {task}")
    print(f"📋 Session: {session_id}")
    print(f"🧠 OS: TAAR v4 Mission Execution OS\n")

    os_instance = TAAR_OS(session_id=session_id)
    result = os_instance.run(task, verbose=verbose)

    print(f"\n📊 Mission: {result.mission['mission_id']}, status={result.state['status']}")
    print(f"📊 Graphs: completed={result.state['completed']}, failed={result.state['failed']}")
    print(f"⏱  Elapsed: {result.resource_usage.get('elapsed_s', '?')}s")
    print(f"🧠 Policy evolutions: {result.policy_evolution.get('total_evolutions', 0)}")
    print(f"🗃  Episodes stored: {os_instance.episodic.summarize().get('total', 0)}")
    print(f"\n{'='*60}")
    print("RESULT:", result.final_result)
    print(f"{'='*60}")

    if verbose:
        import json
        print(json.dumps({
            "mission": result.mission,
            "graphs": result.task_graphs,
            "state": result.state,
            "policy_evolution": result.policy_evolution,
            "execution_log": result.execution_log,
        }, indent=2, default=str))

    return {"status": result.state["status"], "mission": result.mission}


def test_tools():
    """Verify all registered tools work."""
    print("🧪 Testing TAAR tool registry...\n")

    from tools_adapter import get_llm, register_all_tools

    # Re-register (ensure clean state)
    from langgraph_core import TOOL_REGISTRY
    register_all_tools(TOOL_REGISTRY)

    tools = TOOL_REGISTRY.list_tools()
    print(f"Registered tools: {tools}\n")

    results = {}
    for tool_name in tools:
        try:
            # Minimal smoke test for each tool
            if tool_name == "bash":
                r = TOOL_REGISTRY.execute("bash", {"cmd": "echo 'hello'"})
            elif tool_name == "read_file":
                r = TOOL_REGISTRY.execute("read_file", {"target_file": "/etc/hostname"})
            elif tool_name == "write_file":
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
                tmp.close()
                r = TOOL_REGISTRY.execute("write_file", {"target_file": tmp.name, "content": "test"})
                r = f"wrote to {tmp.name}"
            elif tool_name == "grep":
                r = TOOL_REGISTRY.execute("grep", {"location": "USER", "query": "import"})
            elif tool_name == "list_files":
                r = TOOL_REGISTRY.execute("list_files", {"path": "/home/workspace"})
            else:
                r = "skip (needs args)"
            results[tool_name] = f"✅ {r}"
        except Exception as e:
            results[tool_name] = f"❌ {e}"

    for tool, result in results.items():
        print(f"  {tool}: {result}")

    print("\n🧪 Testing LLM (Ollama)...")
    try:
        llm = get_llm()
        resp = llm.invoke([{"role": "user", "content": "Say 'hello' in 3 words"}])
        print(f"  LLM: ✅ {resp.content}")
    except Exception as e:
        print(f"  LLM: ❌ {e}")
        print("  (Ollama may not be running — start with: ollama serve)")

    print("\n🧪 Testing Memory...")
    try:
        mem = get_memory(session_id="test-001")
        mem.add_user("test message")
        history = mem.get_history()
        print(f"  Memory: ✅ {len(history)} records, store OK")
    except Exception as e:
        print(f"  Memory: ❌ {e}")

    print("\n✅ Tool test complete.")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TAAR — Tool-Augmented Agent Runtime")
    parser.add_argument("task", nargs="?", default=None, help="Task to execute")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--test", "-t", action="store_true", help="Run tool tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output (full JSON)")
    parser.add_argument("--max-iterations", type=int, default=20, help="Max graph iterations")
    parser.add_argument("--session-id", type=str, default=None, help="Session ID for memory")
    parser.add_argument("--model", type=str, default=None, help="Ollama model to use")
    parser.add_argument("--swarm", action="store_true", help="Use SwarmEngine for parallel execution")

    args = parser.parse_args()

    if args.model:
        import os
        os.environ["OLLAMA_MODEL"] = args.model

    if args.test:
        test_tools()
    elif args.interactive:
        run_interactive()
    elif args.task:
        run_single_task(args.task, max_iterations=args.max_iterations, verbose=args.verbose,
                        use_swarm=args.swarm)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()