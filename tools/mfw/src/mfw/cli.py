"""mfw command line.

mfw identify DUMP                      which known firmware version the dump holds
mfw verify IMAGE                       container consistency (CRCs, lengths, inflate)
mfw check-listing LISTING [--dump D]   independent listing checks, version taken from the listing folder
mfw build DUMP --listing L --out OUT [--engine zopfli]   guarded rebuild; prints the flash range
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import container, listing, patch
from .versions import Version, all_versions, identify


def _layout(v: Version) -> container.Layout:
    return container.Layout(v.descriptor, v.prefix_len, v.len_field, v.tail_limit)


def _identify(img: bytes) -> Version:
    try:
        _, body = container.unpack(img, container.Layout())
    except (container.ContainerError, Exception) as e:  # not an MST9U flash image at all
        raise SystemExit(f"not a recognised MST9U flash image: {e}") from None
    v = identify(container.sha256(body))
    if v is None:
        raise SystemExit(
            f"unknown firmware (AP sha256 {container.sha256(body)}): no version file matches; "
            "see docs/guides/port-firmware-version.md"
        )
    return v


def _version_for_listing(path: Path) -> Version:
    """Listings live in firmware/targets/<model>/listings/<version>/; the folder names the version."""
    for v in all_versions():
        if v.version == path.resolve().parent.name and v.path.parent.parent == path.resolve().parent.parent.parent:
            return v
    raise SystemExit(f"no version file for listing folder {path.parent}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mfw")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("identify")
    s.add_argument("dump")
    s = sub.add_parser("verify")
    s.add_argument("image")
    s = sub.add_parser("check-listing")
    s.add_argument("listing")
    s.add_argument("--dump")
    s = sub.add_parser("build")
    s.add_argument("dump")
    s.add_argument("--listing", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--engine", default="zlib", choices=["zlib", "zopfli"])
    a = ap.parse_args(argv)

    if a.cmd == "identify":
        v = _identify(Path(a.dump).read_bytes())
        print(f"{v.model} firmware {v.version} ({v.path})")
    elif a.cmd == "verify":
        img = Path(a.image).read_bytes()
        problems = container.verify(img, container.Layout())
        print("OK" if not problems else "\n".join(problems))
        return 1 if problems else 0
    elif a.cmd == "check-listing":
        path = Path(a.listing)
        text = path.read_text()
        v = _identify(Path(a.dump).read_bytes()) if a.dump else _version_for_listing(path)
        problems = listing.check(text, set(v.symbols.values()), (v.cave_start, v.cave_end))
        print(f"{v.model} {v.version}: " + ("LISTING OK" if not problems else "\n".join(problems)))
        return 1 if problems else 0
    elif a.cmd == "build":
        img = Path(a.dump).read_bytes()
        v = _identify(img)
        lay = _layout(v)
        if container.verify(img, lay):
            raise SystemExit("the dump itself does not verify; re-dump the monitor")
        prefix, body = container.unpack(img, lay)
        p = container.parse(img, lay)
        if container.build(img, lay, body, stream=img[p.sstart : p.send]) != img:
            raise SystemExit("round-trip of the unmodified dump is not byte-identical; refusing")
        try:
            prefix2, body2, n = patch.apply(v, prefix, body, Path(a.listing).read_text())
        except patch.GuardError as e:
            raise SystemExit(f"guard failure, nothing written: {e}") from None
        new = container.build(img, lay, body2, prefix=prefix2, engine=a.engine)
        problems = container.verify(new, lay)
        if problems:
            raise SystemExit("built image does not verify: " + "; ".join(problems))
        Path(a.out).write_bytes(new)
        sectors = container.sector_diff(img, new)
        lo, hi = min(sectors), max(sectors) + 0x1000
        if lo < v.flash_write_start or hi > v.flash_write_end:
            raise SystemExit(f"changed sectors {lo:#x}..{hi:#x} fall outside the allowed flash range")
        print(f"{v.model} {v.version}: applied {n} bytes, image {a.out} sha256 {container.sha256(new)}")
        print(f"changed sectors: {len(sectors)}  flash range: -Start {lo:x} -End {hi:x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
