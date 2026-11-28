import importlib.util
from pathlib import Path


def test_included_quota_credential_is_rejected_in_actual_release_files(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "scan_release.py"
    spec = importlib.util.spec_from_file_location("release_scan_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifact = tmp_path / "client.js"
    artifact.write_bytes(b"sk-" + b"pl-" + b"a" * 64)
    errors = module.scan(tmp_path)
    assert errors == ["Possible credential in client.js; value redacted"]
    assert "a" * 64 not in " ".join(errors)
