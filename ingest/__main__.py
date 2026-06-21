"""CLI: standalone ingest without orchestrator."""
import argparse
import json
import sys

from ingest.pipeline import ingest_path


def main() -> None:
    p = argparse.ArgumentParser(description="Plan A document ingest")
    p.add_argument("path", help="file to ingest (pdf, md, code, text)")
    p.add_argument("--limit", type=int, default=0, help="max chunks to print")
    args = p.parse_args()
    chunks = ingest_path(args.path)
    out = chunks if not args.limit else chunks[: args.limit]
    json.dump([c.to_dict() for c in out], sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
