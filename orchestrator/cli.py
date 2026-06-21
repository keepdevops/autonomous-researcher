"""CLI for Plan A research runs."""
import argparse
import asyncio
import sys
from datetime import datetime

from rich.console import Console

from orchestrator import checkpoint
from orchestrator.executor import resume_state, execute
from orchestrator.plans.research import build_graph
from orchestrator.state import Status
from research_engine import run_research_plan

console = Console()

GLYPH = {
    Status.DONE: "[green]✔[/green]",
    Status.RUNNING: "[yellow]●[/yellow]",
    Status.FAILED: "[red]✘[/red]",
    Status.PENDING: "[dim]▢[/dim]",
    Status.SKIPPED: "[dim]–[/dim]",
    Status.AWAITING_APPROVAL: "[magenta]⏸[/magenta]",
}


def cmd_run(args):
    report = run_research_plan(args.question)
    console.print(report)


def cmd_status(args):
    state = checkpoint.load(args.run_id)
    graph = build_graph()
    for i, name in enumerate(graph.order, 1):
        st = state.steps.get(name)
        g = GLYPH.get(st.status, "?") if st else "?"
        console.print(f"  {g} {i:>2}. {name}  phase={state.phase()}")
    console.print("\n[bold]Events[/bold]")
    for ts, step, status, detail in checkpoint.events(args.run_id):
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        console.print(f"  {t} {step:<12} {status} {detail[:80]}")


def cmd_resume(args):
    state = checkpoint.load(args.run_id)
    state = resume_state(build_graph(), state)
    state = asyncio.run(execute(build_graph(), state))
    report = state.scratch.get("final_report", "")
    if report:
        console.print(report)
    else:
        console.print("[yellow]Run paused or incomplete.[/yellow]")


def main():
    from observer import ensure
    ensure()

    p = argparse.ArgumentParser(description="Plan A research orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("question")
    r.set_defaults(fn=cmd_run)
    st = sub.add_parser("status")
    st.add_argument("run_id")
    st.set_defaults(fn=cmd_status)
    rs = sub.add_parser("resume")
    rs.add_argument("run_id")
    rs.set_defaults(fn=cmd_resume)
    args = p.parse_args()
    try:
        args.fn(args)
    except (KeyError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
