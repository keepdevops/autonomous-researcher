"""CLI: show research graph for a run."""
import argparse
import json
import sys

from research_graph import store


def main() -> None:
    p = argparse.ArgumentParser(description="Research graph viewer")
    p.add_argument("run_id")
    args = p.parse_args()
    graph = store.load(args.run_id)
    json.dump(graph.model_dump(mode="json"), sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
