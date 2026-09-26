"""Repairs a specific non-finite-opacity bug in Fast-SAM3D's vendored
``Gaussian.save_ply()`` (``sam3d_objects...representations/gaussian/gaussian_model.py``,
cloned by ``bootstrap_fastsam3d.sh``): it writes
``inverse_sigmoid(sigmoid(raw_logit))`` with no epsilon or clamping, so any
splat whose sigmoid rounds to exactly 0.0/1.0 in the model's working
precision comes out as +-inf in the PLY's ``opacity`` column (this saturates
far more easily under ``FASTSAM3D_FP16=1``'s fp16 autocast than fp32, since
fp16 saturates sigmoid around |x| ~ 8-9 vs fp32's ~87). Unity's Gsplat
importer then fails the whole object's import on the first non-finite value
it finds.

This never touches the model or the vendored library's source -- it repairs
the ``.ply`` file ``save_ply`` already wrote, in place, after the fact. The
pure array logic (`sanitize_opacity_array`) has no GPU/torch/plyfile
dependency and is unit-tested directly; the file-level wrapper
(`sanitize_ply_opacity_file`) lazily imports `plyfile`, which is only
present in the Fast-SAM3D GPU environment, never in the lightweight local
worker venv.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

# A saturated splat was already "very opaque" or "very transparent" before
# save_ply's round-trip destroyed that value into inf -- this substitutes
# the most extreme representable logit instead, which is what the model
# actually meant, not an arbitrary guess. sigmoid(10) ~= 0.99995.
SAFE_LOGIT = 10.0


def sanitize_opacity_array(opacities: np.ndarray) -> tuple[np.ndarray, int]:
    """Replace non-finite values in a Gaussian PLY's opacity (logit) column.

    +inf becomes +SAFE_LOGIT (very opaque), -inf and NaN become -SAFE_LOGIT
    (very transparent -- an invisible splat is a far less misleading failure
    than a solid one for an unknown/NaN value). Returns
    ``(sanitized_array, count_replaced)``; on all-finite input, returns the
    input array unchanged with ``count_replaced == 0``.
    """
    finite = np.isfinite(opacities)
    bad_count = int((~finite).sum())
    if bad_count == 0:
        return opacities, 0
    sign = np.where(opacities == np.inf, 1.0, -1.0)
    fixed = np.where(finite, opacities, sign * SAFE_LOGIT)
    return fixed.astype(opacities.dtype, copy=False), bad_count


def sanitize_ply_opacity_file(path) -> int:
    """Read the Gaussian ``.ply`` at `path`, repair any non-finite
    ``opacity`` values in place, and return how many were fixed (0 means the
    file was left untouched).
    """
    from plyfile import PlyData  # noqa: PLC0415 - GPU-env-only dependency

    path = Path(path)
    # mmap=False: plyfile memory-maps binary PLYs by default, and rewriting
    # the same file while it's mapped truncates the pages under the array --
    # Linux then fails the write with EFAULT ("Bad address").
    plydata = PlyData.read(str(path), mmap=False)
    element = plydata.elements[0]
    opacities = np.asarray(element["opacity"])
    fixed, bad_count = sanitize_opacity_array(opacities)
    if bad_count:
        element["opacity"][:] = fixed
        # Write beside the original and swap, so a failed write never leaves
        # a truncated artifact behind.
        tmp_path = path.with_name(path.name + ".tmp")
        plydata.write(str(tmp_path))
        os.replace(tmp_path, path)
    return bad_count
