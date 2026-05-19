# Security

## Signed Manifest Trust

Downloaded updates are trusted only through a detached Ed25519 signature over a
release manifest. The launcher verifies the manifest signature before parsing
the manifest YAML.

Required app config:

```yaml
trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
  manifest_url: "https://github.com/org/app/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/org/app/releases/download/{version}/launcher-manifest.yml.sig"
```

Manifest:

```yaml
schema_version: 1
application: MyApp
version: v1.2.3
archive:
  sha256: "<hex-sha256-of-source-archive>"
```

The launcher rejects:

- missing or invalid signatures;
- manifest schema versions other than `1`;
- application or version mismatches;
- invalid archive hashes;
- source archives whose SHA-256 differs from the signed manifest.

## Archive Extraction

Archives are extracted into a unique temporary directory and moved into place
only after validation succeeds. Existing target directories are not overwritten.

The extractor rejects members containing parent path segments, absolute paths,
Windows drive paths, backslash paths, symlinks, and special files.

## Release Flow

Generate a manifest and signature:

```bash
uv run python scripts/sign_manifest.py \
  --application MyApp \
  --version v1.2.3 \
  --archive source.zip \
  --private-key ed25519-private.pem
```

Upload both generated files as release assets:

- `launcher-manifest.yml`
- `launcher-manifest.yml.sig`

The command prints the base64 public key to place in `application.yml`.

## Non-Goals

The launcher does not make unsigned release archives trustworthy, protect a
compromised signing key, sandbox the launched application, or validate the
semantic correctness of application code.
