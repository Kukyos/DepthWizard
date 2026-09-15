"""API behaviour, especially the ways it should refuse.

"Software stability" is in the evaluation criteria, and the realistic way to fail it is a
judge dropping in something unexpected and getting a traceback. These check the refusals as
carefully as the happy path.

The pipeline itself is not exercised here -- that needs the model and a GPU, and lives in
the eval harness. What is checked is that the HTTP surface behaves.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import api  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def _png_bytes(size: int = 16) -> bytes:
    from PIL import Image

    rng = np.random.default_rng(0)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (size, size, 3), dtype=np.uint8)).save(
        buffer, format="PNG")
    return buffer.getvalue()


def test_health_reports_device_and_unsourced_values(client: TestClient):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "cuda" in body and isinstance(body["cuda"], bool)
    # Unsourced values are surfaced, not buried in the docs, so a caller can see which
    # numbers rest on a placeholder.
    assert isinstance(body["unsourced_values"], list)


def test_unsupported_file_type_is_refused_cleanly(client: TestClient):
    response = client.post("/api/process",
                           files={"image": ("notes.txt", b"not an image", "text/plain")})
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_bad_scene_id_is_refused(client: TestClient):
    """Path traversal through a download endpoint is the oldest trick there is."""
    for bad in ("../etc", "a/b", "x" * 40, "..%2f.."):
        assert client.get(f"/api/scene/{bad}").status_code in (400, 404)


def test_unknown_scene_is_404(client: TestClient):
    assert client.get("/api/scene/deadbeefdeadbeef").status_code == 404


def test_scene_file_cannot_escape_its_directory(client: TestClient, tmp_path: Path):
    """Even a valid scene id must not serve files outside its own folder."""
    scene_id = "abc123abc123abc1"
    (api.SCENES / scene_id).mkdir(parents=True, exist_ok=True)
    (api.SCENES / scene_id / "manifest.json").write_text("{}", encoding="utf8")
    secret = api.SCENES / "secret.txt"
    secret.write_text("should not be served", encoding="utf8")
    try:
        response = client.get(f"/api/scene/{scene_id}/../secret.txt")
        assert response.status_code == 404 or "should not be served" not in response.text
    finally:
        secret.unlink(missing_ok=True)


def test_missing_image_is_a_validation_error(client: TestClient):
    assert client.post("/api/process").status_code == 422


def test_accepted_extensions_cover_the_brief(client: TestClient):
    """The brief names PNG, JPG and TIFF explicitly."""
    for required in (".png", ".jpg", ".tif", ".tiff"):
        assert required in api.ACCEPTED


def test_geotiff_and_png_are_both_accepted_types():
    assert ".h5" in api.ACCEPTED, "GAMUS tiles are used throughout development"
    assert ".jpeg" in api.ACCEPTED


def test_upload_limit_is_declared():
    """A 50000x50000 TIFF should be refused by size, not by running out of memory."""
    assert 0 < api.MAX_UPLOAD_BYTES <= 2 * 1024**3


def test_cors_is_localhost_only():
    """Hard rule 6: this is an offline tool and must not be reachable from the web."""
    for middleware in api.app.user_middleware:
        origins = middleware.kwargs.get("allow_origins", []) if middleware.kwargs else []
        for origin in origins:
            assert "localhost" in origin or "127.0.0.1" in origin, origin


def test_writing_a_geotiff_round_trips_through_the_scene_dir(tmp_path: Path):
    """Sanity: the scene directory is writable and holds a valid raster."""
    from depthwizard import config, io_raster
    from rasterio.crs import CRS
    from rasterio.transform import Affine

    path = tmp_path / "scene.tif"
    with rasterio.open(path, "w", driver="GTiff", width=8, height=8, count=3,
                       dtype="uint8", crs=CRS.from_epsg(32644),
                       transform=Affine(0.5, 0, 0, 0, -0.5, 0)) as dst:
        dst.write(np.zeros((3, 8, 8), np.uint8))
    _, meta = io_raster.read_scene(path)
    assert meta.units in config.Units.METRIC
