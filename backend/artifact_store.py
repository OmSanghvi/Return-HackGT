"""Artifact storage for SketchScape reconstruction outputs.

This module owns the *only* place the API stores and serves PLY, mask, and
preview files produced by the GPU worker. It provides one ``ArtifactStore``
surface with two backends:

- ``LocalArtifactStore`` (default): files land under the existing
  ``ARTIFACT_ROOT`` directory on the API host. The ``/v1/artifacts/…``
  endpoint streams them directly via ``FileResponse``. No external service
  required; powers the local demo and all tests.

- ``S3ArtifactStore``: files are streamed to an S3 bucket under a namespaced
  ``artifacts/<job_id>/`` prefix. The serving endpoint issues a short-lived
  (5-minute) presigned GET URL and redirects the Unity client to it.
  ``boto3`` is imported lazily so the dependency stays optional.

Backend is selected by ``SKETCHSCAPE_ARTIFACTS_BACKEND`` (``local`` or ``s3``).
The S3 backend also reads ``SKETCHSCAPE_ARTIFACTS_BUCKET`` (and optionally
``AWS_REGION``). Both values are emitted by ``terraform output`` after
``enable_artifacts_bucket = true``.

Design constraints:
- Neither backend buffers a full PLY in memory. The local backend writes from
  an ``asyncio`` ``UploadFile`` using chunked async reads; the S3 backend uses
  a ``TransferConfig`` multipart upload from a temp file so the FastAPI request
  body is never entirely in RAM for large PLYs.
- The local backend is always the fallback for tests; the test suite never
  contacts AWS.
- Artifact URLs returned by ``put()`` are backend-agnostic relative paths
  (``/v1/artifacts/{job_id}/{filename}``). The serving endpoint resolves them
  via whichever backend is active.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

if TYPE_CHECKING:  # pragma: no cover
    pass


# Presigned URL TTL in seconds.
_PRESIGN_TTL = 300


class ArtifactStore(ABC):
    """The persistence surface every artifact backend must implement."""

    @abstractmethod
    async def put(
        self,
        job_id: str,
        filename: str,
        source: UploadFile,
        *,
        size_limit: int,
    ) -> str:
        """Write ``source`` and return the canonical artifact URL path.

        The returned value is always ``/v1/artifacts/{job_id}/{filename}`` so
        route handlers and scene JSON are backend-agnostic.
        """

    @abstractmethod
    async def copy_local(
        self,
        job_id: str,
        filename: str,
        source_path: Path,
    ) -> str:
        """Copy an existing local file (e.g. the input image) into the store.

        Returns the same canonical URL form as ``put()``.
        """

    @abstractmethod
    async def serve(self, job_id: str, filename: str) -> Response:
        """Return a FastAPI response that delivers the artifact to the client."""

    @abstractmethod
    def exists(self, job_id: str, filename: str) -> bool:
        """Return True if the artifact is present in the store."""

    @staticmethod
    def artifact_url(job_id: str, filename: str) -> str:
        """Canonical relative URL for any artifact, regardless of backend."""
        return f"/v1/artifacts/{job_id}/{filename}"


class LocalArtifactStore(ArtifactStore):
    """Filesystem-backed artifact store under ``artifact_root``.

    Writes arrive as bounded chunked reads so a large PLY upload never loads
    the full file into the API process's heap.
    """

    def __init__(self, artifact_root: Path) -> None:
        self._root = Path(artifact_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str, filename: str) -> Path:
        return self._root / job_id / filename

    def _job_dir(self, job_id: str) -> Path:
        job_dir = self._root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    async def put(
        self,
        job_id: str,
        filename: str,
        source: UploadFile,
        *,
        size_limit: int,
    ) -> str:
        destination = self._job_dir(job_id) / filename
        size = 0
        with destination.open("wb") as output:
            while chunk := await source.read(1024 * 1024):
                size += len(chunk)
                if size > size_limit:
                    output.close()
                    destination.unlink(missing_ok=True)
                    from fastapi import HTTPException  # noqa: PLC0415
                    raise HTTPException(
                        413,
                        f"Artifact exceeds the {size_limit // 1024 // 1024} MB limit.",
                    )
                output.write(chunk)
        if not size:
            destination.unlink(missing_ok=True)
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(400, "Artifact upload was empty.")
        return self.artifact_url(job_id, filename)

    async def copy_local(
        self,
        job_id: str,
        filename: str,
        source_path: Path,
    ) -> str:
        dest = self._job_dir(job_id) / filename
        shutil.copy2(source_path, dest)
        return self.artifact_url(job_id, filename)

    async def serve(self, job_id: str, filename: str) -> Response:
        path = self._path(job_id, filename)
        if not path.is_file():
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(404, "Artifact does not exist.")
        return FileResponse(path, filename=filename)

    def exists(self, job_id: str, filename: str) -> bool:
        return self._path(job_id, filename).is_file()


class S3ArtifactStore(ArtifactStore):
    """S3-backed artifact store.

    Objects land at ``s3://<bucket>/artifacts/<job_id>/<filename>``. Serving
    issues a short-lived (``_PRESIGN_TTL`` second) presigned GET URL and
    redirects the client to it, so the API process never proxies large PLY
    bytes.

    ``boto3`` is imported lazily; selecting this backend without it installed
    raises a clear ``RuntimeError``.

    The S3 upload uses ``boto3.s3.transfer.TransferConfig`` multipart so large
    PLY files are sent in chunks without loading them fully into memory. Since
    FastAPI ``UploadFile`` is async and boto3 upload is sync, the implementation
    writes to a temp file first then uploads — acceptable for the single-GPU
    hackathon throughput (one job at a time).
    """

    _S3_PREFIX = "artifacts"

    def __init__(self, bucket: str, *, region_name: str | None = None) -> None:
        if not bucket:
            raise RuntimeError(
                "S3ArtifactStore requires a bucket name. "
                "Set SKETCHSCAPE_ARTIFACTS_BUCKET or use SKETCHSCAPE_ARTIFACTS_BACKEND=local."
            )
        self._bucket = bucket
        self._region_name = region_name
        self._client = None  # resolved lazily

    def _boto_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # noqa: PLC0415
        except ImportError as err:
            raise RuntimeError(
                "The S3 artifact backend requires boto3. "
                "Install it with `pip install boto3`, or use "
                "SKETCHSCAPE_ARTIFACTS_BACKEND=local."
            ) from err
        self._client = boto3.client("s3", region_name=self._region_name)
        return self._client

    def _s3_key(self, job_id: str, filename: str) -> str:
        return f"{self._S3_PREFIX}/{job_id}/{filename}"

    async def put(
        self,
        job_id: str,
        filename: str,
        source: UploadFile,
        *,
        size_limit: int,
    ) -> str:
        """Buffer to a temp file then multipart-upload to S3."""
        from boto3.s3.transfer import TransferConfig  # noqa: PLC0415

        fd, tmp_path_str = tempfile.mkstemp(suffix=Path(filename).suffix)
        tmp_path = Path(tmp_path_str)
        try:
            size = 0
            with os.fdopen(fd, "wb") as tmp:
                while chunk := await source.read(1024 * 1024):
                    size += len(chunk)
                    if size > size_limit:
                        from fastapi import HTTPException  # noqa: PLC0415
                        raise HTTPException(
                            413,
                            f"Artifact exceeds the {size_limit // 1024 // 1024} MB limit.",
                        )
                    tmp.write(chunk)
            if not size:
                from fastapi import HTTPException  # noqa: PLC0415
                raise HTTPException(400, "Artifact upload was empty.")
            config = TransferConfig(multipart_threshold=8 * 1024 * 1024)
            self._boto_client().upload_file(
                str(tmp_path),
                self._bucket,
                self._s3_key(job_id, filename),
                Config=config,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        return self.artifact_url(job_id, filename)

    async def copy_local(
        self,
        job_id: str,
        filename: str,
        source_path: Path,
    ) -> str:
        from boto3.s3.transfer import TransferConfig  # noqa: PLC0415

        config = TransferConfig(multipart_threshold=8 * 1024 * 1024)
        self._boto_client().upload_file(
            str(source_path),
            self._bucket,
            self._s3_key(job_id, filename),
            Config=config,
        )
        return self.artifact_url(job_id, filename)

    async def serve(self, job_id: str, filename: str) -> Response:
        """Redirect to a short-lived presigned GET URL."""
        url = self._boto_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": self._s3_key(job_id, filename)},
            ExpiresIn=_PRESIGN_TTL,
        )
        return RedirectResponse(url, status_code=302)

    def exists(self, job_id: str, filename: str) -> bool:
        try:
            self._boto_client().head_object(
                Bucket=self._bucket, Key=self._s3_key(job_id, filename)
            )
            return True
        except Exception:
            return False


def create_artifact_store(
    *,
    local_artifact_root: Path,
    backend: str | None = None,
) -> ArtifactStore:
    """Build the configured artifact store.

    Selection order:
    - ``backend`` argument when given (used by tests),
    - else ``SKETCHSCAPE_ARTIFACTS_BACKEND`` (``local`` default, or ``s3``).

    The S3 backend reads ``SKETCHSCAPE_ARTIFACTS_BUCKET`` and optional
    ``AWS_REGION``. It never runs unless explicitly selected.
    """
    selected = (
        backend or os.environ.get("SKETCHSCAPE_ARTIFACTS_BACKEND", "local")
    ).strip().lower()

    if selected in {"", "local", "file", "filesystem"}:
        return LocalArtifactStore(local_artifact_root)

    if selected in {"s3", "aws", "aws-s3"}:
        return S3ArtifactStore(
            os.environ.get("SKETCHSCAPE_ARTIFACTS_BUCKET", ""),
            region_name=os.environ.get("AWS_REGION") or None,
        )

    raise RuntimeError(
        f"Unknown SKETCHSCAPE_ARTIFACTS_BACKEND '{selected}'. Use 'local' or 's3'."
    )
