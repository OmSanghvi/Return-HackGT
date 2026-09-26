# Graph Report - HackGT  (2026-09-25)

## Corpus Check
- 0 files · ~58,811 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 881 nodes · 1601 edges · 53 communities (43 shown, 10 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 46 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Project Persistence Layer
- Shared Room Feature & Agent Concepts
- Pipeline Docs & Infra Concepts
- Experience Blueprint Schema (Defs)
- Unity Scene Profile Schema
- FastSAM3D Reconstruction Pipeline
- Scene Schema (Legacy)
- SAM3D ZeroGPU HF Space & AWS Smoke Test
- Backend API Models
- Worker Contract Schema
- Core Module Imports & Blender Export
- Subject Labeling
- Asset Upload Endpoint
- DynamoDB & Storage Contract Tests
- Artifact Store Core & Factory Tests
- Multi-View Provenance Tests
- Local Artifact Store Tests
- S3 Artifact Store & Tests
- Read Endpoints
- Worker Job Server
- Worker Job Runner Script
- Blueprint Environment Schema
- Local Artifact Store Core
- SAM3D GPU HF Space
- AWS Bootstrap Script
- Reconstruction Job Handling
- Blueprint Experience Metadata Schema
- Reconstruction API Tests
- Blueprint Objects & Portals Schema
- Worker Job Runner (Core Logic)
- Worker Server Job Execution
- Scene Action Endpoints
- Unity Scene Profile Instance
- Worker Auth Endpoints
- Upload Labeling Tests
- Blueprint AR/VR Navigation Schema
- Experience Blueprint Schema Root
- FastSAM3D Source Prep Script
- Scene Compilation & Legacy Sketch
- Blueprint Publish Endpoints
- Storage Factory Tests
- Fake S3 Client Tests
- Subject Labeler Backend Tests
- Worker HTTP Handler
- AWS Preflight Check Script
- FastSAM3D Bootstrap Script
- Artifact Store Serve Endpoint
- Blueprint Project ID Field
- Blueprint Revision Field
- AWS Publish Bundle Script
- Mock Demo Start Script
- Local Verify Script
- SAM3.1 Local Bootstrap Script

## God Nodes (most connected - your core abstractions)
1. `docs/BUILD_PLAN.md` - 38 edges
2. `DynamoDbStore` - 22 edges
3. `LocalJsonStore` - 22 edges
4. `create_reconstruction()` - 22 edges
5. `docs/PROJECT_STATUS.md` - 21 edges
6. `AuthoringStore` - 20 edges
7. `ProjectAsset` - 19 edges
8. `ProjectRecord` - 19 edges
9. `add_asset_view()` - 19 edges
10. `immersive-reveal-staging skill` - 19 edges

## Surprising Connections (you probably didn't know these)
- `run_s3_smoke()` --calls--> `create_artifact_store()`  [INFERRED]
  scripts/smoke_test_aws_storage.py → backend/artifact_store.py
- `run_dynamodb_smoke()` --calls--> `create_store()`  [INFERRED]
  scripts/smoke_test_aws_storage.py → backend/storage.py
- `_make_blueprint()` --references--> `ExperienceBlueprint`  [EXTRACTED]
  scripts/smoke_test_aws_storage.py → backend/main.py
- `_make_asset()` --references--> `ProjectAsset`  [EXTRACTED]
  scripts/smoke_test_aws_storage.py → backend/main.py
- `_make_project()` --references--> `ProjectRecord`  [EXTRACTED]
  scripts/smoke_test_aws_storage.py → backend/main.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Build Plan step-to-skill roster (steps 1-12)** — claude_skills_meta_track_alignment_skill, claude_skills_contributor_data_model_skill, claude_skills_contributor_api_endpoints_skill, claude_skills_nemoclaw_agent_setup_skill, claude_skills_nemoclaw_scene_tools_skill, claude_skills_nemoclaw_subject_labeling_skill, claude_skills_connection_compose_endpoint_skill, claude_skills_immersive_reveal_staging_skill, claude_skills_nemoclaw_environment_sourcing_skill, claude_skills_sketch_image_gen_backends_skill, claude_skills_unity_diegetic_attribution_skill, claude_skills_meta_hardware_polish_skill, claude_skills_gpu_cloud_activation_skill, claude_skills_unity_offline_builder_and_rendering_skill, claude_skills_demo_video_prep_skill [EXTRACTED 1.00]
- **Immersive scene-craft open-source toolkit** — concept_vr_builder, concept_primetween, concept_tweenplayables, concept_urp_volumetric_light, concept_visualeffectgraph_samples, concept_resonance_audio, concept_mms_tts, concept_xri_haptics [EXTRACTED 1.00]
- **NemoClaw scene-authoring tool suite** — concept_nemoclaw_agent, nemoclaw_tool_place_objects_in_scene, nemoclaw_tool_read_sketch_layout, nemoclaw_tool_stage_immersive_reveal, nemoclaw_tool_identify_subject, nemoclaw_tool_find_object_image, nemoclaw_tool_trigger_unity_scene_update [EXTRACTED 1.00]
- **NemoClaw's authored toolset for scene composition and staging** — concept_nemoclaw, concept_place_objects_in_scene, concept_read_sketch_layout, concept_stage_immersive_reveal, concept_trigger_unity_scene_update [EXTRACTED 1.00]
- **Cloud storage backend provisioning and live verification (DynamoDB + S3)** — concept_authoring_store, concept_dynamodb_authoring_table, concept_s3_artifacts_bucket, infra_aws_smoke_test_guide, infra_aws_readme [INFERRED 0.85]
- **Alternative deployment strategies for serving SAM 3D Objects reconstruction** — sam3d_hf_gpu_space_readme, sam3d_hf_zerogpu_space_readme, infra_aws_readme, concept_sam3d_objects [INFERRED 0.85]

## Communities (53 total, 10 thin omitted)

### Community 0 - "Project Persistence Layer"
Cohesion: 0.06
Nodes (28): ExperienceBlueprint, ProjectAsset, ProjectRecord, PublicationRecord, An immutable record of one blueprint publication. Publication history is…, AuthoringStore, create_store(), DynamoDbStore (+20 more)

### Community 1 - "Shared Room Feature & Agent Concepts"
Cohesion: 0.08
Nodes (58): connection-compose-endpoint skill, contributor-api-endpoints skill, contributor-data-model skill, demo-video-prep skill, gpu-cloud-activation skill, immersive-reveal-staging skill, meta-hardware-polish skill, meta-track-alignment skill (+50 more)

### Community 2 - "Pipeline Docs & Infra Concepts"
Cohesion: 0.09
Nodes (39): sketchscape-infrastructure skill, AuthoringStore (LocalJsonStore / DynamoDbStore), Camber GPU bootstrap (bootstrap_fastsam3d.sh), ConnectionInsight (AI-inferred shared theme), Contribution data model, Contributor data model, "The connection must be felt, not read" (diegetic staging over UI text), Dual-track submission strategy (Meta + Immersive AR/VR from one build) (+31 more)

### Community 3 - "Experience Blueprint Schema (Defs)"
Cohesion: 0.05
Nodes (46): minLength, type, $defs, portal, sceneObject, transform, vector3, minLength (+38 more)

### Community 4 - "Unity Scene Profile Schema"
Cohesion: 0.05
Nodes (43): items, type, additionalProperties, minLength, type, additionalProperties, properties, required (+35 more)

### Community 5 - "FastSAM3D Reconstruction Pipeline"
Cohesion: 0.07
Nodes (36): gc, hydra_utils, math, numpy, omegaconf, pil, sam3d_objects_pipeline_inference_pipeline, SAM3SemanticPredictor (+28 more)

### Community 6 - "Scene Schema (Legacy)"
Cohesion: 0.05
Nodes (40): items, type, uniqueItems, type, $defs, vector3, type, type (+32 more)

### Community 7 - "SAM3D ZeroGPU HF Space & AWS Smoke Test"
Cohesion: 0.11
Nodes (31): boto3, boto3_dynamodb_conditions, GPU, diagnostic_text(), ensure_checkpoints(), ensure_repo(), ensure_runtime(), get_inference() (+23 more)

### Community 8 - "Backend API Models"
Cohesion: 0.11
Nodes (27): AddAssetViewRequest, AssetStatus, BlueprintObject, create_project(), EnvironmentSettings, ExperienceSettings, get_interactives(), InteractiveObject (+19 more)

### Community 9 - "Worker Contract Schema"
Cohesion: 0.08
Nodes (23): allOf, description, type, type, description, type, type, type (+15 more)

### Community 10 - "Core Module Imports & Blender Export"
Cohesion: 0.13
Nodes (17): asyncio, Artifact storage for SketchScape reconstruction outputs. This module owns the…, Small contract checks; run with `python -m unittest test_api.py`., Storage-layer contract tests. These exercise the backend-selection factory and…, NemoClaw identify_subject labeling (Build Plan step 4a). Run with: python -m…, bpy, fastapi, fastapi_responses (+9 more)

### Community 11 - "Subject Labeling"
Cohesion: 0.13
Nodes (19): create_subject_labeler(), MockSubjectLabeler, NemoClawSubjectLabeler, ABC, Path, Subject labeling for uploaded photos (Build Plan step 4a). When a contributor…, Raised when a labeling backend is misconfigured or fails., NemoClaw's reading of which object an uploaded photo is about. (+11 more)

### Community 12 - "Asset Upload Endpoint"
Cohesion: 0.19
Nodes (21): add_asset_view(), AssetView, create_project_asset(), create_reconstruction(), image_extension(), job_url(), Path, UploadFile (+13 more)

### Community 13 - "DynamoDB & Storage Contract Tests"
Cohesion: 0.10
Nodes (9): DynamoDbStoreTests, _extract_pk_and_prefix(), _FakeTable, LocalJsonStoreContractTests, make_asset(), make_project(), A tiny in-memory stand-in for a boto3 DynamoDB Table. It supports only the…, Pull the pk value and sk prefix out of a boto3 And(condition) tree. (+1 more)

### Community 14 - "Artifact Store Core & Factory Tests"
Cohesion: 0.14
Nodes (10): ArtifactStore, create_artifact_store(), ABC, UploadFile, Build the configured artifact store. Selection order: - ``backend`` argument…, The persistence surface every artifact backend must implement., Write ``source`` and return the canonical artifact URL path. The returned value…, Copy an existing local file (e.g. the input image) into the store. Returns the… (+2 more)

### Community 15 - "Multi-View Provenance Tests"
Cohesion: 0.23
Nodes (8): MultiViewProvenanceTests, Verify per-view reconstruction provenance on catalog assets., Creating an asset via POST /assets must seed views[0] with correct metadata., POST /assets/{id}/views must append a view with view_index=1., Asset must become READY and artifact_url promoted once view 0 job completes., Worker callback must update the matching AssetView by job_id., A failed second view must not change asset status when view 0 is READY., A multi-view READY asset must compile into a blueprint correctly.

### Community 16 - "Local Artifact Store Tests"
Cohesion: 0.23
Nodes (6): LocalArtifactStoreTests, UploadFile, Construct a minimal UploadFile from in-memory bytes., Run a coroutine synchronously inside the test suite., _run(), _upload_file()

### Community 17 - "S3 Artifact Store & Tests"
Cohesion: 0.24
Nodes (5): S3-backed artifact store. Objects land at…, Buffer to a temp file then multipart-upload to S3., Redirect to a short-lived presigned GET URL., S3ArtifactStore, S3ArtifactStoreTests

### Community 18 - "Read Endpoints"
Cohesion: 0.20
Nodes (15): get_artifact(), get_blueprint(), get_compiled_project_scene(), get_project(), get_project_asset(), health_check(), list_asset_views(), list_project_assets() (+7 more)

### Community 19 - "Worker Job Server"
Cohesion: 0.16
Nodes (11): http_client, http_server, logging, mimetypes, queue, time, urllib_error, _job_worker_thread() (+3 more)

### Community 20 - "Worker Job Runner Script"
Cohesion: 0.20
Nodes (11): json, download(), export(), main(), Path, Export one published SketchScape project into the Unity authoring folder. This…, shlex, shutil (+3 more)

### Community 21 - "Blueprint Environment Schema"
Cohesion: 0.14
Nodes (14): type, additionalProperties, properties, required, type, type, minLength, type (+6 more)

### Community 22 - "Local Artifact Store Core"
Cohesion: 0.26
Nodes (4): LocalArtifactStore, Path, Canonical relative URL for any artifact, regardless of backend., Filesystem-backed artifact store under ``artifact_root``. Writes arrive as…

### Community 23 - "SAM3D GPU HF Space"
Cohesion: 0.21
Nodes (12): gradio, huggingface_hub, _binary_mask(), get_inference(), _pipeline_config(), ndarray, Path, Gradio front end for the official SAM 3D Objects inference pipeline. The model… (+4 more)

### Community 24 - "AWS Bootstrap Script"
Cohesion: 0.17
Nodes (12): DEBIAN_FRONTEND, FASTSAM3D_CHECKPOINT_DIR, FASTSAM3D_ENV_DIR, FASTSAM3D_PERSIST_ROOT, FASTSAM3D_REPO_DIR, HF_HOME, SAM31_ENV_DIR, SAM31_MODEL_DIR (+4 more)

### Community 25 - "Reconstruction Job Handling"
Cohesion: 0.23
Nodes (11): get_reconstruction(), datetime, Demo-safe fallback; it never pretends to have run SAM 3D., Submit a job to the persistent worker server on loopback. The worker server…, Private callback for the GPU worker; it is not a Unity endpoint., receive_worker_result(), ReconstructionJob, run_local_gpu_job() (+3 more)

### Community 26 - "Blueprint Experience Metadata Schema"
Cohesion: 0.17
Nodes (12): additionalProperties, properties, required, type, enum, experience, mode, theme (+4 more)

### Community 27 - "Reconstruction API Tests"
Cohesion: 0.18
Nodes (3): Republishing appends a record; it never rewrites earlier history., A fresh Store reading the same file must rehydrate authoring state., ReconstructionApiTests

### Community 28 - "Blueprint Objects & Portals Schema"
Cohesion: 0.20
Nodes (11): format, type, $ref, items, type, items, type, properties (+3 more)

### Community 29 - "Worker Job Runner (Core Logic)"
Cohesion: 0.27
Nodes (10): download(), generate_mask(), get_task(), main(), private_url(), Path, Run the pre-baked automatic segmentation command, if one was configured. It…, Post files without loading a potentially large splat PLY into memory. (+2 more)

### Community 30 - "Worker Server Job Execution"
Cohesion: 0.22
Nodes (8): _download_input(), Path, Ask the warm SAM 3.1 server for a mask; None means use the subprocess., Stream callbacks so a large PLY is never duplicated in host memory., _report(), _run_one_job(), _segment_via_server(), _segment_via_subprocess()

### Community 31 - "Scene Action Endpoints"
Cohesion: 0.24
Nodes (10): apply_scene_action(), bounded_vector(), get_scene(), modify_scene(), Apply an allowlisted, bounded transform action to one named object., Legacy phrase adapter; all mutations pass through the structured policy., A bounded action shared by Unity runtime and authoring/MCP tools., SceneActionRequest (+2 more)

### Community 32 - "Unity Scene Profile Instance"
Cohesion: 0.20
Nodes (9): acceptance_checks, $schema, profile_version, required_components, required_references, scene, checkpoint_label, save_before_changes (+1 more)

### Community 33 - "Worker Auth Endpoints"
Cohesion: 0.28
Nodes (9): alias, get_worker_input(), get_worker_task(), Reject public clients from marking a job complete. In local development no…, Private pull endpoint used by a Camber job; never call this from Unity., Return the worker-only text concept for local SAM 3.1 segmentation., worker_is_authorized(), FileResponse (+1 more)

### Community 35 - "Blueprint AR/VR Navigation Schema"
Cohesion: 0.22
Nodes (9): enum, additionalProperties, properties, required, type, ar, navigation, vr (+1 more)

### Community 36 - "Experience Blueprint Schema Root"
Cohesion: 0.25
Nodes (7): additionalProperties, description, $id, required, $schema, title, type

### Community 37 - "FastSAM3D Source Prep Script"
Cohesion: 0.33
Nodes (6): argparse, subprocess, main(), Path, Apply the three narrowly-scoped source fixes proven in the Kaggle run., replace_once()

### Community 38 - "Scene Compilation & Legacy Sketch"
Cohesion: 0.33
Nodes (7): compile_blueprint(), find_scene_object(), legacy_sketch(), placeholder_scene(), Compatibility endpoint retained while Unity migrates to reconstruction jobs., SceneDocument, SceneObject

### Community 39 - "Blueprint Publish Endpoints"
Cohesion: 0.60
Nodes (6): create_blueprint(), ExperienceBlueprintInput, publish_blueprint(), validate_blueprint(), validate_blueprint_assets(), post

### Community 44 - "AWS Preflight Check Script"
Cohesion: 1.00
Nodes (3): check(), fail(), aws_preflight.sh script

### Community 45 - "FastSAM3D Bootstrap Script"
Cohesion: 0.50
Nodes (3): MAX_JOBS, bootstrap_fastsam3d.sh script, TORCH_CUDA_ARCH_LIST

### Community 47 - "Blueprint Project ID Field"
Cohesion: 0.67
Nodes (3): minLength, type, project_id

### Community 48 - "Blueprint Revision Field"
Cohesion: 0.67
Nodes (3): revision, minimum, type

## Knowledge Gaps
- **156 isolated node(s):** `allOf`, `description`, `type`, `type`, `description` (+151 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 342 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MultiViewProvenanceTests` connect `Multi-View Provenance Tests` to `Core Module Imports & Blender Export`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `S3ArtifactStore` connect `S3 Artifact Store & Tests` to `Core Module Imports & Blender Export`, `Artifact Store Core & Factory Tests`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Why does `ArtifactStore` connect `Artifact Store Core & Factory Tests` to `Artifact Store Serve Endpoint`, `S3 Artifact Store & Tests`, `Core Module Imports & Blender Export`, `Local Artifact Store Core`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `DynamoDbStore` (e.g. with `ExperienceBlueprint` and `ProjectAsset`) actually correct?**
  _`DynamoDbStore` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `LocalJsonStore` (e.g. with `ExperienceBlueprint` and `ProjectAsset`) actually correct?**
  _`LocalJsonStore` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `create_reconstruction()` (e.g. with `run_local_gpu_job()` and `run_mock_job()`) actually correct?**
  _`create_reconstruction()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `allOf`, `description`, `type` to the rest of the system?**
  _156 weakly-connected nodes found - possible documentation gaps or missing edges._