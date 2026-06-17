from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunPaths:
    root: Path
    evidence: Path
    downloads: Path
    raw: Path
    output: Path


def safe_reference(reference: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in reference.strip())
    return cleaned or "quotation"


def create_run_paths(base_output_dir: Path, quotation_reference: str) -> RunPaths:
    safe_ref = safe_reference(quotation_reference)
    run_root = Path("runs") / safe_ref
    top_level_evidence = Path("evidence") / safe_ref
    paths = RunPaths(
        root=run_root,
        evidence=top_level_evidence,
        downloads=run_root / "downloads",
        raw=top_level_evidence / "raw",
        output=base_output_dir,
    )
    for path in (paths.root, run_root / "evidence", paths.evidence, paths.downloads, paths.raw, paths.output):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def evidence_path(paths: RunPaths, source: str, stem: str, suffix: str = ".png") -> Path:
    cleaned_source = safe_reference(source)
    cleaned_stem = safe_reference(stem)
    return paths.evidence / f"{cleaned_source}_{cleaned_stem}{suffix}"
