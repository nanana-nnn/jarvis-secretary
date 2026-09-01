"""Approved-only application of a JARVIS proposal (DESIGN.md §11)."""
from __future__ import annotations

from pathlib import Path
import shutil


class WriteRejected(ValueError):
    pass


def apply_proposal(vault: Path, proposal: Path, changed_files: list[str]) -> None:
    """Copy only safe additions/updates.  Never delete, move, or follow paths out of Vault."""
    root = vault.resolve()
    proposal_root = proposal.resolve()
    for relative in changed_files:
        target = (vault / relative).resolve()
        source = (proposal / relative).resolve()
        if root not in target.parents or proposal_root not in source.parents:
            raise WriteRejected("PATH_REJECTED")
        if not source.is_file():
            # A missing source would mean a deletion or rename: both are forbidden.
            raise WriteRejected("DELETE_REJECTED")
        if target.exists() and not target.is_file():
            raise WriteRejected("PATH_REJECTED")

    # Validate every path before changing even one file, so failure is atomic.
    for relative in changed_files:
        target, source = vault / relative, proposal / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
