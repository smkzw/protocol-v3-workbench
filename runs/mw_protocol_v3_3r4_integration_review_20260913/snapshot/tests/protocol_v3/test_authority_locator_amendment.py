"""R.1: relocation preserves frozen identity and rejects changed or escaped bytes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location(
        "authority_amendment", ROOT / "scripts/qc/protocol_v3/authority_locator_amendment.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def case(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    new.mkdir()
    asset = new / "template.docx"
    asset.write_bytes(b"frozen bytes")
    sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    return {"old_root": str(old), "new_root": str(new), "relocations": [
        {"old_locator": str(old / asset.name), "new_locator": str(asset),
         "sha256": sha, "owner": "clinical_template_authority", "allowed": "read_only"}
    ], "additions": []}


def test_current_amendment_covers_exact_frozen_assets_and_new_authorities():
    m = module()
    data = m.load_amendment()
    frozen = json.loads((ROOT / "tests/fixtures/protocol_v3/immutable_protected_assets.json").read_text())
    old = {x["path"]: x["sha256"] for x in frozen["assets"]
           if "cmss_sop_md_5101_protocol_template_authority" in x["rule_ids"]}
    assert {x["old_locator"]: x["sha256"] for x in data["relocations"]} == old
    assert len(m.validate_amendment(data)) == 13
    assert len(data["additions"]) == 8
    assert data["additions"][0]["sha256"] == "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"


def test_relocation_validates_bytes_and_does_not_mutate_record(tmp_path):
    data = case(tmp_path)
    before = copy.deepcopy(data)
    mapping = module().validate_amendment(data)
    assert data == before
    assert mapping[data["relocations"][0]["old_locator"]] == Path(data["relocations"][0]["new_locator"])
    Path(data["relocations"][0]["new_locator"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        module().validate_amendment(data)


@pytest.mark.parametrize("defect", ["duplicate", "escape", "symlink", "missing", "owner"])
def test_bad_relocation_fails_closed(tmp_path, defect):
    data = case(tmp_path)
    row = data["relocations"][0]
    target = Path(row["new_locator"])
    if defect == "duplicate":
        data["relocations"].append(dict(row))
    elif defect == "escape":
        row["new_locator"] = str(tmp_path / "outside.docx")
    elif defect == "symlink":
        original = tmp_path / "outside.docx"
        target.rename(original)
        target.symlink_to(original)
    elif defect == "missing":
        target.unlink()
    else:
        row["owner"] = ""
    with pytest.raises(ValueError):
        module().validate_amendment(data)


def test_frozen_rule_and_manifest_bytes_remain_unchanged():
    for name, expected in {
        "immutable_protected_assets.json": "f4b385d444d4cf922f20b9934e87f6b72c0ad932fc767b5c86045b7e8c0ace7f",
        "protected_path_rules.json": "16012ec0960ea096f86db6db65bb5dd77b33f215f3cee2377e5dfb28a6cb4ece",
    }.items():
        assert hashlib.sha256((ROOT / "tests/fixtures/protocol_v3" / name).read_bytes()).hexdigest() == expected


def test_builder_resolves_current_bytes_under_unchanged_logical_keys():
    spec = importlib.util.spec_from_file_location(
        "frozen_builder_amended", ROOT / "scripts/qc/protocol_v3/build_frozen_authority_manifest.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    data = module().load_amendment()
    patterns = [str(Path(data["old_root"]) / "**" / suffix) for suffix in ("*.docx", "*.xlsx")]
    keys, counts = builder._expand_patterns(patterns, [Path(data["old_root"])])
    assert keys == {Path(row["old_locator"]) for row in data["relocations"]}
    assert sum(counts.values()) == 13
    row = data["relocations"][0]
    record = builder._path_record(Path(row["old_locator"]), [Path(data["old_root"])])
    assert record["path"] == row["old_locator"]
    assert record["sha256"] == row["sha256"]


def test_unknown_current_file_is_rejected(tmp_path):
    data = case(tmp_path)
    (Path(data["new_root"]) / "unexpected.docx").write_bytes(b"not authorized")
    with pytest.raises(ValueError, match="unknown assets"):
        module().validate_amendment(data)
