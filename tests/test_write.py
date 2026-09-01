from pathlib import Path

import pytest

from server.write import WriteRejected, apply_proposal


def test_approved_proposal_updates_only_the_changed_file(tmp_path: Path) -> None:
    vault, proposal = tmp_path / "vault", tmp_path / "proposal"
    vault.mkdir(); proposal.mkdir()
    (vault / "daily.md").write_text("before", encoding="utf-8")
    (proposal / "daily.md").write_text("after", encoding="utf-8")

    apply_proposal(vault, proposal, ["daily.md"])

    assert (vault / "daily.md").read_text(encoding="utf-8") == "after"


def test_proposal_cannot_delete_a_vault_file(tmp_path: Path) -> None:
    vault, proposal = tmp_path / "vault", tmp_path / "proposal"
    vault.mkdir(); proposal.mkdir()
    (vault / "keep.md").write_text("keep", encoding="utf-8")

    with pytest.raises(WriteRejected, match="DELETE_REJECTED"):
        apply_proposal(vault, proposal, ["keep.md"])

    assert (vault / "keep.md").read_text(encoding="utf-8") == "keep"


def test_proposal_cannot_escape_the_vault(tmp_path: Path) -> None:
    vault, proposal = tmp_path / "vault", tmp_path / "proposal"
    vault.mkdir(); proposal.mkdir()

    with pytest.raises(WriteRejected, match="PATH_REJECTED"):
        apply_proposal(vault, proposal, ["../outside.md"])
