"""Plain data classes shared by the whole agent: what a finished run is made of.

A RunResult holds the question, the Sources it read, the Claims it kept (each with Evidence quotes and a status of
supported, contested or unsupported), the Conflicts between claims, and the written answer in Markdown. Every other
module, including the PDF report and the eval scorer, reads these and nothing else, so a saved run can be redrawn
or re-scored without running the agent again.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Source:
    url: str
    author: str = ""
    org: str = ""
    date_written: str = ""
    fetched_at: str = ""
    snippet: str = ""


@dataclass
class Evidence:
    source_url: str
    quote: str
    stance: Literal["supports", "refutes"] = "supports"


@dataclass
class Claim:
    id: str
    text: str
    kind: Literal["qual", "quant"] = "qual"
    status: Literal["supported", "contested", "unsupported"] = "unsupported"
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Conflict:
    claim_ids: list[str]
    reason: str
    resolved: bool = False


@dataclass
class RunResult:
    run_id: str
    question: str
    sources: list[Source] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    answer_md: str = ""
    uncertainty_notes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)  # tokens, seconds, nodes
