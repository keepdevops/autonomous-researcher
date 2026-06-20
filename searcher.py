"""Command-line front end for the canonical tools in tools.py.

Lets you exercise the same search_web / read_url implementations the agent
uses, straight from the shell, without standing up the LLM loop.
"""

import argparse
import logging
import sys

from tools import read_url, search_web

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the web via SearXNG or fetch a URL as clean text."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="run a web search")
    p_search.add_argument("query", help="search query")
    p_search.add_argument(
        "-n", "--num-results", type=int, default=8, help="max results (default: 8)"
    )

    p_read = sub.add_parser("read", help="fetch a URL and render it as text")
    p_read.add_argument("url", help="URL to fetch")

    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> str:
    if args.command == "search":
        results = search_web({"query": args.query, "num_results": args.num_results})
        return "\n\n".join(
            f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet'][:300]}..."
            for r in results
        )
    if args.command == "read":
        return read_url({"url": args.url})
    raise ValueError(f"unknown command: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        output = _run(args)
    except (RuntimeError, ValueError) as exc:
        logger.error("%s failed: %s", args.command, exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
