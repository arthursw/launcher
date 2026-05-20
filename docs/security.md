# Security Guide

Launcher downloads Python code and runs it. That is powerful, but it also means
the launcher must be careful.

This guide explains the security model without assuming packaging or security
experience.

## The Problem

If a program downloads code from the internet and runs it, it must answer one
question:

> Is this really the release the app developer intended users to run?

HTTPS helps, but it is not the whole answer. A wrong server response, broken
release process, compromised endpoint, or malicious archive could still cause
bad code to run.

## The Solution: Signed Manifests

Each app release must include two small files:

- `launcher-manifest.yml`
- `launcher-manifest.yml.sig`

The manifest describes the release:

```yaml
schema_version: 1
application: MyApp
version: v1.2.3
archive:
  sha256: "<hash-of-the-source-archive>"
```

The `.sig` file is a digital signature created by the app developer.

The launcher contains the public key in `myapp.yml`. When it updates the app, it:

1. downloads the manifest and signature;
2. verifies that the signature matches the public key;
3. downloads the app source archive;
4. checks that the archive hash matches the signed manifest;
5. extracts and runs the app only if all checks pass.

In short: the signature proves who approved the manifest, and the hash proves
the downloaded archive is exactly the archive described by that manifest.

## What This Protects Against

Signed manifests protect users from:

- accidentally downloading the wrong archive;
- corrupted downloads;
- tampered manifests;
- tampered archives;
- many proxy, cache, or custom endpoint mistakes.

They do not protect against:

- a stolen signing private key;
- a malicious developer signing a malicious release;
- bugs or vulnerabilities inside the app itself.

## Release Flow

Create the signing key once:

```bash
uv run launcher-release keygen
```

This creates `launcher-signing-key.pem`, adds it to `.gitignore`, and prints the
public key to put in your app config.

For each app release:

1. publish the normal GitHub or GitLab release;
2. put the source archive in `dist/`;
3. run the signing command;
4. verify the generated release files;
5. upload both files as release assets.

```bash
uv run launcher-release sign
uv run launcher-release verify
uv run launcher-release upload
```

By default, `sign`:

- looks for one archive in `dist/`;
- infers the version from the archive filename, such as `myapp-v1.2.3.zip`;
- writes `dist/launcher-manifest.yml`;
- writes `dist/launcher-manifest.yml.sig`.

`verify` checks the signature and confirms that the archive still matches the
hash in the manifest.

`upload` sends the manifest and signature to the release using the official
provider CLI:

- GitHub uses `gh`: https://github.com/cli/cli#installation
- GitLab uses `glab`: https://gitlab.com/gitlab-org/cli/#installation

Install and authenticate the matching tool before running `upload`. Launcher
does not ask for or store GitHub/GitLab tokens.

Manual upload is also fine. Open the release page on github.com or gitlab.com
and add these two files as release assets:

- `launcher-manifest.yml`
- `launcher-manifest.yml.sig`

The launcher then has enough information to verify the release before running
it.

## Proxy Passwords

Some users need a corporate proxy to access the internet.

Launcher can remember proxy passwords, but it does not write them into YAML
files. If the user chooses "remember password", the password is stored through
the operating system keychain. If keychain storage is unavailable, the password
is used only for the current launch.
