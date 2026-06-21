"""CLI: tail the unified event stream across all components."""
import argparse
import json
import sys
import time
from datetime import datetime

from observer.bootstrap import install
from observer.events import Component
from observer import store


def cmd_tail(args: argparse.Namespace) -> None:
    install(enable_log=False)
    last_id = store.latest_event_id()
    print(f"Watching {store.DB_PATH} (from id>{last_id})… Ctrl+C to stop.", flush=True)
    try:
        while True:
            rows = store.tail_events(since_id=last_id, limit=50)
            for row in rows:
                eid, ts, component, kind, run_id, step, status, detail = row
                last_id = eid
                t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                rid = run_id or "-"
                st = step or "-"
                line = f"{t} [{component}/{kind}] run={rid} step={st} {status}"
                if detail:
                    line += f" — {detail[:160]}"
                print(line, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


def cmd_list(args: argparse.Namespace) -> None:
    install(enable_log=False)
    component = Component(args.component) if args.component else None
    rows = store.list_events(run_id=args.run_id, component=component, limit=args.limit)
    if not rows:
        print("No events.", flush=True)
        return
    for ts, component, kind, step, status, detail, meta_json in reversed(rows):
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        meta = json.loads(meta_json) if meta_json else {}
        print(f"{t}  {component}/{kind}  {step or '-'}  {status}")
        if detail:
            print(f"  detail: {detail[:200]}")
        if meta:
            print(f"  meta: {json.dumps(meta)[:200]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified system observer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    tail = sub.add_parser("tail", help="live tail of all component events")
    tail.add_argument("--interval", type=float, default=0.5)
    tail.set_defaults(fn=cmd_tail)

    lst = sub.add_parser("list", help="list recent events")
    lst.add_argument("--run-id", default=None)
    lst.add_argument("--component", choices=[c.value for c in Component], default=None)
    lst.add_argument("--limit", type=int, default=50)
    lst.set_defaults(fn=cmd_list)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
