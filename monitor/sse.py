"""SSE stream from observer system_events.db."""
import asyncio
import json
import time

from observer import store


async def event_stream(since_id: int = 0, poll: float = 0.5):
    last = since_id
    while True:
        rows = store.tail_events(since_id=last, limit=100)
        for row in rows:
            eid, ts, component, kind, run_id, step, status, detail = row
            last = eid
            payload = {
                "id": eid,
                "ts": ts,
                "component": component,
                "kind": kind,
                "run_id": run_id,
                "step": step,
                "status": status,
                "detail": detail,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(poll)


async def stream_response(since_id: int = 0):
    from starlette.responses import StreamingResponse

    return StreamingResponse(event_stream(since_id), media_type="text/event-stream")
