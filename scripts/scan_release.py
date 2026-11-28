"""Scan a concrete prepared package. Never print matched credentials."""

import argparse
import hashlib
import re
from pathlib import Path

PATTERNS = [
    re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    re.compile(rb"sk-or-v1-[0-9a-fA-F]{64}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

# Public Mozilla CA bundle shipped by the certifi version pinned in uv.lock.
# Exact content is approved, never an arbitrary PEM or a private-key exemption.
CERTIFI_CA_SHA256 = "bb92c6ac31c92f4f553bffd6bf093db02c858c23e111b0b4df9bafa3fdbe00d1"


def scan(root):
    errors = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        approved_public_ca = (
            relative.endswith("_internal/certifi/cacert.pem")
            and hashlib.sha256(content).hexdigest() == CERTIFI_CA_SHA256
        )
        if re.search(r"_KEY\.(?:csv|json)$", path.name, re.I) or path.name in {
            ".env",
            "glassflow.db",
            "pending-restore.json",
        }:
            errors.append(f"Forbidden runtime file: {relative}")
        if path.suffix.lower() in {".db", ".sqlite", ".joblib", ".pkl", ".pem", ".key"} and not approved_public_ca:
            errors.append(f"Unapproved runtime artifact: {relative}")
        if any(pattern.search(content) for pattern in PATTERNS):
            errors.append(f"Possible credential in {relative}; value redacted")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if not args.directory.is_dir():
        raise SystemExit("Package directory missing")
    findings = scan(args.directory)
    if findings:
        raise SystemExit("\n".join(findings))
    print("PASS: scanned concrete package for known credential patterns, KEY and local state artifacts")
