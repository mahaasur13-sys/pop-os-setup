#!/bin/bash
#========================================================
# pop-os-setup v6 — Control Plane API (FastAPI)
#========================================================
# Minimal production-ready control plane for v6.
# Single file — no external dependencies for core API.
#========================================================

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Optional, Literal
from contextlib import asynccontextmanager
import asyncio
import json
import uuid
from datetime import datetime, timezone

app = FastAPI(title="pop-os-setup Control Plane", version="6.0.0")

# ─── MODELS ────────────────────────────────────────────────────────────────────

class Manifest(BaseModel):
    name: str
    version: str
    sha256: str
    profile: str = "workstation"

class RunRequest(BaseModel):
    manifest: Manifest
    agent_id: Optional[str] = None
    replay_from: Optional[str] = None

class EventRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    type: str
    node: Optional[str] = None
    agent_id: Optional[str] = None
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict = Field(default_factory=dict)

class AgentRegister(BaseModel):
    agent_id: str
    hostname: str
    platform: str
    tags: dict = Field(default_factory=dict)

# ─── IN-MEMORY STORE (replace with Postgres in production) ────────────────────

runs: dict[str, dict] = {}
events: list[EventRecord] = []
agents: dict[str, dict] = {}
active_connections: list[WebSocket] = []

# ─── WEBSOCKET BROADCAST ───────────────────────────────────────────────────────

async def broadcast(event: EventRecord):
    data = json.dumps(event.model_dump(), default=str)
    dead = []
    for ws in active_connections:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_connections.remove(ws)

# ─── ROUTES ────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "6.0.0", "agents": len(agents)}

@app.post("/agents/register")
async def register_agent(agent: AgentRegister):
    agents[agent.agent_id] = agent.model_dump()
    await broadcast(EventRecord(
        run_id="", type="AGENT_REGISTERED", agent_id=agent.agent_id,
        payload={"hostname": agent.hostname, "tags": agent.tags}
    ))
    return {"agent_id": agent.agent_id, "registered": True}

@app.get("/agents")
async def list_agents():
    return list(agents.values())

@app.post("/runs")
async def create_run(req: RunRequest):
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run = {
        "run_id": run_id,
        "status": "created",
        "manifest": req.manifest.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nodes_total": 0,
        "nodes_completed": 0,
        "nodes_failed": 0,
    }
    runs[run_id] = run

    await broadcast(EventRecord(
        run_id=run_id, type="RUN_STARTED",
        payload={"manifest": req.manifest.model_dump(), "replay_from": req.replay_from}
    ))
    return {"run_id": run_id, "status": "created"}

@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    if run_id not in runs:
        raise HTTPException(404, "Run not found")
    return runs[run_id]

@app.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, after_ts: Optional[str] = None):
    query = [e for e in events if e.run_id == run_id]
    if after_ts:
        query = [e for e in query if e.ts > after_ts]
    return [e.model_dump() for e in query]

@app.websocket("/ws/{run_id}")
async def websocket_endpoint(ws: WebSocket, run_id: str):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            event = json.loads(data)
            event_record = EventRecord(**event)
            events.append(event_record)
            # Update run state
            if event_record.run_id in runs:
                run = runs[event_record.run_id]
                if event_record.type == "NODE_COMPLETED":
                    run["nodes_completed"] += 1
                elif event_record.type == "NODE_FAILED":
                    run["nodes_failed"] += 1
                elif event_record.type == "RUN_COMPLETED":
                    run["status"] = "completed"
                elif event_record.type == "RUN_FAILED":
                    run["status"] = "failed"
            # Broadcast to other clients
            await broadcast(event_record)
    except WebSocketDisconnect:
        active_connections.remove(ws)

@app.post("/runs/{run_id}/replay")
async def replay_run(run_id: str, from_node: Optional[str] = None, mode: Literal["failed", "diff", "node"] = "failed"):
    if run_id not in runs:
        raise HTTPException(404, "Run not found")
    replay_id = f"replay_{uuid.uuid4().hex[:8]}"
    await broadcast(EventRecord(
        run_id=run_id, type="REPLAY_INITIATED",
        payload={"replay_id": replay_id, "from_node": from_node, "mode": mode}
    ))
    return {"replay_id": replay_id, "mode": mode, "initiated": True}
