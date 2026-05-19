#!/usr/bin/env python3
"""Create and sign a launcher release manifest."""

import argparse
import base64
import hashlib
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a signed launcher manifest")
    parser.add_argument("--application", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--manifest", default="launcher-manifest.yml", type=Path)
    parser.add_argument("--signature", default="launcher-manifest.yml.sig", type=Path)
    args = parser.parse_args()

    private_key_bytes = args.private_key.read_bytes()
    private_key = serialization.load_pem_private_key(private_key_bytes, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Private key must be an Ed25519 PEM key")

    archive_sha256 = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "application": args.application,
        "version": args.version,
        "archive": {"sha256": archive_sha256},
    }
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False).encode("utf-8")
    signature = private_key.sign(manifest_bytes)

    args.manifest.write_bytes(manifest_bytes)
    args.signature.write_bytes(signature)

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(f"public_key: {base64.b64encode(public_key).decode('ascii')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
