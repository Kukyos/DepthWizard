"""HTTP API: upload an image, get back a navigable scene.

    python -m uvicorn depthwizard.api:app --port 8000

The brief's second deliverable is an interface where a user uploads imagery, flies through
the reconstruction, and validates heights against reference data. This is the server side of
that: it runs the same pipeline the CLI and the eval harness run, with no privileged path
(hard rule 4), and serves the scene the viewer loads.

Uploads land in a scratch directory keyed by a content hash, so re-uploading the same image
returns the existing scene instead of recomputing it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import backbone, config, dsm, mesh

app = FastAPI(title="DepthWizard", version="0.1.0")

# The viewer is served from a different port in development. Localhost only -- the pipeline
# is offline by design (hard rule 6) and this should never be reachable from anywhere else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:{config.VIEWER_PORT}",
                   f"http://127.0.0.1:{config.VIEWER_PORT}"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SCENES = Path(tempfile.gettempdir()) / "depthwizard-scenes"
SCENES.mkdir(parents=True, exist_ok=True)

ACCEPTED = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".h5"}
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Enough to tell whether a demo is about to go badly."""
    device = backbone.pick_device()
    weights = config.WEIGHTS_DIR / "height_head.pt"
    return {
        "status": "ok",
        "device": device,
        "cuda": device == "cuda",
        "trained_weights": weights.exists(),
        "scenes": len(list(SCENES.glob("*/manifest.json"))),
        # Surfaced rather than buried: a caller can see which numbers rest on unsourced
        # values without reading the docs.
        "unsourced_values": [p.key for p in config.placeholders()],
    }


@app.post("/api/process")
async def process(
    image: UploadFile = File(...),
    reference: UploadFile | None = File(None),
) -> JSONResponse:
    """Upload an image, run the pipeline, return the scene manifest.

    An optional reference height raster enables the validation view -- the brief puts
    validating estimates against reference data inside the app, as a user action.
    """
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ACCEPTED:
        raise HTTPException(
            400, f"unsupported file type '{suffix}'. Accepted: {sorted(ACCEPTED)}")

    payload = await image.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"upload is {len(payload)/2**20:.0f} MB; limit is "
                                 f"{MAX_UPLOAD_BYTES/2**20:.0f} MB")

    # Content hash, so the same image twice is one scene rather than two.
    scene_id = hashlib.sha256(payload).hexdigest()[:16]
    scene_dir = SCENES / scene_id
    if (scene_dir / "manifest.json").exists():
        return JSONResponse(_manifest(scene_id) | {"cached": True})

    work = scene_dir / "input"
    work.mkdir(parents=True, exist_ok=True)
    source = work / f"upload{suffix}"
    source.write_bytes(payload)

    reference_path = None
    if reference is not None and reference.filename:
        reference_path = work / f"reference{Path(reference.filename).suffix.lower()}"
        reference_path.write_bytes(await reference.read())

    weights = config.WEIGHTS_DIR / "height_head.pt"
    try:
        product = dsm.estimate(source, weights=weights if weights.exists() else None)
        raster = scene_dir / "dsm.tif"
        from . import io_raster

        io_raster.write_dsm(raster, product.heights, product.meta, product.provenance)
        mesh.export(raster, scene_dir, source, reference_path=reference_path)
    except ValueError as exc:
        # Malformed input is a user error, not a server fault. "Software stability" is in
        # the evaluation criteria, and a traceback on screen is how you lose it.
        shutil.rmtree(scene_dir, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:                          # noqa: BLE001
        shutil.rmtree(scene_dir, ignore_errors=True)
        raise HTTPException(500, f"processing failed: {type(exc).__name__}: {exc}") from exc

    return JSONResponse(_manifest(scene_id) | {"cached": False})


def _manifest(scene_id: str) -> dict[str, Any]:
    path = SCENES / scene_id / "manifest.json"
    if not path.exists():
        raise HTTPException(404, f"no scene {scene_id}")
    return {"sceneId": scene_id, **json.loads(path.read_text(encoding="utf8"))}


@app.get("/api/scene/{scene_id}")
def scene(scene_id: str) -> dict[str, Any]:
    return _manifest(_safe(scene_id))


@app.get("/api/scene/{scene_id}/{filename}")
def scene_file(scene_id: str, filename: str) -> FileResponse:
    """Serve one file from a scene.

    Both path segments are checked rather than trusted: a scene id is hex and a filename
    must resolve inside its own directory. Path traversal through a download endpoint is the
    oldest trick there is.
    """
    path = SCENES / _safe(scene_id) / Path(filename).name
    if not path.is_file():
        raise HTTPException(404, f"no file {filename} in scene {scene_id}")
    return FileResponse(path)


@app.get("/api/scene/{scene_id}/download/dsm")
def download_dsm(scene_id: str) -> FileResponse:
    """The GeoTIFF itself -- the brief's first deliverable, in a standard geospatial format."""
    path = SCENES / _safe(scene_id) / "dsm.tif"
    if not path.is_file():
        raise HTTPException(404, "no DSM for this scene")
    return FileResponse(path, media_type="image/tiff", filename=f"{scene_id}_DSM.tif")


def _safe(scene_id: str) -> str:
    if not scene_id.isalnum() or len(scene_id) > 32:
        raise HTTPException(400, "bad scene id")
    return scene_id


# Serve the built viewer when it exists, so the packaged app is one process rather than two.
_dist = config.ROOT / "viewer" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="viewer")
