"""
Tests for event_sourcing + event_store + Lamport clock.

Covers:
- TaskEvent creation and serialization
- LamportClock monotonicity and merge
- EventStore append + read + replay
- Audit trail generation
- Global sequence across tasks
- Idempotency during replay
"""

import asyncio
import pytest
import time

from agent_runtime.event_sourcing import EventType, TaskEvent
from agent_runtime.event_store import EventStore, LamportClock


async def _make_store():
    store = EventStore("redis://localhost:6379")
    r = await store._get_redis()
    await r.flushdb()
    return store


async def _make_clock():
    clock = LamportClock("redis://localhost:6379")
    r = await clock._get_redis()
    await r.flushdb()
    return clock


class TestTaskEvent:
    def test_make_event(self):
        e = TaskEvent.make(
            task_id="t1",
            event_type=EventType.TASK_CLAIMED,
            worker_id="worker-1",
            epoch=1,
            lamport_ts=5,
        )
        assert e.task_id == "t1"
        assert e.event_type == EventType.TASK_CLAIMED
        assert e.worker_id == "worker-1"
        assert e.epoch == 1
        assert e.lamport_ts == 5
        assert e.event_id
        assert e.timestamp > 0

    def test_stream_fields_roundtrip(self):
        e = TaskEvent.make(
            task_id="t1",
            event_type=EventType.STEP_EXECUTED,
            worker_id="worker-1",
            epoch=2,
            lamport_ts=10,
            step_id="s1",
            payload={"latency_ms": 42.0, "tool": "shell"},
        )
        fields = e.to_stream_fields()
        restored = TaskEvent.from_stream_fields(fields)
        assert restored.task_id == "t1"
        assert restored.event_type == EventType.STEP_EXECUTED
        assert restored.epoch == 2
        assert restored.lamport_ts == 10
        assert restored.step_id == "s1"
        assert restored.payload["latency_ms"] == 42.0


class TestLamportClock:
    @pytest.mark.asyncio
    async def test_tick_monotonic(self):
        clock = await _make_clock()
        task_id = "t-" + str(time.time())
        ts1 = await clock.tick(task_id)
        ts2 = await clock.tick(task_id)
        ts3 = await clock.tick(task_id)
        assert ts1 < ts2 < ts3

    @pytest.mark.asyncio
    async def test_update_takes_max(self):
        clock = await _make_clock()
        task_id = "t-" + str(time.time())
        await clock.tick(task_id)
        await clock.tick(task_id)
        ts4 = await clock.update(task_id, 100)  # remote is ahead
        assert ts4 > 100
        ts5 = await clock.update(task_id, 0)   # remote is behind
        assert ts5 > ts4

    @pytest.mark.asyncio
    async def test_get_zero_if_fresh(self):
        clock = await _make_clock()
        val = await clock.get("nonexistent-task-" + str(time.time()))
        assert val == 0


class TestEventStore:
    @pytest.mark.asyncio
    async def test_append_read(self):
        store = await _make_store()
        task_id = "t-" + str(time.time())
        e = TaskEvent.make(
            task_id=task_id,
            event_type=EventType.TASK_CREATED,
            worker_id="w1",
            epoch=0,
            lamport_ts=0,
        )
        entry_id = await store.append(task_id, e)
        assert entry_id
        events = await store.get_all_events(task_id)
        assert len(events) == 1
        assert events[0].event_type == EventType.TASK_CREATED

    @pytest.mark.asyncio
    async def test_append_step_executed(self):
        store = await _make_store()
        task_id = "t-" + str(time.time())
        entry_id = await store.append_step_executed(
            task_id=task_id,
            epoch=1,
            worker_id="w1",
            step_id="s1",
            step_name="search web",
            tool="web",
            latency_ms=150.0,
            input_tokens=50,
            output_tokens=120,
        )
        assert entry_id
        events = await store.get_all_events(task_id)
        step_ev = next(e for e in events if e.event_type == EventType.STEP_EXECUTED)
        assert step_ev.payload["latency_ms"] == 150.0
        assert step_ev.payload["tool"] == "web"

    @pytest.mark.asyncio
    async def test_replay_with_idempotency(self):
        store = await _make_store()
        task_id = "t-" + str(time.time())

        # Simulate: step executed, then idempotency guard set
        await store.append_step_executed(task_id, epoch=1, worker_id="w1",
            step_id="s1", step_name="step1", tool="llm", latency_ms=50.0)
        await store.append_idempotency_set(task_id, epoch=1, worker_id="w1",
            step_id="s1", step_name="step1")
        await store.append_task_completed(task_id, epoch=1, worker_id="w1",
            result={"status": "ok"})

        results = await store.replay(task_id)
        assert len(results) == 2  # STEP_EXECUTED + TASK_COMPLETED (idempotency guard skipped)
        completed = next(r for r in results if r.get("event_type") == "TASK_COMPLETED")
        assert completed["result"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_audit_trail(self):
        store = await _make_store()
        task_id = "t-" + str(time.time())

        await store.append_step_executed(task_id, epoch=1, worker_id="w1",
            step_id="s1", step_name="step1", tool="llm", latency_ms=50.0)
        await store.append_task_completed(task_id, epoch=1, worker_id="w1",
            result={"output": "done"})

        trail = await store.get_audit_trail(task_id)
        assert trail["total_events"] == 2
        assert len(trail["events"]) == 2
        assert trail["events"][0]["type"] == "STEP_EXECUTED"
        assert trail["events"][1]["type"] == "TASK_COMPLETED"

    @pytest.mark.asyncio
    async def test_global_sequence(self):
        store = await _make_store()
        t1 = "t1-" + str(time.time())
        t2 = "t2-" + str(time.time())

        # t2 gets events first (by wall clock), but t1 appends first Lamport
        await store.append(
            t1,
            TaskEvent.make(t1, EventType.TASK_CREATED, "w1", epoch=0, lamport_ts=0),
        )
        await asyncio.sleep(0.01)
        await store.append(
            t2,
            TaskEvent.make(t2, EventType.TASK_CREATED, "w1", epoch=0, lamport_ts=0),
        )

        merged = await store.get_global_sequence([t1, t2])
        assert len(merged) == 2
        # sorted by Lamport (t1 first because it was created first)
        assert merged[0].task_id == t1
        assert merged[1].task_id == t2

    @pytest.mark.asyncio
    async def test_delete_stream(self):
        store = await _make_store()
        task_id = "t-" + str(time.time())
        await store.append(
            task_id,
            TaskEvent.make(task_id, EventType.TASK_CREATED, "w1", epoch=0, lamport_ts=0),
        )
        assert await store.count_events(task_id) == 1
        await store.delete_stream(task_id)
        assert await store.count_events(task_id) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
