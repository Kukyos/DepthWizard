/**
 * Viewer bootstrap.
 *
 * Phase 4 builds the real thing: terrain from a server-produced DSM, the original image
 * projected onto it, three cameras, probe, overlays and the validation view
 * (docs/07-build-plan.md). What exists here is the scaffold plus a synthetic heightfield,
 * so the rendering stack, the camera cycle, the probe and the units badge are all real and
 * exercised from day one rather than stubbed.
 *
 * The synthetic terrain is explicitly labelled as such in the UI. It is scenery for an
 * empty room, not a result.
 */

import { Engine } from "@babylonjs/core/Engines/engine";
import { Scene } from "@babylonjs/core/scene";
import { ArcRotateCamera } from "@babylonjs/core/Cameras/arcRotateCamera";
import { FlyCamera } from "@babylonjs/core/Cameras/flyCamera";
import { UniversalCamera } from "@babylonjs/core/Cameras/universalCamera";
import { HemisphericLight } from "@babylonjs/core/Lights/hemisphericLight";
import { DirectionalLight } from "@babylonjs/core/Lights/directionalLight";
import { Vector3, Color3, Color4 } from "@babylonjs/core/Maths/math";
import { VertexData } from "@babylonjs/core/Meshes/mesh.vertexData";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { StandardMaterial } from "@babylonjs/core/Materials/standardMaterial";
import { Texture } from "@babylonjs/core/Materials/Textures/texture";
import type { Camera } from "@babylonjs/core/Cameras/camera";
// Side-effect import. Babylon's tree-shaken build leaves Ray out unless it is pulled in
// explicitly, and without it scene.pick silently returns nothing -- which is the height
// probe. Removing this line breaks measurement with only a console warning.
import "@babylonjs/core/Culling/ray";

/** How a height field is to be interpreted. Mirrors `Units` in server/depthwizard/config.py.
 *
 * A string union rather than a boolean, so "relative" is a first-class state and an unset
 * value cannot silently read as metres. Hard rule 2.
 */
type Units = "metres_absolute" | "metres_agl" | "relative_unitless";

/** Units carrying real metres. "relative" is deliberately absent. */
const METRIC: readonly Units[] = ["metres_absolute", "metres_agl"];

/** The subset of the server's SceneManifest the viewer needs. See docs/09-architecture.md. */
interface SceneManifest {
  id: string;
  units: Units;
  gsdOutM: number | null;
  objectsResolvable: boolean;
  confidenceM: number | null;
  meshSize?: number;
  heightFile?: string | null;
  textureFile?: string | null;
  verticalRange?: [number, number];
}

/** Fetch a scene exported by `python -m depthwizard.mesh`.
 *
 *  Returns null when there is none, so the viewer falls back to synthetic scenery rather
 *  than showing an error to someone who simply has not run the pipeline yet. Same-origin
 *  only: hard rule 6 forbids reaching off the machine. */
async function loadScene(
  base = "scene",
): Promise<{ manifest: SceneManifest; heights: Float32Array } | null> {
  try {
    const response = await fetch(`${base}/manifest.json`);
    if (!response.ok) return null;
    const manifest = (await response.json()) as SceneManifest;
    if (!manifest.heightFile || !manifest.meshSize) return null;
    const buffer = await (await fetch(`${base}/${manifest.heightFile}`)).arrayBuffer();
    const heights = new Float32Array(buffer);
    if (heights.length !== manifest.meshSize * manifest.meshSize) {
      console.error("height.bin does not match meshSize; ignoring scene");
      return null;
    }
    return { manifest, heights };
  } catch {
    return null;
  }
}

const el = <T extends HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing element #${id}`);
  return found as T;
};

// --------------------------------------------------------------------- units badge

/**
 * Render the units badge from the manifest.
 *
 * This is the UI enforcement of hard rule 2. It reads `units` from the manifest rather
 * than from any local flag, so there is no code path in which a relative scene presents a
 * value labelled in metres.
 */
function applyUnits(manifest: SceneManifest): void {
  const badge = el("units");
  const label = el("units-label");
  const metric = METRIC.includes(manifest.units);

  badge.classList.toggle("absolute", metric);
  if (!metric) {
    label.textContent = "relative — no metric scale";
    return;
  }
  // Above-ground and above-sea-level are both metres and are not the same claim. Saying
  // "absolute" for an nDSM would overstate by the terrain elevation, invisibly.
  const parts = [manifest.units === "metres_agl"
    ? "metres above ground"
    : "metres above sea level"];
  if (manifest.gsdOutM !== null) parts.push(`${manifest.gsdOutM.toFixed(2)} m/px`);
  if (!manifest.objectsResolvable) parts.push("terrain only — objects not resolvable");
  label.textContent = parts.join(" · ");
}

/**
 * Format a height for display.
 *
 * Returns an unlabelled, deliberately unitless string for a relative scene. Any caller
 * that wants to append "m" has to go through here and cannot, which is the point.
 */
function formatHeight(value: number, manifest: SceneManifest): string {
  if (!METRIC.includes(manifest.units)) {
    return `${value.toFixed(3)} (relative)`;
  }
  const band = manifest.confidenceM === null ? "" : ` ± ${manifest.confidenceM.toFixed(1)}`;
  const datum = manifest.units === "metres_agl" ? " AGL" : " ASL";
  return `${value.toFixed(1)}${band} m${datum}`;
}

// ------------------------------------------------------------------ placeholder mesh

/**
 * Build a mesh from a height field.
 *
 * Phase 4 replaces the source of `heights` with a real DSM and adds LOD and texture
 * projection; the geometry construction is the same shape of work, so it is written here
 * rather than mocked. Row-major, `size` samples per side, spanning `extent` world units.
 */
function heightFieldMesh(
  name: string,
  heights: Float32Array,
  size: number,
  extent: number,
  scene: Scene,
): Mesh {
  const positions = new Float32Array(size * size * 3);
  const uvs = new Float32Array(size * size * 2);
  const step = extent / (size - 1);

  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      const i = row * size + col;
      positions[i * 3] = col * step - extent / 2;
      positions[i * 3 + 1] = heights[i] ?? 0;
      positions[i * 3 + 2] = row * step - extent / 2;
      uvs[i * 2] = col / (size - 1);
      uvs[i * 2 + 1] = row / (size - 1);
    }
  }

  // Two triangles per cell. Uint32 because a 1024-sample field exceeds 16-bit indices.
  const indices = new Uint32Array((size - 1) * (size - 1) * 6);
  let k = 0;
  for (let row = 0; row < size - 1; row++) {
    for (let col = 0; col < size - 1; col++) {
      const tl = row * size + col;
      const tr = tl + 1;
      const bl = tl + size;
      const br = bl + 1;
      indices[k++] = tl; indices[k++] = bl; indices[k++] = tr;
      indices[k++] = tr; indices[k++] = bl; indices[k++] = br;
    }
  }

  const normals: number[] = [];
  VertexData.ComputeNormals(positions, indices, normals);

  const mesh = new Mesh(name, scene);
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.normals = normals;
  data.uvs = uvs;
  data.applyToMesh(mesh);
  return mesh;
}

/** A synthetic field, so the scene is not empty before Phase 4. Not a result. */
function syntheticField(size: number): Float32Array {
  const heights = new Float32Array(size * size);
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      const x = (col / size) * Math.PI * 4;
      const y = (row / size) * Math.PI * 4;
      // Smooth relief, plus a few blocks so there is something to probe and to cast shadow.
      let h = Math.sin(x) * Math.cos(y) * 2.5;
      const inBlock = col % 24 > 16 && row % 24 > 16 && col > size * 0.2 && row > size * 0.2;
      if (inBlock) h += 12;
      heights[row * size + col] = h;
    }
  }
  return heights;
}

// ------------------------------------------------------------------------ cameras

type CameraKind = "orbit" | "fly" | "ground";

function makeCameras(scene: Scene): Record<CameraKind, Camera> {
  // Framed to show the whole 300-unit extent rather than a close crop of it.
  const orbit = new ArcRotateCamera("orbit", -Math.PI / 2, 0.95, 340, Vector3.Zero(), scene);
  orbit.lowerRadiusLimit = 10;
  orbit.upperRadiusLimit = 900;
  orbit.wheelDeltaPercentage = 0.02;

  // FlyCamera is Babylon's purpose-built 6-DOF camera: the flythrough the brief asks for.
  const fly = new FlyCamera("fly", new Vector3(0, 60, -120), scene);
  fly.rollCorrect = 10;
  fly.bankedTurn = true;
  fly.setTarget(Vector3.Zero());

  // Ground-level first-person, for reading structure heights from street level.
  const ground = new UniversalCamera("ground", new Vector3(0, 18, -60), scene);
  ground.speed = 1.5;
  ground.setTarget(Vector3.Zero());

  // Attached individually and with the current single-argument API: iterating widens the
  // type to the Camera base class, whose attachControl signature differs from the
  // concrete cameras' overloads. Babylon takes the input element from the engine.
  orbit.attachControl(true);
  fly.attachControl(true);
  ground.attachControl(true);

  return { orbit, fly, ground };
}

// --------------------------------------------------------------------------- main

async function main(): Promise<void> {
  const canvas = el<HTMLCanvasElement>("canvas");
  const engine = new Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
  const scene = new Scene(engine);
  scene.clearColor = new Color4(0.05, 0.07, 0.09, 1);

  // Metres are earned from a CRS, never assumed — so the fallback declares itself
  // relative, which is also the correct state for the non-georeferenced path.
  const loaded = await loadScene();
  const manifest: SceneManifest = loaded?.manifest ?? {
    id: "synthetic placeholder",
    units: "relative_unitless",
    gsdOutM: null,
    objectsResolvable: true,
    confidenceM: null,
  };
  applyUnits(manifest);
  el("r-scene").textContent = loaded ? manifest.id : "synthetic placeholder";

  // A low sun angle is deliberate: raking light is what makes relief legible on terrain,
  // and it is the same cue the shadow anchor exploits (docs/05-domain-reference.md).
  const sky = new HemisphericLight("sky", new Vector3(0, 1, 0), scene);
  sky.intensity = 1.25;
  sky.groundColor = new Color3(0.3, 0.32, 0.36);
  const sun = new DirectionalLight("sun", new Vector3(-0.6, -0.55, 0.55), scene);
  sun.intensity = 1.1;

  const EXTENT = 300;
  const size = loaded ? (manifest.meshSize as number) : 192;
  // A relative field spans 0..1, which is invisible against a 300-unit extent. Exaggeration
  // is applied explicitly and reported in the UI — never silently, since a silent factor
  // would make every height on screen a lie.
  const [lo, hi] = manifest.verticalRange ?? [0, 1];
  const span = Math.max(hi - lo, 1e-6);
  const exaggeration = loaded ? (EXTENT * 0.12) / span : 1;
  const field = loaded
    ? Float32Array.from(loaded.heights, (h) => (h - lo) * exaggeration)
    : syntheticField(size);

  const terrain = heightFieldMesh("terrain", field, size, EXTENT, scene);
  const material = new StandardMaterial("terrain", scene);
  material.specularColor = new Color3(0.04, 0.04, 0.04);
  material.backFaceCulling = false;
  if (loaded && manifest.textureFile) {
    // The optical image draped over the geometry. Projection accuracy is the first thing
    // the evaluation criteria name, so the UVs map 1:1 to the source grid with no offset.
    const texture = new Texture(`scene/${manifest.textureFile}`, scene, false, false);
    texture.wrapU = Texture.CLAMP_ADDRESSMODE;
    texture.wrapV = Texture.CLAMP_ADDRESSMODE;
    material.diffuseTexture = texture;
    material.diffuseColor = new Color3(1, 1, 1);
    // Satellite imagery is often dark (this scene is winter, mean RGB ~87,77,67). An
    // emissive copy keeps the photo readable while the directional light still shades the
    // relief, so the terrain reads as 3D rather than as a flat unlit map.
    material.emissiveTexture = texture;
    material.linkEmissiveWithDiffuse = false;
  } else {
    material.diffuseColor = new Color3(0.62, 0.66, 0.70);
  }
  terrain.material = material;
  if (loaded) {
    el("r-exag").textContent = `${exaggeration.toFixed(1)}x (display only)`;
  }

  const cameras = makeCameras(scene);
  const order: CameraKind[] = ["orbit", "fly", "ground"];
  let current = 0;

  // Controls are attached once in makeCameras; Babylon routes input to the active camera,
  // so switching is just a reassignment. Each camera keeps its own position across
  // switches, which is the behaviour we want.
  const activate = (kind: CameraKind): void => {
    scene.activeCamera = cameras[kind];
    el("r-camera").textContent = kind;
  };
  activate("orbit");

  window.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() !== "c") return;
    current = (current + 1) % order.length;
    activate(order[current] as CameraKind);
  });

  // Height probe. Phase 4 reports the stored DSM value at the picked pixel; here it reads
  // the mesh, which exercises the same picking path and the same formatting rule.
  //
  // Listening on the canvas rather than scene.onPointerDown: the scene-level pointer
  // callbacks depend on Babylon's input manager being attached, which is easy to break by
  // changing how cameras attach their controls. A canvas listener has no such coupling.
  //
  // ponytail: fires on drag-release too, so orbiting also re-probes. Harmless here;
  // Phase 4 should distinguish click from drag once the readout means something.
  canvas.addEventListener("pointerdown", (event) => {
    const hit = scene.pick(event.offsetX, event.offsetY);
    if (!hit?.hit || !hit.pickedPoint) {
      el("r-height").textContent = "—";
      return;
    }
    // Undo the display exaggeration: the readout must be the value stored in the DSM, not
    // the one the mesh was stretched to. Reporting the stretched number would be wrong by
    // a factor nobody could see.
    const stored = hit.pickedPoint.y / exaggeration + lo;
    el("r-height").textContent = formatHeight(stored, manifest);
  });

  engine.runRenderLoop(() => scene.render());
  window.addEventListener("resize", () => engine.resize());
}

void main();
