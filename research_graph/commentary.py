"""Graph commentary — standalone from orchestrator steps."""
from research_graph.models import ClaimStatus, ResearchGraph


def add_commentary(graph: ResearchGraph) -> ResearchGraph:
    for claim in graph.claims:
        if claim.status == ClaimStatus.UNSUPPORTED:
            claim.commentary = "Verifier: insufficient evidence in ingested chunks."
        elif claim.status == ClaimStatus.SUPPORTED and not claim.source_chunk_ids:
            claim.commentary = "Supported via URL only — no chunk ID linked."
        elif not claim.source_chunk_ids:
            claim.commentary = "No chunk IDs linked — citation may be weak."
    return graph
