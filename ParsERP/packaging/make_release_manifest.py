#!/usr/bin/env python3
"""Build the update manifest (``releases.json``) for a release artefact.

The manifest is what :mod:`pars_erp.services.update_service` reads.  Every field
in it is computed from the real files - nothing is typed by hand:

* ``sha256`` and ``size_bytes`` come from the artefact itself;
* ``signature`` is an Ed25519 signature over the artefact's bytes, produced with
  the private key you pass (never commit that key);
* ``schema_revision`` is read from the alembic scripts in this checkout;
* ``version``/``released_at``/``notes_fa`` come from the command line, and the
  version is validated with the same parser the application uses.

Usage
-----
    python packaging/make_release_manifest.py \
        --artefact "dist/ZarrinHormoz-0.7.1-setup.exe" \
        --version 0.7.1 --released-at 2026-11-20 \
        --notes "رفع اشکال گزارش تراز" --notes "افزودن فیلتر شعبه" \
        --url "https://example.invalid/updates/ZarrinHormoz-0.7.1-setup.exe" \
        --private-key packaging/release_signing_key.pem \
        --output dist/releases-0.7.1.json

Without ``--private-key`` the manifest is produced **unsigned**, and the
application will refuse to install it while ``update_require_signature`` is on
(the default).  That is deliberate: an unsigned update is a real risk, not a
warning to click away.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pars_erp.services.update_service import (  # noqa: E402
    MANIFEST_FORMAT,
    parse_version,
)


def head_revision() -> str | None:
    try:
        from alembic.script import ScriptDirectory

        from pars_erp.db.session import Database
    except Exception:  # pragma: no cover - alembic missing
        return None
    try:
        return ScriptDirectory.from_config(Database("sqlite://").alembic_config()
                                          ).get_current_head()
    except Exception:  # pragma: no cover
        return None


def sign(artefact: Path, private_key_path: Path) -> str:
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        load_pem_private_key,
    )

    key = load_pem_private_key(private_key_path.read_bytes(), password=None)
    if hasattr(key, "private_bytes"):  # Ed25519 private keys expose this directly
        pass
    signature = key.sign(artefact.read_bytes())
    return base64.b64encode(signature).decode("ascii")


def build(artefact: Path, *, version: str, released_at: str, notes: list[str], url: str,
          private_key: Path | None = None, channel: str = "stable",
          min_version: str | None = None) -> dict:
    parse_version(version)  # fail early on a malformed version
    payload = artefact.read_bytes()
    entry: dict[str, object] = {
        "version": version,
        "channel": channel,
        "released_at": released_at,
        "notes_fa": notes,
        "url": url,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "schema_revision": head_revision(),
    }
    if min_version:
        entry["min_version"] = min_version
    if private_key is not None:
        entry["signature"] = sign(artefact, private_key)
    return {"format": MANIFEST_FORMAT, "channel": channel, "releases": [entry]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ساخت مانیفست به‌روزرسانی زرین هرمز")
    parser.add_argument("--artefact", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--released-at", default=date.today().isoformat())
    parser.add_argument("--notes", action="append", default=[])
    parser.add_argument("--url", required=True)
    parser.add_argument("--channel", default="stable", choices=("stable", "beta"))
    parser.add_argument("--min-version", default=None)
    parser.add_argument("--private-key", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artefact.is_file():
        parser.error(f"فایل بسته یافت نشد: {args.artefact}")
    document = build(args.artefact, version=args.version, released_at=args.released_at,
                     notes=list(args.notes), url=args.url, private_key=args.private_key,
                     channel=args.channel, min_version=args.min_version)
    text = json.dumps(document, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        entry = document["releases"][0]
        print(f"manifest -> {args.output}")
        print(f"version {entry['version']}  sha256 {entry['sha256']}  "
              f"size {entry['size_bytes']}  signed: {'signature' in entry}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
