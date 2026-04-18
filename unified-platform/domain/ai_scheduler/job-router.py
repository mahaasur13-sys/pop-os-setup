#!/usr/bin/env python3
"""
GPU Job Router — MANDATORY Gateway for All GPU Workloads
=========================================================
ACOS ISOLATION: This module contains NO infra dependencies.
Slurm is the GPU authority. Ray is compute executor only.

FORBIDDEN PATTERNS (enforced by CI):
    ✗ ray.init() with GPU args in non-router code
    ✗ direct CUDA_VISIBLE_DEVICES set
    ✗ any GPU allocation bypassing job-router

Usage:
    python job-router.py submit --script train.sh --partition gpu --gpus 1
    python job-router.py status --job-id 12345
    python job-router.py cancel --job-id 12345
"""

import argparse
import os
import subprocess
import sys
import time
import json
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════

SLURM_PARTITIONS = {
    "gpu": {"nodes": "rtx3060", "gres": "gpu:rtx3060:1", "default": True},
    "compute": {"nodes": "compute-*", "gres": None, "default": False},
    "edge": {"nodes": "rk3576-*", "gres": None, "default": False},
}

RAY_PARTITIONS = {
    "head": {"slurm_partition": "gpu", "cpus": 4, "gpus": 1},
    "worker": {"slurm_partition": "gpu", "cpus": 4, "gpus": 1},
}

GPU_SCHEDULER_LOG = Path("/var/log/job-router.log")
GPU_SCHEDULER_LOCK = Path("/var/lock/job-router.lock")

# ══════════════════════════════════════════════════════════════════════
# EXCEPTION
# ══════════════════════════════════════════════════════════════════════

class JobRouterError(Exception):
    """Base exception for job-router."""
    pass

class GPUAllocationError(JobRouterError):
    """Raised when GPU allocation fails."""
    pass

# ══════════════════════════════════════════════════════════════════════
# SLURM BRIDGE
# ══════════════════════════════════════════════════════════════════════

def slurm_submit(script: str, partition: str = "gpu", gpus: int = 1,
                nodes: int = 1, ntasks: int = 1, **kwargs) -> str:
    """
    Submit job to Slurm (GPU authority).
    
    Args:
        script: Path to job script
        partition: Slurm partition (gpu|compute|edge)
        gpus: Number of GPUs requested
        nodes: Number of nodes
        ntasks: Tasks per node
    
    Returns:
        str: Slurm job ID
    
    Raises:
        GPUAllocationError: If GPU request fails
    """
    if partition not in SLURM_PARTITIONS:
        raise GPUAllocationError(f"Unknown partition: {partition}")
    
    if gpus > 0 and partition != "gpu":
        raise GPUAllocationError(f"GPU request on non-gpu partition '{partition}'. Use --partition=gpu")
    
    cmd = [
        "sbatch",
        "--partition", partition,
        "--nodes", str(nodes),
        "--ntasks", str(ntasks),
        "--gres", f"gpu:rtx3060:{gpus}" if gpus > 0 else None,
        "--output", f"/tmp/slurm-%j.out",
        "--error", f"/tmp/slurm-%j.err",
        "--wait",
        script
    ]
    cmd = [c for c in cmd if c is not None]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise GPUAllocationError(f"Slurm submission failed: {result.stderr}")
    
    # Parse job ID from "Submitted batch job 12345"
    for line in result.stdout.splitlines():
        if "Submitted batch job" in line:
            job_id = line.split()[-1]
            _log(f"Job submitted: {job_id}")
            return job_id
    
    raise GPUAllocationError(f"Could not parse job ID from: {result.stdout}")

def slurm_status(job_id: str) -> dict:
    """Get Slurm job status."""
    result = subprocess.run(
        ["sacct", "-j", job_id, "--json", "-n"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"job_id": job_id, "state": "UNKNOWN", "error": result.stderr}
    
    try:
        data = json.loads(result.stdout)
        jobs = data.get("jobs", [])
        if jobs:
            job = jobs[0]
            return {
                "job_id": job.get("job_id"),
                "state": job.get("state", "UNKNOWN"),
                "exit_code": job.get("exit_code"),
            }
    except (json.JSONDecodeError, IndexError):
        pass
    
    return {"job_id": job_id, "state": "UNKNOWN"}

def slurm_cancel(job_id: str) -> bool:
    """Cancel a Slurm job."""
    result = subprocess.run(["scancel", job_id], capture_output=True, text=True)
    return result.returncode == 0

# ══════════════════════════════════════════════════════════════════════
# RAY EXECUTOR (via Slurm wrapper)
# ══════════════════════════════════════════════════════════════════════

RAY_HEAD_SCRIPT = """#!/bin/bash
# Ray head node launched via Slurm
# DO NOT run Ray directly with GPU args
# All GPU allocation MUST go through job-router

set -e
module load cuda/12.4
module load cudnn/9.0

srun ray start --head --node-ip-address=$SLURM_JOB_NODELIST --port=6379 --redis-password=ray_cluster
"""

RAY_WORKER_SCRIPT = """#!/bin/bash
# Ray worker launched via Slurm
# DO NOT run Ray directly with GPU args
# All GPU allocation MUST go through job-router

set -e
module load cuda/12.4
module load cudnn/9.0

RAY_HEAD_IP=$1
srun ray start --address=$RAY_HEAD_IP:6379 --redis-password=ray_cluster
"""

def ray_submit(script: str, head_ip: Optional[str] = None, **kwargs) -> str:
    """
    Submit Ray job via Slurm wrapper.
    Ray workers are allocated by Slurm, not by direct CUDA_VISIBLE_DEVICES.
    """
    if head_ip:
        wrapper_script = RAY_WORKER_SCRIPT
        cmd = ["bash", "-c", wrapper_script, "--", head_ip]
    else:
        wrapper_script = RAY_HEAD_SCRIPT
        cmd = ["bash", "-c", wrapper_script]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise JobRouterError(f"Ray submission failed: {result.stderr}")
    
    _log(f"Ray job submitted via Slurm")
    return "RAY-JOB-QUEUED"

# ══════════════════════════════════════════════════════════════════════
# ACOS WORKLOADS (pure compute, no infra imports)
# ══════════════════════════════════════════════════════════════════════

def acos_submit(script: str, **kwargs) -> str:
    """
    Submit ACOS workload (pure computation, no infra deps).
    ACOS modules MUST NOT import terraform/kubernetes/infra.
    """
    # Verify ACOS isolation
    with open(script) as f:
        content = f.read()
    
    FORBIDDEN_IMPORTS = ["terraform", "ansible", "kubernetes", "infra", "k8s", "kubectl"]
    violations = [imp for imp in FORBIDDEN_IMPORTS if f"import {imp}" in content or f"from {imp}" in content]
    
    if violations:
        raise JobRouterError(
            f"ACOS isolation violation in {script}: "
            f"forbidden imports found: {violations}. "
            f"ACOS modules must be pure computation."
        )
    
    return slurm_submit(script, partition="gpu", **kwargs)

# ══════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════

def _log(msg: str):
    """Log to stdout and file."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] JOB-ROUTER: {msg}"
    print(line, flush=True)
    try:
        GPU_SCHEDULER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GPU_SCHEDULER_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def acquire_lock() -> bool:
    """Acquire exclusive lock for job-router operations."""
    try:
        GPU_SCHEDULER_LOCK.parent.mkdir(parents=True, exist_ok=True)
        if GPU_SCHEDULER_LOCK.exists():
            return False
        GPU_SCHEDULER_LOCK.touch()
        return True
    except Exception:
        return False

def release_lock():
    """Release job-router lock."""
    try:
        GPU_SCHEDULER_LOCK.unlink(missing_ok=True)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def cmd_submit(args):
    """Submit a GPU job."""
    if not acquire_lock():
        print("ERROR: Another job-router instance is running", file=sys.stderr)
        sys.exit(1)
    
    try:
        if args.workload == "slurm":
            job_id = slurm_submit(
                script=args.script,
                partition=args.partition,
                gpus=args.gpus,
                nodes=args.nodes,
            )
            print(f"Slurm job submitted: {job_id}")
        
        elif args.workload == "ray":
            job_id = ray_submit(
                script=args.script,
                head_ip=args.ray_head_ip,
            )
            print(f"Ray job submitted: {job_id}")
        
        elif args.workload == "acos":
            job_id = acos_submit(
                script=args.script,
                gpus=args.gpus,
            )
            print(f"ACOS job submitted: {job_id}")
        
        else:
            print(f"ERROR: Unknown workload type: {args.workload}", file=sys.stderr)
            sys.exit(1)
        
        print(f"Job ID: {job_id}")
    
    finally:
        release_lock()

def cmd_status(args):
    """Check job status."""
    if args.workload == "slurm":
        status = slurm_status(args.job_id)
        print(json.dumps(status, indent=2))
    else:
        print(f"Status not implemented for {args.workload}", file=sys.stderr)
        sys.exit(1)

def cmd_cancel(args):
    """Cancel a job."""
    if args.workload == "slurm":
        success = slurm_cancel(args.job_id)
        if success:
            print(f"Job {args.job_id} cancelled")
        else:
            print(f"Failed to cancel job {args.job_id}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Cancel not implemented for {args.workload}", file=sys.stderr)
        sys.exit(1)

def cmd_list(args):
    """List running jobs."""
    result = subprocess.run(
        ["squeue", "--json"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            jobs = data.get("jobs", [])
            print(f"Running jobs: {len(jobs)}")
            for job in jobs[:10]:
                print(f"  {job.get('job_id')}: {job.get('name')} [{job.get('state')}]")
        except json.JSONDecodeError:
            print(result.stdout)
    else:
        print("squeue not available or no running jobs")

def main():
    parser = argparse.ArgumentParser(
        description="GPU Job Router — MANDATORY gateway for all GPU workloads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit GPU training job via Slurm
  python job-router.py submit --workload slurm --script train.sh --partition gpu --gpus 1
  
  # Submit Ray AI job
  python job-router.py submit --workload ray --script ray_train.py --ray-head-ip 10.0.0.1
  
  # Submit ACOS workload (pure computation, isolated)
  python job-router.py submit --workload acos --script acos_eval.py --gpus 1
  
  # Check status
  python job-router.py status --workload slurm --job-id 12345
  
  # Cancel job
  python job-router.py cancel --workload slurm --job-id 12345

RULES:
  ✗ All GPU workloads MUST go through job-router
  ✗ Ray workers MUST be allocated via Slurm
  ✗ ACOS modules MUST NOT import infra dependencies
  ✗ Direct CUDA_VISIBLE_DEVICES manipulation is forbidden
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # submit
    p_submit = subparsers.add_parser("submit", help="Submit a GPU job")
    p_submit.add_argument("--workload", choices=["slurm", "ray", "acos"], required=True,
                         help="Workload type (slurm=batch, ray=AI, acos=pure compute)")
    p_submit.add_argument("--script", required=True, help="Path to job script")
    p_submit.add_argument("--partition", default="gpu", choices=list(SLURM_PARTITIONS.keys()),
                         help="Slurm partition")
    p_submit.add_argument("--gpus", type=int, default=1, help="Number of GPUs")
    p_submit.add_argument("--nodes", type=int, default=1, help="Number of nodes")
    p_submit.add_argument("--ntasks", type=int, default=1, help="Tasks per node")
    p_submit.add_argument("--ray-head-ip", help="Ray head IP (for worker jobs)")
    p_submit.set_defaults(func=cmd_submit)
    
    # status
    p_status = subparsers.add_parser("status", help="Check job status")
    p_status.add_argument("--workload", choices=["slurm", "ray", "acos"], required=True)
    p_status.add_argument("--job-id", required=True, help="Job ID")
    p_status.set_defaults(func=cmd_status)
    
    # cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel a job")
    p_cancel.add_argument("--workload", choices=["slurm", "ray", "acos"], required=True)
    p_cancel.add_argument("--job-id", required=True, help="Job ID")
    p_cancel.set_defaults(func=cmd_cancel)
    
    # list
    p_list = subparsers.add_parser("list", help="List running jobs")
    p_list.add_argument("--workload", choices=["slurm", "ray", "acos"], default="slurm")
    p_list.set_defaults(func=cmd_list)
    
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
