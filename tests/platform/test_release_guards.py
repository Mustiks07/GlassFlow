import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from scan_release import scan  # noqa: E402


def test_scan_concrete_files_redacts_value_and_rejects_key(tmp_path):
    secret = "sk-or-v1-" + "a" * 64  # Explicit synthetic scanner fixture, not a credential.
    (tmp_path / "bundle.js").write_text(secret, encoding="utf8")
    (tmp_path / "questions_closed_KEY.csv").write_text("evaluation only", encoding="utf8")
    findings = scan(tmp_path)
    assert len(findings) == 2 and all(secret not in f for f in findings)


def test_full_release_refuses_partial_export(tmp_path):
    import json

    from assemble_release import verify_export

    (tmp_path / "manifest.json").write_text(json.dumps({"status": "partial", "files": {}}), encoding="utf8")
    with pytest.raises(ValueError, match="not ready"):
        verify_export(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"status": "ready", "errors": [],
        "module_provenance": {"assistant": {"synthetic": True}}}), encoding="utf8")
    with pytest.raises(ValueError, match="Synthetic"):
        verify_export(tmp_path)


def test_only_exact_pinned_public_certifi_bundle_is_approved(tmp_path):
    import certifi

    bundle = tmp_path / '_internal/certifi/cacert.pem'
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(Path(certifi.where()).read_bytes())
    assert scan(tmp_path) == []
    bundle.write_bytes(bundle.read_bytes() + b'changed')
    assert 'Unapproved runtime artifact' in scan(tmp_path)[0]
    bundle.write_bytes(b'-----BEGIN PRIVATE KEY-----\nsynthetic\n')
    assert len(scan(tmp_path)) == 2


@pytest.mark.parametrize('name', ['open-run', 'baseline', 'changed-input-run'])
def test_actual_downloads_keep_exact_manifest_bytes_in_checkout(name):
    from assemble_release import verify_export

    directory = Path(__file__).resolve().parents[2] / 'docs/release/integration' / name
    manifest = verify_export(directory)
    assert manifest['status'] == 'ready'
