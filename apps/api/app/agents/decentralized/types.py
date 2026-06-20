from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecentralizedCandidate:
    candidate_id: str
    title: str
    concept_summary: str
    expert_role: str
    expert_domain: str
    expert_intro: str
    style_tags: list[str]
    static_html: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidate_id,
            "title": self.title,
            "conceptSummary": self.concept_summary,
            "expertRole": self.expert_role,
            "expertDomain": self.expert_domain,
            "expertIntro": self.expert_intro,
            "styleTags": self.style_tags,
            "staticHtml": self.static_html,
        }


@dataclass(frozen=True)
class DecentralizedPreviewState:
    run_id: str
    job_id: str
    selected_candidate_id: str | None
    phase: str
    candidates: list[DecentralizedCandidate] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "jobId": self.job_id,
            "phase": self.phase,
            "selectedCandidateId": self.selected_candidate_id,
            "candidates": [candidate.to_public_dict() for candidate in self.candidates],
        }
