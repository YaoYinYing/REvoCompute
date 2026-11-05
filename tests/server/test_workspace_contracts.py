from __future__ import annotations

import pytest

from revocompute.workspace_contracts import WorkspaceValidationError, normalize_capability, validate_selected_residues


def selection(**overrides):
    residue = {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False}
    residue.update(overrides)
    return {"selected_residues": [residue]}


def test_workspace_selection_accepts_authored_identity_with_different_viewer_numbering():
    validate_selected_residues({"selected_residues": [{**selection()["selected_residues"][0], "label_seq_id": 900}]})


@pytest.mark.parametrize("value", [
    {"selected_residues": [None]},
    selection(auth_chain=""),
    selection(auth_seq_id=True),
    selection(insertion_code=42),
    selection(residue_name=None),
    selection(hetero="false"),
    {"selected_residues": [selection()["selected_residues"][0], selection()["selected_residues"][0]]},
    {"selected_residues": [
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False},
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "GLY", "hetero": False},
    ]},
    {"selected_residues": [
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False},
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": True},
    ]},
    {"selected_residues": [
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False},
        {"auth_chain": "A ", "auth_seq_id": 7, "insertion_code": " ", "residue_name": "ALA", "hetero": False},
    ]},
])
def test_workspace_selection_rejects_malformed_or_ambiguous_identity(value):
    with pytest.raises(WorkspaceValidationError):
        validate_selected_residues(value)


def test_normalization_boundary_does_not_double_report_selection_identity():
    called = []
    assert normalize_capability(lambda value: called.append(value) or {"params": {}}, {"selected_residues": []}) == {"params": {}}
    assert called


def test_workspace_selection_accepts_no_pick_and_preserves_multichain_provenance():
    validate_selected_residues({"selected_residues": []})
    validate_selected_residues({"selected_residues": [
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False},
        {"auth_chain": "B", "auth_seq_id": 8, "residue_name": "GLY", "hetero": False},
    ]})


def test_workspace_selection_keeps_distinct_authored_residues_and_insertion_codes():
    validate_selected_residues({"selected_residues": [
        {"auth_chain": "A", "auth_seq_id": 7, "residue_name": "ALA", "hetero": False},
        {"auth_chain": "A", "auth_seq_id": 8, "residue_name": "GLY", "hetero": False},
        {"auth_chain": "A", "auth_seq_id": 9, "insertion_code": "A", "residue_name": "SER", "hetero": False},
        {"auth_chain": "A", "auth_seq_id": 9, "insertion_code": "B", "residue_name": "SER", "hetero": False},
    ]})
