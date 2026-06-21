"""CLI for the durable task-graph executor (observability + intervention).

    python orchestrate.py run    "Compare local vector DBs for personal recall"
    python orchestrate.py status <run_id>
    python orchestrate.py resume <run_id> [--approve persist]
    python orchestrate.py list

`run`/`resume` walk the graph until it completes, fails, or hits an approval
gate. `status` renders the plan with live checkmarks plus the event trace.
"""
import _repo_path  # noqa: F401 — repo root on sys.path for observer
import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime

from rich.console import Console

import checkpoint
import preflight
from example_plan import build_graph
from executor import execute, resume_state
from observer import ensure, store as observer_store
from state import RunState, Status

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
ensure()
console = Console()

GLYPH = {
    Status.DONE: "[green]✔[/green]", Status.RUNNING: "[yellow]●[/yellow]",
    Status.FAILED: "[red]✘[/red]", Status.PENDING: "[dim]▢[/dim]",
    Status.SKIPPED: "[dim]–[/dim]", Status.AWAITING_APPROVAL: "[magenta]⏸[/magenta]",
}


def render(state: RunState) -> None:
    graph = build_graph()
    done = sum(1 for s in state.steps.values() if s.status == Status.DONE)
    total = len(graph.order)
    console.print(f"\n[bold]Run {state.run_id}[/bold]  ({done}/{total} done)")
    console.print(f"[dim]goal:[/dim] {state.goal}\n")
    for i, name in enumerate(graph.order, 1):
        st = state.steps.get(name)
        glyph = GLYPH.get(st.status, "?") if st else "[dim]▢[/dim]"
        extra = f"  [red]{st.error}[/red]" if st and st.error else ""
        console.print(f"  {glyph} [cyan]{i:>2}.[/cyan] {name}{extra}")
    console.print("\n[bold]Events[/bold] (orchestrator)")
    for ts, step, status, detail in checkpoint.events(state.run_id, limit=80):
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        d = f"  {detail}" if detail else ""
        console.print(f"  [dim]{t}[/dim] {step:<12} [dim]{status}[/dim]{d}")
    cross = observer_store.list_events(run_id=state.run_id, limit=40)
    if cross:
        console.print("\n[bold]Cross-component[/bold]")
        for ts, component, kind, step, status, detail, _meta in reversed(cross):
            t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            st = step or "-"
            d = f"  {detail}" if detail else ""
            console.print(
                f"  [dim]{t}[/dim] [{component}/{kind}] {st:<12} "
                f"[dim]{status}[/dim]{d}"
            )


def _final_banner(state: RunState) -> None:
    statuses = {s.status for s in state.steps.values()}
    if Status.FAILED in statuses:
        console.print("\n[red]Run paused after a failure.[/red] Inspect, then "
                      f"`resume {state.run_id}`.")
    elif Status.AWAITING_APPROVAL in statuses:
        gated = [n for n, s in state.steps.items() if s.status == Status.AWAITING_APPROVAL]
        console.print(f"\n[magenta]Awaiting approval:[/magenta] {gated}. Approve with "
                      f"`resume {state.run_id} --approve {gated[0]}`.")
    else:
        console.print("\n[green]Run complete.[/green]")


def cmd_run(args) -> None:
    preflight.check()
    state = RunState(run_id=uuid.uuid4().hex[:8], goal=args.goal)
    state = asyncio.run(execute(build_graph(), state))
    render(state); _final_banner(state)


def cmd_resume(args) -> None:
    preflight.check()
    state = checkpoint.load(args.run_id)
    for step in args.approve or []:
        state.approve(step)
    state = resume_state(build_graph(), state)
    state = asyncio.run(execute(build_graph(), state))
    render(state); _final_banner(state)


def cmd_status(args) -> None:
    render(checkpoint.load(args.run_id))


def cmd_list(_args) -> None:
    rows = checkpoint.list_runs()
    if not rows:
        console.print("[dim]no runs yet[/dim]"); return
    for run_id, goal, updated in rows:
        t = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
        console.print(f"[cyan]{run_id}[/cyan]  [dim]{t}[/dim]  {goal[:60]}")


def main() -> None:
    p = argparse.ArgumentParser(description="Durable task-graph orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("goal"); r.set_defaults(fn=cmd_run)
    rs = sub.add_parser("resume"); rs.add_argument("run_id")
    rs.add_argument("--approve", action="append", help="approve a gated step (repeatable)")
    rs.set_defaults(fn=cmd_resume)
    st = sub.add_parser("status"); st.add_argument("run_id"); st.set_defaults(fn=cmd_status)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    args = p.parse_args()
    try:
        args.fn(args)
    except preflight.PreflightError as e:
        console.print(f"[bold red]Preflight failed:[/bold red] {e}"); sys.exit(1)
    except (KeyError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}"); sys.exit(1)


if __name__ == "__main__":
    main()
