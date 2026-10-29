# Code signing

## Current status

VoiceForge releases are **not code-signed**. Windows SmartScreen may show
"Unknown publisher" the first time you run the installer or the portable app.

That is expected, not a sign of tampering. A publicly trusted signature requires
a code-signing certificate whose subject is a **verified legal entity** (or a
verified individual). WinterGate Intelligence Collective is not a registered
legal entity, so no certificate can be issued in that name. Self-signed
certificates do not help: Windows does not trust them, and they can make the
warning worse.

## Verify what you downloaded

Every release publishes the SHA-256 of the bundle in three places:

1. the release notes;
2. the attached `SHA256SUMS.txt`;
3. the digest GitHub shows next to the release asset.

Check the file you downloaded:

```powershell
Get-FileHash .\VoiceForge-<version>.zip -Algorithm SHA256
```

The output must match the release digest exactly. If it does not, do not run the
file. Report it through [SECURITY.md](SECURITY.md) instead.

To keep the first run simple: Windows may show **More info → Run anyway**. The
app installs per-user, needs no administrator rights, and makes no network
calls of its own (the default Edge voices contact Microsoft's speech endpoint
when you render).

## Why we do not use a self-signed certificate

A self-signed certificate only changes who is named in the signature; Windows
still cannot chain it to a trusted root, so SmartScreen still warns and may also
flag the file as invalidly signed. It would look more official while providing
no verification. We would rather stay unsigned and publish reproducible source,
hashes and the build script.

Note that since 2024, even EV certificates no longer skip SmartScreen entirely.
Any new certificate must build reputation through clean downloads.

## Path to signed releases

When WinterGate has a legal entity, signing is a small, well-defined change:

1. Register the entity (or a sole-proprietor/DBA name, if the CA accepts it).
2. Buy an OV code-signing certificate (roughly **$120–350/year**; private key in
   a cloud HSM or FIPS 140-2 token; maximum validity is 460 days for
   certificates issued after March 2026).
3. Store the signing credentials in the CI secret store or the CA's cloud HSM.
   Never commit them and never add them as repository files.
4. Sign `VoiceForge.bat`'s embedded executable, the launcher and
   `VoiceForge-Setup-*.exe` with SHA-256 and an RFC 3161 timestamp, then verify
   with:

   ```powershell
   signtool verify /pa /v VoiceForge-Setup-*.exe
   ```

5. Update this file and the release notes. Do not describe a build as signed
   until `signtool verify` succeeds on the artifacts that were uploaded.

## Free options and why they are not used

- **SignPath Foundation** issues the certificate to *SignPath Foundation*, so
  the publisher shown would be SignPath Foundation, not WinterGate. Their terms
  also exclude projects with proprietary or commercially dual-licensed
  components; the private Pro edition conflicts with that.
- **Certum's open-source / individual certificate** is issued to an individual's
  legal name and is restricted to non-commercial open source. It cannot carry
  the WinterGate name, and the Pro edition makes the non-commercial condition
  doubtful.

The public source, the test suite and `tools/build_release.py` remain the
authoritative way to check what a release contains.
