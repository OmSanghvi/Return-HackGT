#!/usr/bin/env python3
"""Cut a Gaussian-splat PLY down to a splat budget, for headsets (Quest 2/3).

Keeps the N splats that matter most (opacity x projected-area proxy), drops the
rest, and scales the kept splats up a little so the object keeps its coverage
(the kept splats' total area is matched to the original, capped). The input
must be a binary_little_endian PLY whose vertex properties are all floats (the
3DGS layout Fast-SAM3D and SHARP write, with or without normals / SH).

    python scripts/decimate_splats.py IN.ply OUT.ply --keep 25000 [--max-scale-up 1.3]

Standard library only. Prints the kept count, the share of the original area
kept, and the scale-up applied. ``scripts/sync_s3_assets_to_unity.py`` uses
``decimate`` to write the Quest-sized ``<name>_quest.ply`` copy of every splat
it syncs (docs/IMMERSIVE_SCENE_PIPELINE.md, "Quest budgets").

A file this can't read raises ``ValueError`` (the command line turns it into an
error message), so a caller can skip one bad file and carry on.
"""

from __future__ import annotations

import argparse
import array
import heapq
import math
import sys
from pathlib import Path

END_HEADER = b"end_header"
HEADER_LIMIT = 1 << 16  # a splat PLY header is a few hundred bytes


def _header_end(data: bytes, path: Path) -> int:
    """Offset of the first byte after ``end_header`` and its line break (LF or CRLF)."""
    at = data.find(END_HEADER)
    if at < 0:
        raise ValueError(f"{path}: no end_header (not a PLY file?)")
    end = at + len(END_HEADER)
    if data[end:end + 2] == b"\r\n":
        return end + 2
    if data[end:end + 1] == b"\n":
        return end + 1
    raise ValueError(f"{path}: malformed end_header line")


def _parse_header(lines: list[str], path: Path) -> tuple[list[str], int]:
    """(float vertex property names, vertex count) from the header lines."""
    if not lines or lines[0].strip() != "ply":
        raise ValueError(f"{path}: not a PLY file")
    if not any(line.startswith("format binary_little_endian") for line in lines):
        raise ValueError(f"{path}: only binary_little_endian PLY is supported")
    count, props, in_vertex = None, [], False
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "element":
            in_vertex = parts[1] == "vertex"
            if in_vertex:
                count = int(parts[2])
            elif count is not None:
                raise ValueError(f"{path}: elements after 'vertex' are not supported")
        elif parts[0] == "property" and in_vertex:
            if parts[1] != "float":
                raise ValueError(f"{path}: non-float vertex property {line!r}")
            props.append(parts[2])
    if count is None:
        raise ValueError(f"{path}: no vertex element")
    return props, count


def read_header(path: Path) -> tuple[list[str], list[str], int]:
    """(header lines, vertex property names, vertex count) without reading the splat data."""
    with open(path, "rb") as fh:
        head = fh.read(HEADER_LIMIT)
    end = _header_end(head, path)
    lines = head[:end].decode("ascii").splitlines()
    props, count = _parse_header(lines, path)
    return lines, props, count


def read_ply(path: Path) -> tuple[list[str], list[str], int, array.array]:
    data = path.read_bytes()
    end = _header_end(data, path)
    lines = data[:end].decode("ascii").splitlines()
    props, count = _parse_header(lines, path)
    floats = array.array("f")
    floats.frombytes(data[end:end + count * len(props) * 4])
    if len(floats) != count * len(props):
        raise ValueError(f"{path}: truncated ({len(floats)} of {count * len(props)} floats)")
    if sys.byteorder != "little":
        floats.byteswap()
    return lines, props, count, floats


def importance(floats: array.array, props: list[str], count: int) -> array.array:
    """opacity (sigmoid of the stored logit) x area proxy (exp(2/3 * sum of log scales))."""
    stride = len(props)
    o = props.index("opacity")
    s0, s1, s2 = (props.index(f"scale_{k}") for k in range(3))
    out = array.array("f", bytes(4 * count))
    for i in range(count):
        b = i * stride
        logit = floats[b + o]
        alpha = 0.0 if logit < -30.0 else 1.0 / (1.0 + math.exp(-logit))
        out[i] = alpha * math.exp((floats[b + s0] + floats[b + s1] + floats[b + s2]) * (2.0 / 3.0))
    return out


def decimate(src: Path, dst: Path, keep: int, max_scale_up: float) -> dict:
    """Write the ``keep`` most important splats of ``src`` to ``dst`` (all of them when
    ``keep`` >= the count, unchanged). Returns ``{"source", "kept", "area_share", "scale_up"}``.
    The output goes through ``<dst>.writing`` next to ``dst``, then replaces it."""
    if keep <= 0:
        raise ValueError("keep must be positive")
    src, dst = Path(src), Path(dst)
    lines, props, count, floats = read_ply(src)
    for name in ("opacity", "scale_0", "scale_1", "scale_2"):
        if name not in props:
            raise ValueError(f"{src}: no '{name}' property (not a Gaussian splat)")
    stride = len(props)
    if keep >= count:
        kept_ids = list(range(count))
        scale_up = 1.0
        area_share = 1.0
    else:
        imp = importance(floats, props, count)
        kept_ids = heapq.nlargest(keep, range(count), key=imp.__getitem__)
        kept_ids.sort()
        total = math.fsum(imp)
        kept = math.fsum(imp[i] for i in kept_ids)
        area_share = kept / total if total > 0 else 1.0
        # Area goes with the square of the linear scale.
        scale_up = min(max_scale_up, math.sqrt(1.0 / area_share)) if area_share > 0 else 1.0
        scale_up = max(1.0, scale_up)
    log_up = math.log(scale_up)
    scale_idx = [props.index(f"scale_{k}") for k in range(3)]
    out = array.array("f")
    for i in kept_ids:
        rec = floats[i * stride:(i + 1) * stride]
        if log_up:
            for k in scale_idx:
                rec[k] += log_up  # scales are stored as logs
        out.extend(rec)
    if sys.byteorder != "little":
        out.byteswap()
    header = "\n".join(
        f"element vertex {len(kept_ids)}" if line.startswith("element vertex ") else line for line in lines
    ) + "\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".writing")
    tmp.write_bytes(header.encode("ascii") + out.tobytes())
    tmp.replace(dst)
    return {"source": count, "kept": len(kept_ids), "area_share": area_share, "scale_up": scale_up}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    parser.add_argument("--keep", type=int, required=True, help="splat budget for the output")
    parser.add_argument("--max-scale-up", type=float, default=1.3,
                        help="cap on the coverage-preserving scale-up of kept splats (1 = none)")
    args = parser.parse_args(argv)
    if args.keep <= 0:
        parser.error("--keep must be positive")
    try:
        stats = decimate(args.src, args.dst, args.keep, max(1.0, args.max_scale_up))
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{args.src.name}: kept {stats['kept']:,} of {stats['source']:,} "
          f"({stats['area_share']:.0%} of the area), scale x{stats['scale_up']:.2f} -> {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
