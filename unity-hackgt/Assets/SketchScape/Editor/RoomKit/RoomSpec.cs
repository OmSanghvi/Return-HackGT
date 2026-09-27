// SketchScape RoomKit — room spec (docs/IMMERSIVE_SCENE_PIPELINE.md section 5).
// Canonical source: Return-HackGT/unity-hackgt/. Installed into HackGTUnity by
// scripts/install_hackgt_roomkit.py; edit the repo copy, not the installed one.
//
// JsonUtility-compatible: plain [Serializable] classes, field names equal the
// JSON keys, vectors are float arrays, no nulls/dictionaries/nested arrays.
// Every field has a default so a partial spec still builds.
using System;

namespace SketchScape
{
    [Serializable]
    public class RoomSpec
    {
        public int version = 1;
        public string slug = "";
        public string scene_path = "";
        public string root = "";
        public RoomPlayer player = new RoomPlayer();
        public RoomPhotoScene photo_scene = new RoomPhotoScene();
        public RoomObject[] objects = new RoomObject[0];
        public RoomEnvironment environment = new RoomEnvironment();
        public RoomLight[] lights = new RoomLight[0];
        public RoomImage[] images = new RoomImage[0];
        public RoomAudio[] audio = new RoomAudio[0];
        public RoomParticles[] particles = new RoomParticles[0];
        public RoomStaging staging = new RoomStaging();
        public RoomTeleport teleport = new RoomTeleport();
        public string[] credits = new string[0];
        public RoomShared shared = new RoomShared();
        public RoomPerformance performance = new RoomPerformance();
    }

    /// <summary>
    /// Quest readiness (RoomKit 1.0.16; docs/IMMERSIVE_SCENE_PIPELINE.md "Quest budgets"). A spec without
    /// this block gets these defaults, i.e. every room is Quest-ready and interactive unless it opts out.
    /// Build records the flags on the room (RoomBuildInfo) and Finalize follows them.
    /// </summary>
    [Serializable]
    public class RoomPerformance
    {
        /// <summary>"quest" | "desktop": which device the room is sized for (the build report warns
        /// when a "quest" room renders more splats than a Quest 2 keeps up with).</summary>
        public string target = "quest";
        /// <summary>Render the sync's Quest-sized copy (&lt;name&gt;_quest.ply next to the splat) when there is one;
        /// placement always comes from the full-resolution splat.</summary>
        public bool prefer_quest_lod = true;
        /// <summary>Finalize adds SketchScapePickup (desktop pick-up in the Editor) to every grabbable object.</summary>
        public bool pickups = true;
        /// <summary>Finalize adds QuestPerformance (foveated rendering) to the OVRCameraRig and makes Android's
        /// default quality level one without MSAA.</summary>
        public bool quest_performance = true;
        /// <summary>Finalize adds Meta's camera rig, interaction rig, near + distance grab on every grabbable
        /// object and a teleport hotspot at every hotspot marker (the meta_add_* MCP tools' own handlers).</summary>
        public bool meta_setup = true;
    }

    /// <summary>Shared layer (Return-HackGT docs/WEB_TO_QUEST_PIPELINE.md section 3): account switcher,
    /// personal notes, letters and object tags, read from the project's /v1/rooms/{p}/shared view.</summary>
    [Serializable]
    public class RoomShared
    {
        public bool enabled = false;
        public string project_id = "";
        public string api_base = "";
        public string[] accounts = new string[0];
        public string[] labels = new string[0];
        public string default_account = "";
        public string snapshot_resource = "";
    }

    [Serializable]
    public class RoomPlayer
    {
        public float eye_height = 1.6f;
        public float[] spawn = { 0f, 0f, 0f };
        public float yaw = 0f;
    }

    [Serializable]
    public class RoomPhotoScene
    {
        public bool enabled = false;
        public string splat_path = "";
        public float[] position = { 0f, 0f, 0f };
        public float[] rotation = { 0f, 0f, 0f, 1f };
        public float[] scale = { 1f, 1f, 1f };
    }

    [Serializable]
    public class RoomObject
    {
        public string id = "";
        public string label = "";
        public string asset_id = "";
        public string splat_path = "";
        public string mode = "upright";          // "transform" | "upright"
        public float[] position = { 0f, 0f, 0f };
        public float[] rotation = { 0f, 0f, 0f, 1f };
        public float[] scale = { 1f, 1f, 1f };
        public float size_m = 0.5f;
        public float[] tint = { 0.8f, 0.8f, 0.8f };
        public bool grabbable = true;             // Finalize gives it Meta near + distance grab (and a pickup)
        public RoomObjectLight light = new RoomObjectLight();
    }

    [Serializable]
    public class RoomObjectLight
    {
        public bool enabled = false;
        public string type = "point";
        public float[] color = { 1f, 0.9f, 0.75f };
        public float intensity = 1.5f;
        public float range = 4f;
        public float[] offset = { 0f, 0.5f, 0f };
    }

    [Serializable]
    public class RoomEnvironment
    {
        public string hdri_url = "";
        public float hdri_rotation = 0f;
        public float hdri_exposure = 1f;
        public float[] sky_tint = { 0.5f, 0.5f, 0.5f };
        public string ambient_mode = "skybox";   // "skybox" | "flat"
        public float[] ambient_color = { 0.4f, 0.4f, 0.4f };
        public float ambient_intensity = 1f;
        public RoomFog fog = new RoomFog();
        public RoomFloor floor = new RoomFloor();
        public RoomShell shell = new RoomShell();
    }

    [Serializable]
    public class RoomFog
    {
        public bool enabled = false;
        public float[] color = { 0.6f, 0.6f, 0.65f };
        public float density = 0.02f;
    }

    [Serializable]
    public class RoomFloor
    {
        public bool enabled = true;
        public float[] size = { 12f, 12f };
        public float height = 0f;
        public string texture_url = "";
        public float[] color = { 0.55f, 0.5f, 0.45f };
        public float tiling = 4f;
    }

    [Serializable]
    public class RoomShell
    {
        public bool enabled = false;
        public float[] center = { 0f, 1.5f, 0f };  // box centre (world)
        public float[] size = { 6f, 3f, 6f };
        public string wall_texture_url = "";
        public float[] wall_color = { 0.85f, 0.82f, 0.78f };
        public bool ceiling = true;
    }

    [Serializable]
    public class RoomLight
    {
        public string type = "directional";       // "directional" | "point" | "spot"
        public float[] color = { 1f, 0.96f, 0.9f };
        public float intensity = 1f;
        public float[] position = { 0f, 3f, 0f };
        public float[] rotation = { 0f, 0f, 0f, 1f };
        public float range = 5f;
        public float spot_angle = 60f;
        public string shadows = "none";           // "soft" | "hard" | "none"
        public string name = "";
    }

    [Serializable]
    public class RoomImage
    {
        public string url = "";
        public string title = "";
        public string attribution = "";
        public float[] position = { 0f, 1.5f, 2f };
        public float[] rotation = { 0f, 0f, 0f, 1f };  // identity: picture faces -Z (a viewer looking +Z sees it)
        public float width = 0.8f;
        public bool frame = true;
        public float[] frame_color = { 0.12f, 0.1f, 0.08f };
        public bool lit = true;
    }

    [Serializable]
    public class RoomAudio
    {
        public string url = "";
        public string title = "";
        public string attribution = "";
        public float[] position = { 0f, 1f, 0f };
        public bool spatial = true;
        public float volume = 0.6f;
        public bool loop = true;
        public float min_distance = 1f;
        public float max_distance = 12f;
    }

    [Serializable]
    public class RoomParticles
    {
        public string kind = "dust";              // dust | fireflies | snow | rain | embers
        public float[] position = { 0f, 1.5f, 0f };
        public float[] size = { 6f, 3f, 6f };
        public float[] color = { 1f, 1f, 1f };
        public float rate = 20f;
    }

    [Serializable]
    public class RoomStaging
    {
        public bool enabled = false;
        public float[] mood_color = { 1f, 0.75f, 0.5f };
        public float[] glow_position = { 0f, 1.2f, 1.5f };
        public float[] motif_xz = new float[0];
        public string[] reveal_order = new string[0];
        public float reveal_seconds = 1.2f;
        public string narration = "";
        public string narration_audio_url = "";
    }

    [Serializable]
    public class RoomTeleport
    {
        public bool floor_collider = true;
        public float[] hotspots = new float[0];   // x0,y0,z0, x1,y1,z1, ...
    }
}
