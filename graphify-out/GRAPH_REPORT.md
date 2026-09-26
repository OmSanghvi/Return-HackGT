# Graph Report - HackGT  (2026-09-25)

## Corpus Check
- 78 files · ~63,790 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 6, .example 2, .ipynb 2)

## Summary
- 971 nodes · 1635 edges · 59 communities (49 shown, 10 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 45 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Blueprint Authoring Store
- HTTP Server Bootstrap
- Backend API Contract Tests
- SketchScape Agent Reference
- Scene Schema (Portal/Transform)
- JSON Schema Building Blocks
- Scene Schema Root
- Sketch Image-Gen Backends
- Backend Main API
- Reconstruction/Asset Creation
- DynamoDB Store Tests
- Worker Contract Schema
- Subject Labeler
- Immersive Reveal Staging
- Blueprint/Scene Read Endpoints
- AWS Smoke Test Script
- Connection Compose Endpoint
- Artifact Store Abstraction
- SAM3D HF Space App
- SketchScape Infrastructure Skill
- Multi-View Provenance Tests
- Local Artifact Store Tests
- Local Artifact Store Impl
- S3 Artifact Store
- Contributor/Contribution API
- Fast-SAM3D Inference Pipeline
- Instance Bootstrap Script
- GPU + Cloud Activation
- SAM 3.1 Semantic Predictor
- Experience Config Schema
- Demo Video / Meta Hardware Polish
- Reconstruction API Tests
- Sketch Endpoint Tests
- Scene Profile Acceptance Checks
- SAM 3.1 Local Segmentation
- Scene Ambience Schema
- Worker Pull/Callback Endpoints
- Experience Mode Schema
- Scene Portal Schema
- Scene Action Policy
- SAM3D Job Submission
- FastSAM3D Source Prep Script
- Centered Object Segmentation
- Legacy Sketch Compatibility
- Store Factory Tests
- Fake S3 Client
- Furniture World Export (Blender)
- SAM 3D Objects HF Deployments
- Scene Object Array Schema
- AWS Preflight Script
- Environment Schema
- FastSAM3D Bootstrap Script
- Artifact Upload
- Artifact Serve Response
- Project ID Schema
- Bundle Publish Script
- Mock Demo Start Script
- SAM 3.1 Local Bootstrap Script

## God Nodes (most connected - your core abstractions)
1. `AGENT.md — SketchScape Agent Reference` - 27 edges
2. `create_reconstruction()` - 23 edges
3. `LocalJsonStore` - 22 edges
4. `DynamoDbStore` - 22 edges
5. `Meta Track Alignment Skill` - 21 edges
6. `AuthoringStore` - 20 edges
7. `ProjectRecord` - 19 edges
8. `ProjectAsset` - 19 edges
9. `add_asset_view()` - 19 edges
10. `ExperienceBlueprint` - 18 edges

## Surprising Connections (you probably didn't know these)
- `GPU + Cloud Activation Skill` --semantically_similar_to--> `SketchScape Infrastructure Skill`  [INFERRED] [semantically similar]
  .claude/skills/gpu-cloud-activation/SKILL.md → .agents/skills/sketchscape-infrastructure/SKILL.md
- `guide.txt NemoClaw orchestration/agent layer` --semantically_similar_to--> `NemoClaw agent`  [INFERRED] [semantically similar]
  guide.txt → AGENT.md
- `guide.txt — Draw It, Step Inside It build guide` --semantically_similar_to--> `AGENT.md — SketchScape Agent Reference`  [INFERRED] [semantically similar]
  guide.txt → AGENT.md
- `run_s3_smoke()` --calls--> `create_artifact_store()`  [INFERRED]
  scripts/smoke_test_aws_storage.py → backend/artifact_store.py
- `run_dynamodb_smoke()` --calls--> `create_store()`  [INFERRED]
  scripts/smoke_test_aws_storage.py → backend/storage.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **SketchScape Build Plan Step Sequence** — _claude_skills_contributor_data_model_skill_contributor_data_model, _claude_skills_contributor_api_endpoints_skill_contributor_api_endpoints, _claude_skills_nemoclaw_agent_setup_skill_nemoclaw_agent_setup, _claude_skills_nemoclaw_scene_tools_skill_nemoclaw_scene_tools, _claude_skills_nemoclaw_subject_labeling_skill_nemoclaw_subject_labeling, _claude_skills_connection_compose_endpoint_skill_connection_compose_endpoint, _claude_skills_immersive_reveal_staging_skill_immersive_reveal_staging, _claude_skills_nemoclaw_environment_sourcing_skill_nemoclaw_environment_sourcing, _claude_skills_sketch_image_gen_backends_skill_sketch_image_gen_backends, _claude_skills_unity_diegetic_attribution_skill_unity_diegetic_attribution, _claude_skills_meta_hardware_polish_skill_meta_hardware_polish, _claude_skills_gpu_cloud_activation_skill_gpu_cloud_activation, _claude_skills_unity_offline_builder_and_rendering_skill_unity_offline_builder_and_rendering, _claude_skills_demo_video_prep_skill_demo_video_prep [EXTRACTED 1.00]
- **ConnectionInsight derived from a single NemoClaw reasoning pass** — _claude_skills_connection_compose_endpoint_skill_connection_compose_endpoint, _claude_skills_nemoclaw_scene_tools_skill_place_objects_in_scene, _claude_skills_contributor_data_model_skill_connectioninsight_model [EXTRACTED 1.00]
- **"Felt, not read" diegetic expression rule** — _claude_skills_immersive_reveal_staging_skill_immersive_reveal_staging, _claude_skills_unity_diegetic_attribution_skill_unity_diegetic_attribution, _claude_skills_meta_track_alignment_skill_meta_track_alignment [EXTRACTED 1.00]
- **NemoClaw's scene-composition tool suite** — agent_nemoclaw, agent_place_objects_in_scene, agent_read_sketch_layout, agent_stage_immersive_reveal, agent_trigger_unity_scene_update [EXTRACTED 1.00]
- **Shared Room N-ary social data layer** — agent_contributor_model, agent_contribution_model, agent_connection_insight, docs_architecture_n_contributor_scaling [INFERRED 0.85]
- **Parallel deployment paths for facebook/sam-3d-objects reconstruction** — sam3d_hf_gpu_space_readme_doc, sam3d_hf_zerogpu_space_readme_doc, worker_readme_doc [INFERRED 0.75]

## Communities (59 total, 10 thin omitted)

### Community 0 - "Blueprint Authoring Store"
Cohesion: 0.06
Nodes (29): ExperienceBlueprint, ProjectAsset, ProjectRecord, PublicationRecord, An immutable record of one blueprint publication. Publication history is…, AuthoringStore, create_store(), DynamoDbStore (+21 more)

### Community 1 - "HTTP Server Bootstrap"
Cohesion: 0.05
Nodes (44): BaseHTTPRequestHandler, http_client, http_server, json, logging, mimetypes, queue, re (+36 more)

### Community 2 - "Backend API Contract Tests"
Cohesion: 0.05
Nodes (26): Small contract checks; run with `python -m unittest test_api.py`., FactoryTests, _is_png(), MockBackendTests, Tests for the sketch → image generation pipeline. Covers: - Factory selection…, LabelerBackendTests, NemoClaw identify_subject labeling (Build Plan step 4a). Run with: python -m…, UploadLabelingTests (+18 more)

### Community 3 - "SketchScape Agent Reference"
Cohesion: 0.08
Nodes (30): ConnectionInsight model, Contribution model, Contributor model, AGENT.md — SketchScape Agent Reference, Grok as switchable fallback NemoClaw runtime, Hard rules — never break these, Immersive scene craft open-source toolkit, Llama-backed NemoClaw reasoning runtime (Meta track default) (+22 more)

### Community 4 - "Scene Schema (Portal/Transform)"
Cohesion: 0.05
Nodes (46): minLength, type, $defs, portal, sceneObject, transform, vector3, minLength (+38 more)

### Community 5 - "JSON Schema Building Blocks"
Cohesion: 0.05
Nodes (43): items, type, additionalProperties, minLength, type, additionalProperties, properties, required (+35 more)

### Community 6 - "Scene Schema Root"
Cohesion: 0.05
Nodes (40): items, type, uniqueItems, type, $defs, vector3, type, type (+32 more)

### Community 7 - "Sketch Image-Gen Backends"
Cohesion: 0.08
Nodes (26): Azure AI Foundry "Muse" (unrelated Xbox research model), AzureBackend, GrokBackend, HFBackend, Meta Muse Image (rejected), Sketch Image-Gen Backends Skill, AzureImageGenBackend, create_image_gen_backend() (+18 more)

### Community 8 - "Backend Main API"
Cohesion: 0.10
Nodes (34): AddAssetViewRequest, AssetStatus, AssetView, BlueprintObject, create_blueprint(), create_project(), EnvironmentSettings, ExperienceBlueprintInput (+26 more)

### Community 9 - "Reconstruction/Asset Creation"
Cohesion: 0.14
Nodes (28): add_asset_view(), create_project_asset(), create_reconstruction(), create_sketch_reconstruction(), get_reconstruction(), image_extension(), job_url(), Path (+20 more)

### Community 10 - "DynamoDB Store Tests"
Cohesion: 0.10
Nodes (12): asyncio, DynamoDbStoreTests, _extract_pk_and_prefix(), _FakeTable, LocalJsonStoreContractTests, make_asset(), make_project(), Storage-layer contract tests. These exercise the backend-selection factory and… (+4 more)

### Community 11 - "Worker Contract Schema"
Cohesion: 0.08
Nodes (23): allOf, description, type, type, description, type, type, type (+15 more)

### Community 12 - "Subject Labeler"
Cohesion: 0.15
Nodes (17): create_subject_labeler(), MockSubjectLabeler, NemoClawSubjectLabeler, ABC, Path, RuntimeError, Subject labeling for uploaded photos (Build Plan step 4a). When a contributor…, Raised when a labeling backend is misconfigured or fails. (+9 more)

### Community 13 - "Immersive Reveal Staging"
Cohesion: 0.12
Nodes (19): Immersive Reveal Staging Skill, Meta MMS TTS, PrimeTween, Resonance Audio, StagingPlan, TweenPlayables, URP Volumetric Lighting/Fog, VisualEffectGraph-Samples (+11 more)

### Community 14 - "Blueprint/Scene Read Endpoints"
Cohesion: 0.17
Nodes (19): compile_blueprint(), get_artifact(), get_blueprint(), get_compiled_project_scene(), get_project(), get_project_asset(), get_scene(), health_check() (+11 more)

### Community 15 - "AWS Smoke Test Script"
Cohesion: 0.23
Nodes (16): boto3, boto3_dynamodb_conditions, check(), cleanup_dynamodb(), cleanup_s3(), main(), _make_asset(), _make_blueprint() (+8 more)

### Community 16 - "Connection Compose Endpoint"
Cohesion: 0.15
Nodes (17): connection/compose Endpoint Skill, POST /v1/projects/{project_id}/connection/compose, ConnectionComposeResponse, ConnectionInsight model, stage_immersive_reveal tool, BlueprintObject, LayoutHint, NemoClaw Scene Tools Skill (+9 more)

### Community 17 - "Artifact Store Abstraction"
Cohesion: 0.15
Nodes (11): ArtifactStore, create_artifact_store(), ABC, Artifact storage for SketchScape reconstruction outputs. This module owns the…, Build the configured artifact store. Selection order: - ``backend`` argument…, The persistence surface every artifact backend must implement., Return True if the artifact is present in the store., ArtifactStoreFactoryTests (+3 more)

### Community 18 - "SAM3D HF Space App"
Cohesion: 0.17
Nodes (16): GPU, gradio, numpy, diagnostic_text(), ensure_checkpoints(), ensure_repo(), ensure_runtime(), get_inference() (+8 more)

### Community 19 - "SketchScape Infrastructure Skill"
Cohesion: 0.13
Nodes (15): docs/ARCHITECTURE.md, docs/INFRASTRUCTURE_ROADMAP.md, docs/INTEGRATION_GUIDE.md, PIPELINE_MODE=mock, SketchScape Infrastructure Skill, SketchScapeExperienceCompiler, Hermes Agent, LangChain Deep Agents (+7 more)

### Community 20 - "Multi-View Provenance Tests"
Cohesion: 0.23
Nodes (8): MultiViewProvenanceTests, Verify per-view reconstruction provenance on catalog assets., Creating an asset via POST /assets must seed views[0] with correct metadata., POST /assets/{id}/views must append a view with view_index=1., Asset must become READY and artifact_url promoted once view 0 job completes., Worker callback must update the matching AssetView by job_id., A failed second view must not change asset status when view 0 is READY., A multi-view READY asset must compile into a blueprint correctly.

### Community 21 - "Local Artifact Store Tests"
Cohesion: 0.23
Nodes (6): LocalArtifactStoreTests, UploadFile, Construct a minimal UploadFile from in-memory bytes., Run a coroutine synchronously inside the test suite., _run(), _upload_file()

### Community 22 - "Local Artifact Store Impl"
Cohesion: 0.21
Nodes (5): LocalArtifactStore, Path, Copy an existing local file (e.g. the input image) into the store. Returns the…, Canonical relative URL for any artifact, regardless of backend., Filesystem-backed artifact store under ``artifact_root``. Writes arrive as…

### Community 23 - "S3 Artifact Store"
Cohesion: 0.24
Nodes (5): S3-backed artifact store. Objects land at…, Buffer to a temp file then multipart-upload to S3., Redirect to a short-lived presigned GET URL., S3ArtifactStore, S3ArtifactStoreTests

### Community 24 - "Contributor/Contribution API"
Cohesion: 0.18
Nodes (13): POST/GET /v1/projects/{project_id}/contributions, Contributor API Endpoints Skill, POST/GET /v1/projects/{project_id}/contributors, MultiViewProvenanceTests, AuthoringStore, Contribution model, Contributor Data Model Skill, Contributor model (+5 more)

### Community 25 - "Fast-SAM3D Inference Pipeline"
Cohesion: 0.15
Nodes (9): hydra_utils, math, omegaconf, sam3d_objects_pipeline_inference_pipeline, torch, env_path(), main(), Path (+1 more)

### Community 26 - "Instance Bootstrap Script"
Cohesion: 0.17
Nodes (12): DEBIAN_FRONTEND, FASTSAM3D_CHECKPOINT_DIR, FASTSAM3D_ENV_DIR, FASTSAM3D_PERSIST_ROOT, FASTSAM3D_REPO_DIR, HF_HOME, SAM31_ENV_DIR, SAM31_MODEL_DIR (+4 more)

### Community 27 - "GPU + Cloud Activation"
Cohesion: 0.20
Nodes (12): Fast-SAM3D, SAM 3.1, DynamoDB/S3 cloud backend activation, GPU + Cloud Activation Skill, infra/aws/SMOKE_TEST_GUIDE.md, AGENT.md, find_object_image tool, NemoClaw Environment Sourcing Skill (+4 more)

### Community 28 - "SAM 3.1 Semantic Predictor"
Cohesion: 0.27
Nodes (11): SAM3SemanticPredictor, build_predictor(), main(), Path, Write one mask for ``prompt``; 0 on success, 2 when a human must review., Keep SAM 3.1 loaded between jobs. Loopback only; one request at a time., segment(), serve() (+3 more)

### Community 29 - "Experience Config Schema"
Cohesion: 0.17
Nodes (12): additionalProperties, properties, required, type, enum, experience, mode, theme (+4 more)

### Community 30 - "Demo Video / Meta Hardware Polish"
Cohesion: 0.22
Nodes (11): Demo Video Prep Skill, features.txt, docs/PROJECT_STATUS.md, Quest headset shown on a real head, Meta XR Interaction SDK Hand Tracking, Meta Hardware Polish Skill, Meta XR Building Blocks, Meta XR SDK Passthrough API (+3 more)

### Community 31 - "Reconstruction API Tests"
Cohesion: 0.18
Nodes (3): Republishing appends a record; it never rewrites earlier history., A fresh Store reading the same file must rehydrate authoring state., ReconstructionApiTests

### Community 33 - "Scene Profile Acceptance Checks"
Cohesion: 0.20
Nodes (9): acceptance_checks, $schema, profile_version, required_components, required_references, scene, checkpoint_label, save_before_changes (+1 more)

### Community 34 - "SAM 3.1 Local Segmentation"
Cohesion: 0.27
Nodes (9): gc, ultralytics_models_sam, candidate_masks(), choose_one(), ndarray, Turn a SAM 3.1 text-concept prediction into one Fast-SAM3D mask. SAM 3.1…, Normalize an Ultralytics mask to the original source dimensions., Pick one object near the photo centre, rejecting implausible masks. (+1 more)

### Community 35 - "Scene Ambience Schema"
Cohesion: 0.20
Nodes (10): type, properties, type, minLength, type, ambient_audio, floor, lighting_preset (+2 more)

### Community 36 - "Worker Pull/Callback Endpoints"
Cohesion: 0.28
Nodes (9): alias, get_worker_input(), get_worker_task(), Reject public clients from marking a job complete. In local development no…, Private pull endpoint used by a Camber job; never call this from Unity., Return the worker-only text concept for local SAM 3.1 segmentation., worker_is_authorized(), FileResponse (+1 more)

### Community 37 - "Experience Mode Schema"
Cohesion: 0.22
Nodes (9): enum, additionalProperties, properties, required, type, ar, navigation, vr (+1 more)

### Community 38 - "Scene Portal Schema"
Cohesion: 0.22
Nodes (9): format, type, type, properties, created_at, portals, revision, minimum (+1 more)

### Community 39 - "Scene Action Policy"
Cohesion: 0.29
Nodes (8): apply_scene_action(), bounded_vector(), modify_scene(), Apply an allowlisted, bounded transform action to one named object., Legacy phrase adapter; all mutations pass through the structured policy., A bounded action shared by Unity runtime and authoring/MCP tools., SceneActionRequest, SceneModificationRequest

### Community 40 - "SAM3D Job Submission"
Cohesion: 0.32
Nodes (7): datetime, Demo-safe fallback; it never pretends to have run SAM 3D., Submit a job to the persistent worker server on loopback. The worker server…, run_local_gpu_job(), run_mock_job(), sync_project_asset(), utc_now()

### Community 41 - "FastSAM3D Source Prep Script"
Cohesion: 0.33
Nodes (6): argparse, subprocess, main(), Path, Apply the three narrowly-scoped source fixes proven in the Kaggle run., replace_once()

### Community 42 - "Centered Object Segmentation"
Cohesion: 0.33
Nodes (6): pil, transformers, main(), normalized_mask(), ndarray, Create a conservative automatic mask for a single prominent centre object. Exit…

### Community 43 - "Legacy Sketch Compatibility"
Cohesion: 0.33
Nodes (6): find_scene_object(), legacy_sketch(), placeholder_scene(), Compatibility endpoint retained while Unity migrates to reconstruction jobs., SceneDocument, SceneObject

### Community 46 - "Furniture World Export (Blender)"
Cohesion: 0.40
Nodes (3): bpy, pathlib, Export a small curated living-room world from Furniture_FREE.blend. Run through…

### Community 48 - "Scene Object Array Schema"
Cohesion: 0.40
Nodes (5): $ref, items, type, items, objects

### Community 49 - "AWS Preflight Script"
Cohesion: 1.00
Nodes (3): check(), fail(), aws_preflight.sh script

### Community 50 - "Environment Schema"
Cohesion: 0.50
Nodes (4): additionalProperties, required, type, environment

### Community 51 - "FastSAM3D Bootstrap Script"
Cohesion: 0.50
Nodes (3): MAX_JOBS, bootstrap_fastsam3d.sh script, TORCH_CUDA_ARCH_LIST

### Community 54 - "Project ID Schema"
Cohesion: 0.67
Nodes (3): minLength, type, project_id

## Ambiguous Edges - Review These
- `Meta Muse Image (rejected)` → `Azure AI Foundry "Muse" (unrelated Xbox research model)`  [AMBIGUOUS]
  .claude/skills/sketch-image-gen-backends/SKILL.md · relation: conceptually_related_to

## Knowledge Gaps
- **187 isolated node(s):** `$schema`, `title`, `description`, `type`, `required` (+182 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 413 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Meta Muse Image (rejected)` and `Azure AI Foundry "Muse" (unrelated Xbox research model)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `connection/compose Endpoint Skill` connect `Connection Compose Endpoint` to `Contributor/Contribution API`, `Backend Main API`, `Immersive Reveal Staging`, `Demo Video / Meta Hardware Polish`?**
  _High betweenness centrality (0.153) - this node is a cross-community bridge._
- **Why does `NemoClaw Scene Tools Skill` connect `Connection Compose Endpoint` to `GPU + Cloud Activation`, `SketchScape Infrastructure Skill`, `Immersive Reveal Staging`, `Demo Video / Meta Hardware Polish`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `properties` connect `Scene Portal Schema` to `Experience Mode Schema`, `Connection Compose Endpoint`, `Scene Object Array Schema`, `Environment Schema`, `Project ID Schema`, `Experience Config Schema`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `AGENT.md — SketchScape Agent Reference` (e.g. with `guide.txt — Draw It, Step Inside It build guide` and `PIPELINE_PLAN.md`) actually correct?**
  _`AGENT.md — SketchScape Agent Reference` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `create_reconstruction()` (e.g. with `run_local_gpu_job()` and `run_mock_job()`) actually correct?**
  _`create_reconstruction()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `LocalJsonStore` (e.g. with `ExperienceBlueprint` and `ProjectAsset`) actually correct?**
  _`LocalJsonStore` has 4 INFERRED edges - model-reasoned connections that need verification._