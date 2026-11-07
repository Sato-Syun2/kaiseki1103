# `tracking_v2` SDK exporter: implementation rules

These instructions apply to the ZED SDK exporter in this folder and travel with its Windows distribution.

## Source and package boundaries

- This folder is the canonical source for `tracking_v2`. Do not edit the older exporter in the shared SDK package as a substitute.
- `prepare_tracking_sdk.py` creates a new, hash-verified Windows package from this folder. Keep source changes here, then prepare a new destination; do not overwrite an existing package or exchange results.
- This code runs on a Windows PC with ZED SDK and reads recorded SVO/SVO2 files. Corridor-coordinate conversion, trajectory analysis, and replay reports belong to the Ubuntu project.
- Do not depend on `experiment_recorder` internals or change its recording behavior from this exporter.

## SDK and Python environment

- Use the `pyzed` installed with ZED SDK 5.5 or later and the Python environment compatible with that SDK. Do not install `pyzed` from PyPI.
- Prefer the already working SDK Python environment. Do not upgrade or pin NumPy/OpenCV blindly; confirm compatibility with the installed SDK before changing dependencies.
- The Ubuntu machine may inspect and prepare these files, but it cannot claim a successful SDK run when its ZED GPU/driver environment is unavailable. Hardware validation status must remain explicit in the package manifest and reports.
- Use `NEURAL` as the depth mode. Do not introduce deprecated `QUALITY` as a default.

## Inputs, settings, and output safety

- Keep recording paths, output paths, setup IDs, run mode, frame limits, and optional features configurable through CLI arguments or the batch inventory. Do not hardcode a user's drive, recording number, or one-off output directory.
- Validate settings before opening the camera. Reject invalid ranges and ambiguous inputs with an actionable error.
- Treat SVO/SVO2 inputs as read-only. Compute and record the source hash where the format requires provenance; never modify, move, or delete the recording.
- On the Windows SDK PC, read large SVO/SVO2 files from a local disk or attached external SSD when a local copy is available; avoid streaming large inputs over `\\tsclient` because it is slower. Write all primary SDK output to the local Windows folder `<user home>\\kaiseki1103_exchange\\<tag>` (overridable with `--local-root`), then mirror the completed batch to the shared `exchange` path when available. A mirror failure must never discard or invalidate the local batch. The 2026-11-04 `test_005` local input is `F:\experiment_data\20261104_test\test_005\test_005.svo2`; keep it configurable because drive letters and copies can vary.
- Before starting SVO processing, snapshot child SDK tools into `<local-root>\\.sdk_tools\\<package-name>` so an active export does not need to read more program files from a possibly disconnected shared package.
- `export_svo_directory.py` recursively discovers `.svo` and `.svo2` files under a supplied local folder and writes one BODY_34 export and validation per selected input. `--include-parent-pattern` filters the immediate SVO parent directory using a case-insensitive glob, so calibration SVOs can be excluded from experiment batches. `--start-index` selects a 1-based position in the sorted filtered list while preserving the `recording_NNN` number, so interrupted batches can continue in a new output tag without reprocessing earlier recordings. Its required `--setup-id` is shared across that batch, so use it only when the physical camera setup is unchanged; split recordings into separate batches when the camera moved.
- `export_depth_batch.py` accepts repeated `(JOB_ID, SVO_PATH, SETUP_ID)` jobs, stages its child exporter locally, writes sparse ZED depth and validation output to the Windows local exchange folder, then transactionally mirrors the completed batch to shared storage.
- Refuse to reuse an existing output/tag directory. A failed run must be diagnosed and retried into a new destination; do not silently resume with stale images or rows.
- Keep per-recording logs and a batch summary so failures can be isolated. Batch CSV summaries are written once after processing rather than repeatedly truncating a shared file; each per-recording log records its exporter exit code.
- Mirror completed output transactionally through a temporary sibling directory and publish only after file names and sizes match. If the shared path is disconnected, leave the full local output intact and provide `sync_exchange.py` to retry after reconnection.

## Capture and SDK lifecycle

- Process every grabbed SVO frame for body/head detections. Choose image export times from the image timestamp/elapsed-time clock, independently of detector processing speed; do not use wall-clock timing to select SVO samples.
- Record original SVO frame index, image timestamp, detection timestamp, retrieval status, and whether an image was emitted. Preserve monotonic frame/time ordering.
- Check SDK return statuses and preserve the reason for missing or failed fields. Do not turn failed SDK calls or non-finite values into plausible measurements.
- Release camera and tracking resources on both success and failure. Keep SDK initialization and cleanup in structured `try/finally` or context-managed code.
- Convert SDK BGRA images to BGR before JPEG encoding. Keep image dimensions and file hashes in the export inventory.

## Body and head export semantics

- `body` mode uses BODY_34 and exports SDK body ID/state/confidence, 2D and camera-frame 3D keypoints, per-keypoint confidence, and related available fields.
- `heads` mode uses the explicit head detection model and exports object ID/label and head box/position fields. If that model is unavailable, fail clearly; do not silently substitute another model.
- Body and head modes are separate passes over the same SVO. Keep the source SVO hash, setup ID, camera calibration, and timing metadata so Ubuntu can verify they belong together. Body IDs and head/object IDs are separate identifier spaces and must not be equated.
- Record missing-field reasons. Keep segmentation disabled by default; when enabled, note that mask coordinates are local to the detection box and preserve the box needed to interpret them.
- `is_new` describes SDK result-container freshness; it does not prove that every joint was directly observed. Preserve it as metadata and do not use it as a per-joint visibility flag.

## Export contract and downstream compatibility

- Preserve the documented CSV column names, JSON encodings, units, coordinate frames, timestamp units, and file layout. If a schema must change, update the Ubuntu importer and this README in the same change.
- A body export contains `camera.json`, `manifest.json`, `frames.csv`, `bodies.csv`, `assets.csv`, and `images/`. A head export has the corresponding `heads.csv`. Optional segmentation writes `masks/`.
- Batch output includes the inventory, batch summary, per-recording logs, and package manifest. Keep source/package hashes consistent.
- Keep the primary export under the Windows local root and mirror the completed tree into the shared `exchange` directory when available. Do not copy raw SVOs to either output, and do not commit person images, skeletons, masks, or location data to the public Git repository.
- Update `README.md`, `package_manifest.json` generation, and any Ubuntu-side loader whenever a command, schema, model, SDK requirement, or output behavior changes.

## Editing style

- Keep SDK interaction, serialization, and command-line orchestration easy to inspect. Use named constants for schemas and model settings; avoid duplicating field definitions across modes.
- Use explicit units and coordinate-frame names in field names and metadata. Preserve non-finite-to-null handling for JSON and write files with stable encoding.
- Keep operational examples accurate to the current source and package. Distinguish a short frame-limited smoke run from a complete recording export so limited output cannot be mistaken for a full analysis.
