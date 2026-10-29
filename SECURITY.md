# Security policy

## Supported versions

Security fixes are issued for the latest release on the `main` branch. Older
builds are not patched; rebuild from `main` or update to the newest release.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting flow:

1. Open <https://github.com/WinterGate-IC/VoiceForge/security/advisories/new>.
2. Describe the issue, the affected version and, if possible, a minimal
   reproduction.

You will get an acknowledgement as soon as the report is reviewed. Please give
us a reasonable window to ship a fix before publishing details.

## Scope

In scope:

- the VoiceForge launcher, native app, browser/Flet front-ends and CLI;
- the Windows package and the offline Setup installer;
- the build and release scripts in `tools/`;
- the render pipeline, audio writers and library/profile parsers;
- the optional clone engine integration code.

Out of scope:

- the Microsoft Edge speech service itself (report to Microsoft);
- third-party libraries (report those upstream as well);
- issues that require an already-compromised machine or administrator rights;
- social-engineering or physical access;
- the optional XTTS v2 model weights and `coqui-tts`/`torch` installs.

## What this project already does

- **No secrets in the repository.** The Edge engine needs no API key, and the
  release scripts never read or store a token.
- **No binaries or user data are committed.** `.gitignore` excludes virtual
  environments, build trees, releases, caches, downloads, voices and scripts.
- **Installer hardening.** Archive members are validated before extraction:
  absolute paths and `..` traversal are rejected, and Windows extended-length
  paths are used so a deep install folder cannot break or escape extraction.
- **Crash-safe audio.** Every rendered part and the finished file is validated,
  written to a temporary name and renamed into place; a failed render leaves
  nothing half-written in the downloads folder.
- **No telemetry.** Scripts, voices and audio stay in the local library. Only
  the text you explicitly synthesize is sent to Microsoft's Edge endpoint.
- **Checksums.** Release assets publish a SHA-256 digest; GitHub also reports
  the digest of every uploaded asset.
- **Dependency updates.** Dependabot watches Python and GitHub Actions
  dependencies; CodeQL and the test suite run on every push and pull request.
- **Licensing.** The build ships only the RSA *public* key used to verify a
  licence. The signing key is offline in a private repository, so no public
  build can mint a licence. See `OPEN_CORE.md`.

## Verifying a download

```powershell
Get-FileHash .\VoiceForge-<timestamp>.zip -Algorithm SHA256
```

Compare the result with the digest in the release notes. The same digest is
shown on the GitHub release asset.

## Licence and security model

VoiceForge is open source under the MIT licence. There are no server-side
secrets: the default engine talks directly to Microsoft's public speech
endpoint, and the optional clone engine runs locally. The trade-off of MIT is
that anyone may fork and redistribute the code; that is expected and is
separate from vulnerability handling.
