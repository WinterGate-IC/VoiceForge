"""Offline licence verification for VoiceForge.

The open-source build can **verify** a licence but cannot create one: only the
RSA public key is shipped here, and the signing key stays offline in the
WinterGate private repository. An add-on may therefore be distributed like any
other file, but it will only switch on when a correctly signed licence covers
it.

Token format::

    VF1.<base64url(payload json)>.<base64url(rsa pkcs#1 v1.5 sha-256 sig)>

The payload is canonical JSON (sorted keys, no spaces) so the signature is
stable. See ``SECURITY.md`` and ``OPEN_CORE.md`` for the threat model.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRODUCT = "voiceforge"
TOKEN_PREFIX = "VF1"
TOKEN_VERSION = 1

# Public half of the WinterGate licence key (3072-bit RSA, e = 65537).
# Regenerate with the private ``license_admin.py`` tool and replace both
# constants; never place the private exponent in this repository.
PUBLIC_KEY_N = int(
    "d12cfdc571433b7efe476515af776e3384afd55c7c018a8be47297ec6309bb53"
    "a284c1e476e672f59e851f218a0812a5f27c4d30d50bf349bdae01182fa27b97"
    "428dea288cebf1da6441c39d465a7860febb2f1da87b71b90703096b453f78ac"
    "9ee99bf1f59d084ec49f3a6d3d6074671d127184ead3b96a3bcfe42ab94bffcd"
    "40bf7d670ce3df57d31d52f3fbff7d7c4b3fbfafa93e260c5b388268f0fc6aff"
    "1aae8ed9c0d9e05ecb6c97434552511c8bc209d271466e478d52ed0c0c3b8cd4"
    "7510b4b50a20162245085a71cdb8c37952e5cdc2482407faa8784c45b51b2509"
    "baae897401049c750d86cfa06553dc87db0ec1dd2c8ec035b48cf31e789ef328"
    "3ded1deb2dc5d3b54320411f1490e66029165072d899df50b9f1bdcfe9eba1408"
    "11941df6b4658cc2e459d141030377ec5dc0329d26d88c3790c348eb8b11b4bb"
    "03558fe95868ec7768496f7568965c421415578e81fd34209bb933c428db93d6"
    "ceb1c766f742d34c50e58a9e4896cb4171e4b861008101758d93177225a3255",
    16,
)
PUBLIC_KEY_E = 0x10001
MAX_TOKEN_BYTES = 8 * 1024
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

__all__ = [
    "License",
    "LicenseError",
    "active_license",
    "allows",
    "default_license_path",
    "describe_status",
    "install_license",
    "machine_id",
    "parse_token",
    "require",
    "revoke_license",
]


class LicenseError(ValueError):
    """A licence is missing, malformed, expired or for another product."""


# ------------------------------------------------------------------ helpers
def _b64decode(text: str) -> bytes:
    if not text or len(text) > MAX_TOKEN_BYTES:
        raise LicenseError("licence token is empty or too large")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("licence token is not valid base64url") from exc
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != text:
        raise LicenseError("licence token has a non-canonical encoding")
    return raw


def _verify_signature(payload: bytes, signature: bytes) -> None:
    size = (PUBLIC_KEY_N.bit_length() + 7) // 8
    if len(signature) != size:
        raise LicenseError("licence signature has the wrong length")
    message = pow(int.from_bytes(signature, "big"), PUBLIC_KEY_E, PUBLIC_KEY_N)
    actual = message.to_bytes(size, "big")

    digest = hashlib.sha256(payload).digest()
    trailer = _SHA256_DIGEST_INFO + digest
    padding = size - len(trailer) - 3
    expected = b"\x00\x01" + b"\xff" * padding + b"\x00" + trailer
    if not hmac.compare_digest(actual, expected):
        raise LicenseError("licence signature is not valid for this build")


def _parse_date(value: Any, field: str) -> dt.date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise LicenseError(f"licence field {field!r} must be a date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise LicenseError(f"licence field {field!r} is not an ISO date") from exc


# ------------------------------------------------------------------ licence
@dataclass(frozen=True)
class License:
    """A verified licence payload."""

    product: str
    edition: str
    licensee: str
    email: str
    license_id: str
    issued: dt.date | None
    expires: dt.date | None
    features: frozenset[str]
    max_machines: int
    machine: str | None
    raw: str = ""

    def expired(self, today: dt.date | None = None) -> bool:
        if self.expires is None:
            return False
        return (today or dt.date.today()) > self.expires

    def days_left(self, today: dt.date | None = None) -> int | None:
        if self.expires is None:
            return None
        return (self.expires - (today or dt.date.today())).days

    def allows(self, feature: str | None) -> bool:
        if feature in (None, "", "*"):
            return True
        return "*" in self.features or feature in self.features

    @property
    def perpetual(self) -> bool:
        return self.expires is None


def parse_token(
    token: str,
    *,
    product: str = PRODUCT,
    machine: str | None = None,
    today: dt.date | None = None,
    allow_expired: bool = False,
) -> License:
    """Verify ``token`` and return its payload."""
    token = (token or "").strip()
    if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
        raise LicenseError("licence token is too large")
    parts = token.split(".")
    if len(parts) != 3:
        raise LicenseError("licence token must have three dot-separated parts")
    prefix, payload_b64, signature_b64 = parts
    if prefix != TOKEN_PREFIX:
        raise LicenseError(f"this is not a {product} licence")

    payload_bytes = _b64decode(payload_b64)
    signature = _b64decode(signature_b64)
    _verify_signature(payload_bytes, signature)

    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LicenseError("licence payload is not valid JSON") from exc
    if not isinstance(data, dict):
        raise LicenseError("licence payload must be an object")
    if data.get("v") != TOKEN_VERSION:
        raise LicenseError("unsupported licence version")
    if data.get("product") != product:
        raise LicenseError(f"licence is for {data.get('product')!r}, not {product!r}")

    licensee = data.get("licensee")
    if not isinstance(licensee, str) or not licensee.strip():
        raise LicenseError("licence has no licensee")
    features = data.get("features", [])
    if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
        raise LicenseError("licence features must be a list of strings")

    bound = data.get("machine")
    if bound not in (None, ""):
        if not isinstance(bound, str):
            raise LicenseError("licence machine binding must be a string")
        # Never fall back to "unbound" when the caller omits the machine: a
        # licence bound to one machine must also fail closed on this one.
        current = machine if machine is not None else machine_id()
        if not hmac.compare_digest(bound, current):
            raise LicenseError("licence is bound to a different machine")

    licence = License(
        product=product,
        edition=str(data.get("edition") or "pro"),
        licensee=licensee.strip(),
        email=str(data.get("email") or ""),
        license_id=str(data.get("id") or ""),
        issued=_parse_date(data.get("issued"), "issued"),
        expires=_parse_date(data.get("expires"), "expires"),
        features=frozenset(features),
        max_machines=int(data.get("max_machines") or 1),
        machine=bound or None,
        raw=token,
    )
    if not allow_expired and licence.expired(today):
        raise LicenseError(f"licence expired on {licence.expires.isoformat()}")
    return licence


# ------------------------------------------------------------------ machine
def machine_id() -> str:
    """A stable, non-reversible id for this machine."""
    parts: list[str] = []
    if sys.platform.startswith("win"):
        try:
            import winreg  # noqa: PLC0415 - Windows only

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                parts.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except OSError:
            pass
    if not parts:
        parts.append(platform.node() or "unknown-host")
        parts.append(str(_hardware_address()))
    material = f"{PRODUCT}:licence-machine:" + "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _hardware_address() -> int:
    import uuid  # noqa: PLC0415

    return uuid.getnode()


# ------------------------------------------------------------------ storage
def _config_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base)
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def default_license_path() -> Path:
    return _config_root() / "WinterGate" / "VoiceForge" / "license.key"


def _candidate_tokens() -> list[str]:
    tokens: list[str] = []
    env = os.environ.get("VOICEFORGE_LICENSE", "").strip()
    if env:
        path = Path(env)
        if path.exists():
            try:
                env = path.read_text(encoding="utf-8").strip()
            except OSError:
                env = ""
        if env:
            tokens.append(env)
    for path in (default_license_path(), Path.cwd() / "license.key"):
        try:
            if path.is_file():
                tokens.append(path.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return [token for token in tokens if token]


_active: License | None = None
_active_loaded = False


def active_license(*, refresh: bool = False, machine: str | None = None,
                   today: dt.date | None = None) -> License | None:
    """The first valid licence found, or ``None``. Never raises."""
    global _active, _active_loaded
    if _active_loaded and not refresh and machine is None and today is None:
        return _active
    found: License | None = None
    current_machine = machine if machine is not None else machine_id()
    for token in _candidate_tokens():
        try:
            found = parse_token(token, machine=current_machine, today=today)
            break
        except LicenseError:
            continue
    if machine is None and today is None:
        _active, _active_loaded = found, True
    return found


def allows(feature: str) -> bool:
    licence = active_license()
    return bool(licence and licence.allows(feature))


def require(feature: str) -> License:
    """Raise ``LicenseError`` unless a licence enables ``feature``."""
    licence = active_license()
    if licence is None:
        raise LicenseError(
            f"{feature} needs a valid licence. Run `vf license` for status."
        )
    if not licence.allows(feature):
        raise LicenseError(f"your licence does not include {feature!r}")
    return licence


def install_license(token: str, *, path: Path | None = None) -> Path:
    licence = parse_token(token, machine=machine_id())
    target = path or default_license_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(licence.raw + "\n", encoding="utf-8")
    os.replace(temporary, target)
    active_license(refresh=True)
    return target


def revoke_license(path: Path | None = None) -> bool:
    target = path or default_license_path()
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    active_license(refresh=True)
    return True


def describe_status() -> dict[str, Any]:
    licence = active_license(refresh=True)
    if licence is None:
        return {
            "edition": "community",
            "licensed": False,
            "features": [],
            "license_path": str(default_license_path()),
            "machine": machine_id(),
        }
    remaining = licence.days_left()
    return {
        "edition": licence.edition,
        "licensed": True,
        "licensee": licence.licensee,
        "email": licence.email,
        "id": licence.license_id,
        "issued": licence.issued.isoformat() if licence.issued else None,
        "expires": licence.expires.isoformat() if licence.expires else None,
        "days_left": remaining,
        "perpetual": licence.perpetual,
        "features": sorted(licence.features),
        "machine_bound": bool(licence.machine),
        "license_path": str(default_license_path()),
        "machine": machine_id(),
    }
