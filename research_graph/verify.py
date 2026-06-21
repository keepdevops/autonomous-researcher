"""Claim verification — standalone from orchestrator steps."""
import logging

from agents.llm import chat
from research_graph.models import ClaimStatus, ResearchGraph

logger = logging.getLogger(__name__)


def verify_graph(graph: ResearchGraph, chunks_by_id: dict[str, dict]) -> tuple[ResearchGraph, int]:
    unsupported = 0
    for claim in graph.claims:
        evidence = [chunks_by_id[c]["text"] for c in claim.source_chunk_ids if c in chunks_by_id]
        if not evidence and claim.source_urls:
            claim.status = ClaimStatus.SUPPORTED
            continue
        if not evidence:
            claim.status = ClaimStatus.UNSUPPORTED
            unsupported += 1
            continue
        blob = "\n".join(evidence)[:4000]
        verdict = chat(
            f"Claim: {claim.text}\n\nEvidence:\n{blob}\n\n"
            "Reply with one word: SUPPORTED or UNSUPPORTED.",
            max_tokens=16,
        ).upper()
        if "UNSUPPORTED" in verdict:
            claim.status = ClaimStatus.UNSUPPORTED
            unsupported += 1
        else:
            claim.status = ClaimStatus.SUPPORTED
    _emit_graph("verified", graph.run_id, unsupported=unsupported, total=len(graph.claims))
    return graph, unsupported


def _emit_graph(status: str, run_id: str, **meta) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.GRAPH,
                kind=EventKind.STEP,
                run_id=run_id,
                status=status,
                metadata=meta,
            )
        )
    except Exception:
        pass
