from __future__ import annotations


class SciteClient:
    """Skeleton scite wrapper for citation-type classification."""

    def classify_citation(self, source_paper_id: str, target_paper_id: str) -> dict:
        return {
            "source": source_paper_id,
            "target": target_paper_id,
            "relation_type": "mentioning",
            "confidence": 0.5,
        }
