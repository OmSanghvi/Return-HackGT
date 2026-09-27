// SketchScape RoomKit — builds an immersive Quest room from a room spec.
// Contract: docs/IMMERSIVE_SCENE_PIPELINE.md section 5 (Return-HackGT repo).
// Canonical source: Return-HackGT/unity-hackgt/. Installed into HackGTUnity by
// scripts/install_hackgt_roomkit.py; edit the repo copy, not the installed one.
//
// Public API (call through reflection from Unity_RunCommand):
//   string SketchScape.RoomKit.Build(string json)
//   string SketchScape.RoomKit.Finalize(string slug, float spawnX, float spawnZ, float yaw)
//   type name: "SketchScape.RoomKit, Assembly-CSharp-Editor"
// Both return a short plain-text report (< 2 KB) and never throw.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace SketchScape
{
    public static class RoomKit
    {
        public const string AgentRoomsFolder = "Assets/SketchScape/AgentRooms";
        /// <summary>Bumped on every RoomKit change; check it to know the installed kit is current.</summary>
        public static string Version() { return "1.0.14"; }
        const int MaxReport = 1900;

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        public static string Build(string json)
        {
            var failures = new List<string>();
            var notes = new List<string>();
            RoomSpec spec;
            try
            {
                spec = JsonUtility.FromJson<RoomSpec>(json);
            }
            catch (Exception e)
            {
                return "ERROR: room spec is not valid JSON for RoomKit: " + RoomKitWeb.Short(e.Message);
            }
            if (spec == null) return "ERROR: empty room spec.";
            Normalize(spec);

            string slugError = CheckSlug(spec.slug);
            if (slugError != null) return "ERROR: " + slugError;
            if (string.IsNullOrEmpty(spec.scene_path)) spec.scene_path = AgentRoomsFolder + "/" + spec.slug + ".unity";
            if (!spec.scene_path.StartsWith(AgentRoomsFolder + "/") || !spec.scene_path.EndsWith(".unity") || spec.scene_path.Contains(".."))
                return "ERROR: scene_path must be " + AgentRoomsFolder + "/<name>.unity (got '" + spec.scene_path + "').";
            if (string.IsNullOrEmpty(spec.root)) spec.root = "SharedRoom_" + spec.slug;

            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                var open = SceneManager.GetSceneAt(i);
                if (open.isDirty && !open.path.StartsWith(AgentRoomsFolder + "/"))
                    return "ERROR: scene '" + (open.path.Length > 0 ? open.path : open.name) + "' has unsaved changes. Save or discard them in the Unity Editor, then rerun. Nothing was changed.";
            }

            try
            {
                return BuildInner(spec, failures, notes);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                return Clip("ERROR: build of " + spec.slug + " failed: " + e.GetType().Name + ": " + RoomKitWeb.Short(e.Message) +
                            (failures.Count > 0 ? " | earlier failures: " + string.Join("; ", failures) : ""));
            }
        }

        static string BuildInner(RoomSpec spec, List<string> failures, List<string> notes)
        {
            RoomKitWeb.EnsureFolder(AgentRoomsFolder);
            string genFolder = AgentRoomsFolder + "/" + spec.slug + "_Generated";
            RoomKitWeb.EnsureFolder(genFolder);

            // 1. Download every URL once.
            var urls = new List<string>();
            var env = spec.environment;
            urls.Add(env.hdri_url);
            urls.Add(env.floor.texture_url);
            if (env.shell.enabled) urls.Add(env.shell.wall_texture_url);
            foreach (var im in spec.images) urls.Add(im.url);
            foreach (var au in spec.audio) urls.Add(au.url);
            if (spec.staging.enabled) urls.Add(spec.staging.narration_audio_url);
            var media = RoomKitWeb.FetchAll(urls, failures);

            // 2. Fresh scene.
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var root = new GameObject(spec.root);
            var director = root.AddComponent<RoomDirector>();
            var fadeLights = new List<Light>();
            var fadeAudio = new List<AudioSource>();

            // 3. Sky, ambient, fog.
            string skyNote = BuildSky(spec, media, genFolder, failures);
            if (env.fog.enabled)
            {
                RenderSettings.fog = true;
                RenderSettings.fogMode = FogMode.Exponential;
                RenderSettings.fogColor = Col(env.fog.color);
                RenderSettings.fogDensity = Mathf.Clamp(env.fog.density, 0f, 0.3f);
            }
            else RenderSettings.fog = false;

            // 4. Floor, teleport floor, shell.
            var envGroup = Group(root, "Environment");
            BuildFloor(spec, media, genFolder, envGroup, failures);
            if (env.shell.enabled) BuildShell(spec, media, genFolder, envGroup, failures);

            // 5. Lights.
            var lightGroup = Group(root, "Lighting");
            int lightCount = 0;
            if (spec.lights.Length == 0)
            {
                var key = NewLight(lightGroup, "Key Light", LightType.Directional, new Color(1f, 0.95f, 0.88f), 1.0f);
                key.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
                key.shadows = LightShadows.Soft;
                key.shadowStrength = 0.7f;
                fadeLights.Add(key);
                lightCount++;
                notes.Add("default key light");
            }
            bool keyShadowTaken = false;
            foreach (var l in spec.lights)
            {
                var type = ParseLightType(l.type);
                string name = string.IsNullOrEmpty(l.name) ? (type + " Light " + (lightCount + 1)) : l.name;
                var light = NewLight(lightGroup, name, type, Col(l.color), l.intensity);
                light.transform.position = V3(l.position);
                light.transform.rotation = Q(l.rotation);
                light.range = Mathf.Max(0.1f, l.range);
                if (type == LightType.Spot) light.spotAngle = Mathf.Clamp(l.spot_angle, 1f, 179f);
                light.shadows = ParseShadows(l.shadows);
                if (light.shadows != LightShadows.None)
                {
                    light.shadowStrength = 0.75f;
                    light.shadowBias = 0.03f;
                    keyShadowTaken = true;
                }
                fadeLights.Add(light);
                lightCount++;
            }
            if (!keyShadowTaken)
                foreach (var l in fadeLights)
                    if (l.type == LightType.Directional)
                    {
                        // The key light always casts soft shadows (objects must look grounded).
                        l.shadows = LightShadows.Soft;
                        l.shadowStrength = 0.7f;
                        l.shadowBias = 0.03f;
                        if (spec.lights.Length > 0) notes.Add("soft shadows on key '" + l.name + "'");
                        break;
                    }

            // 6. Photo scene splat: transform applied exactly, no collider.
            string photoNote = "off";
            if (spec.photo_scene.enabled)
            {
                var ps = spec.photo_scene;
                var go = new GameObject("Photo Scene");
                go.transform.SetParent(root.transform, false);
                go.transform.localPosition = V3(ps.position);
                go.transform.localRotation = Q(ps.rotation);
                go.transform.localScale = V3(ps.scale, 1f);
                string err;
                var photoAsset = AttachSplat(go, ps.splat_path, out err);
                if (photoAsset == null)
                {
                    failures.Add("photo scene: " + err);
                    photoNote = "missing";
                }
                else
                {
                    photoNote = "ok";
                    // A floor-standing photo scene is never fully opaque at its floor, so the room
                    // floor shows through: tint the room floor to the photo's own floor colour.
                    Color pf;
                    if (PhotoFloorColor(go, photoAsset, 0f, out pf))
                    {
                        if (env.floor.enabled && s_floorMats.Count > 0)
                        {
                            var tint = FloorTint(pf, s_floorTexMean);
                            foreach (var fm in s_floorMats) fm.color = tint;
                            notes.Add("floor tinted to the photo floor");
                        }
                    }
                    else
                    {
                        // No floor in the photo: a close-up of a raised surface (sofa seat, table top).
                        // Stand it on a plinth so it doesn't float above the room floor.
                        string plinthNote = BuildPlinth(envGroup, go, photoAsset, env.floor.height, genFolder);
                        if (plinthNote != null) notes.Add(plinthNote);
                    }
                }
            }

            // 7. Objects.
            var objectNotes = new List<string>();
            var byId = new Dictionary<string, Transform>();
            foreach (var o in spec.objects)
            {
                string id = string.IsNullOrEmpty(o.id) ? (string.IsNullOrEmpty(o.label) ? "object" : o.label) : o.id;
                id = UniqueName(id, byId);
                string kind;
                var obj = BuildObject(root.transform, o, id, genFolder, failures, out kind);
                byId[id] = obj.transform;
                if (o.light.enabled)
                {
                    var ol = NewLight(obj.transform, "Light", ParseLightType(o.light.type), Col(o.light.color), o.light.intensity);
                    ol.transform.position = obj.transform.position + V3(o.light.offset);
                    ol.range = Mathf.Max(0.1f, o.light.range);
                    fadeLights.Add(ol);
                }
                if (kind.StartsWith("splat")) AddContactShadow(obj, env.floor.height, genFolder);
                objectNotes.Add(id + "(" + kind + ")");
            }

            // 8. Framed images.
            int imagesOk = 0;
            if (spec.images.Length > 0)
            {
                var imageGroup = Group(root, "Images");
                for (int i = 0; i < spec.images.Length; i++)
                {
                    var im = spec.images[i];
                    string path;
                    Texture2D tex = null;
                    if (!string.IsNullOrEmpty(im.url) && media.TryGetValue(im.url.Trim(), out path))
                        tex = ImportTexture(path, false, 2048, TextureWrapMode.Clamp, failures);
                    if (tex == null) { failures.Add("image " + (i + 1) + " skipped (no texture)"); continue; }
                    var lit = BuildImage(imageGroup, im, tex, i, genFolder);
                    if (lit != null) fadeLights.Add(lit);
                    imagesOk++;
                }
            }

            // 9. Audio.
            int audioOk = 0;
            if (spec.audio.Length > 0)
            {
                var audioGroup = Group(root, "Audio");
                for (int i = 0; i < spec.audio.Length; i++)
                {
                    var au = spec.audio[i];
                    string path;
                    AudioClip clip = null;
                    if (!string.IsNullOrEmpty(au.url) && media.TryGetValue(au.url.Trim(), out path))
                        clip = ImportClip(path, au.spatial, failures);
                    if (clip == null) { failures.Add("audio " + (i + 1) + " skipped (no clip)"); continue; }
                    var go = new GameObject("Audio - " + Label(au.title, "ambience " + (i + 1)));
                    go.transform.SetParent(audioGroup, false);
                    go.transform.position = V3(au.position);
                    var src = go.AddComponent<AudioSource>();
                    src.clip = clip;
                    src.loop = au.loop;
                    src.playOnAwake = true;
                    src.volume = Mathf.Clamp01(au.volume);
                    src.spatialBlend = au.spatial ? 1f : 0f;
                    src.rolloffMode = AudioRolloffMode.Logarithmic;
                    src.minDistance = Mathf.Max(0.1f, au.min_distance);
                    src.maxDistance = Mathf.Max(src.minDistance + 0.1f, au.max_distance);
                    src.dopplerLevel = 0f;
                    src.spread = au.spatial ? 60f : 0f;
                    fadeAudio.Add(src);
                    audioOk++;
                }
            }

            // 10. Particles.
            if (spec.particles.Length > 0)
            {
                var pGroup = Group(root, "Particles");
                for (int pi = 0; pi < spec.particles.Length; pi++) BuildParticles(pGroup, spec.particles[pi], genFolder, pi);
            }

            // 11. Reflection probe (baked below).
            var probeGo = new GameObject("Reflection Probe");
            probeGo.transform.SetParent(envGroup, false);
            var fs = env.floor.size;
            probeGo.transform.position = new Vector3(0f, env.floor.height + 1.5f, 0f);
            var probe = probeGo.AddComponent<ReflectionProbe>();
            probe.mode = ReflectionProbeMode.Baked;
            probe.size = new Vector3(Mathf.Max(4f, fs[0]), 4f, Mathf.Max(4f, fs[1]));
            probe.boxProjection = env.shell.enabled;
            probe.resolution = 128;
            probe.hdr = true;

            // 12. Staging.
            if (spec.staging.enabled)
            {
                var st = spec.staging;
                var stageGroup = Group(root, "Staging");
                var mood = Col(st.mood_color);
                var glow = NewLight(stageGroup, "Connection Glow", LightType.Point, mood, 1.4f);
                glow.transform.position = V3(st.glow_position);
                glow.range = 4.5f;
                director.glow = glow;
                director.moodColor = mood;
                if (st.motif_xz != null && st.motif_xz.Length >= 4)
                    director.motif = BuildMotif(stageGroup, st.motif_xz, env.floor.height, mood, genFolder);
                director.revealSeconds = Mathf.Clamp(st.reveal_seconds, 0.2f, 6f);
                director.narrationText = st.narration ?? "";
                string np;
                if (!string.IsNullOrEmpty(st.narration_audio_url) && media.TryGetValue(st.narration_audio_url.Trim(), out np))
                {
                    var clip = ImportClip(np, false, failures);
                    if (clip != null)
                    {
                        var nGo = new GameObject("Narration");
                        nGo.transform.SetParent(stageGroup, false);
                        var src = nGo.AddComponent<AudioSource>();
                        src.clip = clip;
                        src.playOnAwake = false;
                        src.loop = false;
                        src.spatialBlend = 0f;
                        src.volume = 1f;
                        director.narration = src;
                    }
                }
            }
            var order = new List<Transform>();
            if (spec.staging.reveal_order != null)
                foreach (var id in spec.staging.reveal_order)
                {
                    Transform t;
                    if (id != null && byId.TryGetValue(id, out t) && !order.Contains(t)) order.Add(t);
                    else if (id != null) failures.Add("reveal_order: no object '" + id + "'");
                }
            if (spec.staging.enabled && order.Count == 0)
                foreach (var t in byId.Values) order.Add(t);
            director.revealTargets = order.ToArray();
            director.fadeLights = fadeLights.ToArray();
            director.fadeAudio = fadeAudio.ToArray();

            // 13. Teleport hotspots (markers; the agent also runs meta_add_teleport_hotspot).
            int hotspots = 0;
            var hs = spec.teleport.hotspots;
            if (hs != null && hs.Length >= 3)
            {
                var hGroup = Group(root, "TeleportHotspots");
                for (int i = 0; i + 2 < hs.Length; i += 3)
                {
                    var m = new GameObject("TeleportHotspot_" + (hotspots + 1));
                    m.transform.SetParent(hGroup, false);
                    m.transform.position = new Vector3(hs[i], hs[i + 1], hs[i + 2]);
                    hotspots++;
                }
            }

            // 14. Credits.
            string creditsPath = WriteCredits(spec);

            // 15. Save, bake environment lighting + reflection probe, save again.
            EditorSceneManager.MarkSceneDirty(scene);
            if (!EditorSceneManager.SaveScene(scene, spec.scene_path))
                return Clip("ERROR: could not save " + spec.scene_path + ". " + string.Join("; ", failures));
            string bakeNote = Bake(genFolder, failures);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, spec.scene_path);
            FrameSceneView(V3(spec.player.spawn), spec.player.yaw, spec.player.eye_height, root);

            var sb = new StringBuilder();
            sb.Append("OK built ").Append(spec.scene_path).Append(" root=").Append(spec.root).Append('\n');
            sb.Append("objects ").Append(spec.objects.Length).Append(": ").Append(string.Join(", ", objectNotes)).Append('\n');
            sb.Append("photo_scene=").Append(photoNote).Append(" sky=").Append(skyNote)
              .Append(" lights=").Append(lightCount).Append(" images=").Append(imagesOk).Append('/').Append(spec.images.Length)
              .Append(" audio=").Append(audioOk).Append('/').Append(spec.audio.Length)
              .Append(" particles=").Append(spec.particles.Length)
              .Append(" hotspots=").Append(hotspots)
              .Append(" staging=").Append(spec.staging.enabled ? "on(reveal " + order.Count + ")" : "off")
              .Append(" lighting=").Append(bakeNote).Append('\n');
            if (creditsPath != null) sb.Append("credits: ").Append(creditsPath).Append('\n');
            if (notes.Count > 0) sb.Append("notes: ").Append(string.Join("; ", notes)).Append('\n');
            sb.Append(failures.Count == 0 ? "failures: none" : "failures: " + string.Join("; ", failures));
            sb.Append("\nnext: meta_add_camerarig, meta_add_interactionrig, meta_add_grabbable per object id, meta_add_teleport_hotspot, then RoomKit.Finalize.");
            return Clip(sb.ToString());
        }

        // ------------------------------------------------------------------
        // Finalize
        // ------------------------------------------------------------------

        public static string Finalize(string slug, float spawnX, float spawnZ, float yaw)
        {
            try
            {
                string slugError = CheckSlug(slug);
                if (slugError != null) return "ERROR: " + slugError;
                var scene = SceneManager.GetActiveScene();
                if (!scene.path.StartsWith(AgentRoomsFolder + "/"))
                    return "ERROR: active scene is '" + scene.path + "', not an AgentRooms room. Run RoomKit.Build first.";

                string rootName = "SharedRoom_" + slug;
                GameObject root = null;
                Component rig = null;
                int hotspots = 0, markers = 0;
                foreach (var go in scene.GetRootGameObjects())
                {
                    if (go.name == rootName || (root == null && go.GetComponent<RoomDirector>() != null)) root = go;
                    foreach (var c in go.GetComponentsInChildren<Component>(true))
                    {
                        if (c == null) continue;
                        var tn = c.GetType().Name;
                        if (tn == "OVRCameraRig" && rig == null) rig = c;
                        if (tn == "TeleportInteractable") hotspots++;
                        if (c is Transform && c.name.StartsWith("TeleportHotspot_")) markers++;
                    }
                }
                if (root == null) return "ERROR: room root " + rootName + " is missing from " + scene.path + ". Rerun RoomKit.Build.";

                string rigNote = "MISSING (run meta_add_camerarig)";
                if (rig != null)
                {
                    var rt = rig.transform;
                    rt.position = new Vector3(spawnX, 0f, spawnZ);
                    rt.rotation = Quaternion.Euler(0f, yaw, 0f);
                    EditorUtility.SetDirty(rt);
                    string origin = SetFloorLevel(rig.gameObject);
                    rigNote = rig.gameObject.name + " at (" + spawnX.ToString("0.##") + ", 0, " + spawnZ.ToString("0.##") + ") yaw " + yaw.ToString("0") + ", " + origin;
                }

                var lines = new List<string>();
                foreach (Transform child in root.transform)
                {
                    if (child.GetComponent<BoxCollider>() == null) continue;
                    var kinds = new List<string>();
                    foreach (var c in child.GetComponentsInChildren<Component>(true))
                    {
                        if (c == null) continue;
                        var tn = c.GetType().Name;
                        if ((tn == "Grabbable" || tn == "DistanceGrabInteractable" || tn == "HandGrabInteractable" || tn == "GrabInteractable" || tn == "Rigidbody") && !kinds.Contains(tn))
                            kinds.Add(tn);
                    }
                    lines.Add(child.name + (kinds.Count > 0 ? " [" + string.Join(",", kinds) + "]" : " [not grabbable]"));
                }
                EditorSceneManager.MarkSceneDirty(scene);
                EditorSceneManager.SaveScene(scene);
                SaveAgainIfDirtied(scene.path);
                FrameSceneView(new Vector3(spawnX, 0f, spawnZ), yaw, 1.6f, root);
                return Clip("OK saved " + scene.path + ". camera rig: " + rigNote + ". teleport hotspots: " + hotspots +
                            " (markers " + markers + "). objects: " + (lines.Count > 0 ? string.Join("; ", lines) : "none"));
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                return "ERROR: finalize failed: " + e.GetType().Name + ": " + RoomKitWeb.Short(e.Message);
            }
        }

        /// <summary>
        /// The Meta XR rig / interaction components finish initialising on later editor ticks and
        /// re-dirty the scene after Finalize has saved it. Keep saving that scene for ~3 s so the
        /// room is left with no unsaved changes.
        /// </summary>
        static void SaveAgainIfDirtied(string path)
        {
            double until = EditorApplication.timeSinceStartup + 3.0;
            EditorApplication.CallbackFunction tick = null;
            tick = () =>
            {
                if (EditorApplication.timeSinceStartup > until || EditorApplication.isPlayingOrWillChangePlaymode)
                {
                    EditorApplication.update -= tick;
                    return;
                }
                var active = SceneManager.GetActiveScene();
                if (active.path != path) { EditorApplication.update -= tick; return; }
                if (active.isDirty) EditorSceneManager.SaveScene(active);
            };
            EditorApplication.update += tick;
        }

        static string SetFloorLevel(GameObject rigGo)
        {
            Component manager = null;
            foreach (var c in rigGo.GetComponentsInChildren<Component>(true))
                if (c != null && c.GetType().Name == "OVRManager") { manager = c; break; }
            if (manager == null)
                foreach (var c in UnityEngine.Object.FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include))
                    if (c != null && c.GetType().Name == "OVRManager") { manager = c; break; }
            if (manager == null) return "no OVRManager";
            var so = new SerializedObject(manager);
            var prop = so.FindProperty("_trackingOriginType");
            if (prop == null) return "tracking origin unknown";
            int floor = Array.IndexOf(prop.enumNames, "FloorLevel");
            if (floor < 0) return "tracking origin unknown";
            if (prop.enumValueIndex != floor)
            {
                prop.enumValueIndex = floor;
                so.ApplyModifiedPropertiesWithoutUndo();
                return "tracking origin set to FloorLevel";
            }
            return "tracking origin FloorLevel";
        }

        // ------------------------------------------------------------------
        // Sky / lighting
        // ------------------------------------------------------------------

        static string BuildSky(RoomSpec spec, Dictionary<string, string> media, string genFolder, List<string> failures)
        {
            var env = spec.environment;
            Material sky = null;
            string note;
            string hdrPath;
            if (!string.IsNullOrEmpty(env.hdri_url) && media.TryGetValue(env.hdri_url.Trim(), out hdrPath))
            {
                var tex = ImportTexture(hdrPath, true, 4096, TextureWrapMode.Repeat, failures);
                var shader = Shader.Find("Skybox/Panoramic");
                if (tex != null && shader != null)
                {
                    sky = new Material(shader);
                    sky.SetTexture("_MainTex", tex);
                    sky.SetFloat("_Mapping", 1f);      // latitude-longitude
                    sky.SetFloat("_ImageType", 0f);    // 360
                    sky.SetFloat("_MirrorOnBack", 0f);
                    sky.SetFloat("_Layout", 0f);
                    sky.SetFloat("_Rotation", Mathf.Repeat(env.hdri_rotation, 360f));
                    sky.SetFloat("_Exposure", Mathf.Clamp(env.hdri_exposure, 0.05f, 8f));
                    sky.SetColor("_Tint", new Color(0.5f, 0.5f, 0.5f, 1f));
                    sky.EnableKeyword("_MAPPING_LATITUDE_LONGITUDE_LAYOUT");
                    note = "hdri";
                }
                else note = "hdri-failed";
            }
            else note = string.IsNullOrEmpty(env.hdri_url) ? "procedural" : "hdri-failed";

            if (sky == null)
            {
                sky = new Material(Shader.Find("Skybox/Procedural"));
                var tint = Col(env.sky_tint);
                sky.SetColor("_SkyTint", tint);
                sky.SetColor("_GroundColor", Color.Lerp(new Color(0.37f, 0.35f, 0.34f), tint, 0.25f));
                sky.SetFloat("_AtmosphereThickness", 1.0f);
                sky.SetFloat("_Exposure", Mathf.Clamp(env.hdri_exposure, 0.3f, 3f) * 1.2f);
                sky.SetFloat("_SunSize", 0.03f);
                if (note == "hdri-failed") note = "procedural(hdri-failed)";
            }
            RenderSettings.skybox = sky;
            if (note == "hdri")
            {
                // Auto-exposure: HDRIs range from dim interiors to noon sun and this project renders
                // in Gamma space without tonemapping, so normalise the sky to a comfortable mean
                // brightness first; hdri_exposure is then a multiplier on top (1 = normalised).
                float e = AutoExposure(sky);
                sky.SetFloat("_Exposure", Mathf.Clamp(e * Mathf.Clamp(env.hdri_exposure, 0.05f, 8f), 0.02f, 16f));
                note = "hdri(exposure " + sky.GetFloat("_Exposure").ToString("0.00") + ")";
            }
            AssetDatabase.CreateAsset(sky, genFolder + "/Sky.mat");
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
            RenderSettings.defaultReflectionResolution = 128;

            if (env.ambient_mode == "flat")
            {
                RenderSettings.ambientMode = AmbientMode.Flat;
                RenderSettings.ambientLight = Col(env.ambient_color) * Mathf.Max(0f, env.ambient_intensity);
            }
            else
            {
                RenderSettings.ambientMode = AmbientMode.Skybox;
                RenderSettings.ambientIntensity = Mathf.Clamp(env.ambient_intensity, 0f, 8f);
            }
            RenderSettings.reflectionIntensity = 1f;
            // Directional key light doubles as the "sun" of a procedural sky.
            DynamicGI.UpdateEnvironment();
            return note;
        }

        public const float TargetSkyLuminance = 0.3f;

        static float AutoExposure(Material sky)
        {
            RenderSettings.ambientMode = AmbientMode.Skybox;
            RenderSettings.ambientIntensity = 1f;
            float e = 1f;
            for (int i = 0; i < 5; i++)
            {
                sky.SetFloat("_Exposure", e);
                DynamicGI.UpdateEnvironment();
                float m = MeanAmbientLuminance();
                if (m < 1e-4f || float.IsNaN(m)) break;
                // The response is steeper than linear in Gamma space; damp the step.
                float f = Mathf.Pow(TargetSkyLuminance / m, 0.6f);
                e = Mathf.Clamp(e * f, 0.03f, 8f);
                if (Mathf.Abs(f - 1f) < 0.04f) break;
            }
            return e;
        }

        static readonly Vector3[] s_probeDirs =
        {
            Vector3.up, Vector3.down, Vector3.left, Vector3.right, Vector3.forward, Vector3.back
        };

        static float MeanAmbientLuminance()
        {
            var cols = new Color[s_probeDirs.Length];
            RenderSettings.ambientProbe.Evaluate(s_probeDirs, cols);
            float sum = 0f;
            foreach (var c in cols) sum += 0.2126f * c.r + 0.7152f * c.g + 0.0722f * c.b;
            return sum / cols.Length;
        }

        static string Bake(string genFolder, List<string> failures)
        {
            try
            {
                var settings = new LightingSettings
                {
                    bakedGI = false,
                    realtimeGI = false,
                };
                AssetDatabase.CreateAsset(settings, genFolder + "/Lighting.lighting");
                Lightmapping.lightingSettings = settings;
                bool ok = Lightmapping.Bake();
                DynamicGI.UpdateEnvironment();
                if (!ok) { failures.Add("lighting bake did not complete"); return "unbaked"; }
                return "baked";
            }
            catch (Exception e)
            {
                failures.Add("lighting bake: " + RoomKitWeb.Short(e.Message));
                return "unbaked";
            }
        }

        // ------------------------------------------------------------------
        // Floor / shell
        // ------------------------------------------------------------------

        static void BuildFloor(RoomSpec spec, Dictionary<string, string> media, string genFolder, Transform parent, List<string> failures)
        {
            var f = spec.environment.floor;
            s_floorMats.Clear();
            s_floorTexMean = Color.white;
            float sx = Mathf.Max(0.5f, f.size.Length > 0 ? f.size[0] : 12f);
            float sz = Mathf.Max(0.5f, f.size.Length > 1 ? f.size[1] : sx);
            if (f.enabled)
            {
                Texture2D tex = null;
                string path = null;
                if (!string.IsNullOrEmpty(f.texture_url) && media.TryGetValue(f.texture_url.Trim(), out path))
                    tex = ImportTexture(path, false, 2048, TextureWrapMode.Repeat, failures);
                // tiling = texture repeats across the floor's width; UVs are world-space so the
                // solid floor and the fading apron line up exactly.
                float uvPerMetre = Mathf.Max(0.1f, f.tiling) / sx;
                // Textured floors are balanced to a mean albedo of ~0.42 so a pale texture doesn't
                // blow out under the key light + HDRI ambient (Gamma space, no tonemapping).
                var color = Col(f.color);
                if (tex != null)
                {
                    Color texMean;
                    float mean = MeanColor(path, out texMean);
                    float k = mean > 0.02f ? Mathf.Clamp(0.42f / mean, 0.5f, 1f) : 0.85f;
                    color = new Color(k, k, k);
                    if (mean > 0.02f) s_floorTexMean = texMean;
                }

                var floor = new GameObject("Floor");
                floor.transform.SetParent(parent, false);
                floor.transform.position = new Vector3(0f, f.height, 0f);
                floor.AddComponent<MeshFilter>().sharedMesh = FloorMesh(genFolder + "/FloorMesh.asset", sx, sz, uvPerMetre, 16);
                var mat = new Material(Shader.Find("Standard"));
                mat.color = color;
                mat.SetFloat("_Glossiness", 0.18f);
                if (tex != null) mat.mainTexture = tex;
                AssetDatabase.CreateAsset(mat, genFolder + "/Floor.mat");
                s_floorMats.Add(mat);
                floor.AddComponent<MeshRenderer>().sharedMaterial = mat;

                var fadeShader = Shader.Find("SketchScape/FloorFade");
                if (fadeShader != null)
                {
                    float big = Mathf.Max(sx, sz);
                    var apron = new GameObject("Floor Apron");
                    apron.transform.SetParent(parent, false);
                    apron.transform.position = new Vector3(0f, f.height - 0.004f, 0f);
                    apron.AddComponent<MeshFilter>().sharedMesh = FloorMesh(genFolder + "/FloorApronMesh.asset", big * 2.8f, big * 2.8f, uvPerMetre, 24);
                    var am = new Material(fadeShader);
                    am.color = color;
                    if (tex != null) am.mainTexture = tex;
                    am.SetFloat("_Glossiness", 0.18f);
                    am.SetVector("_FadeCenter", Vector4.zero);
                    am.SetFloat("_FadeInner", big * 0.72f);   // square corners are at 0.707 * size
                    am.SetFloat("_FadeOuter", big * 1.35f);
                    am.SetFloat("_WorldTiling", uvPerMetre);
                    AssetDatabase.CreateAsset(am, genFolder + "/FloorApron.mat");
                    s_floorMats.Add(am);
                    var ar = apron.AddComponent<MeshRenderer>();
                    ar.sharedMaterial = am;
                    ar.shadowCastingMode = ShadowCastingMode.Off;
                }
            }
            if (f.enabled || spec.teleport.floor_collider)
            {
                var tp = new GameObject("Teleport Floor");
                tp.transform.SetParent(parent, false);
                tp.transform.position = new Vector3(0f, f.height - 0.05f, 0f);
                var box = tp.AddComponent<BoxCollider>();
                box.size = new Vector3(sx, 0.1f, sz);
            }
        }

        /// <summary>Flat grid mesh centred on its origin, normals up, UV = local xz * uvPerMetre.</summary>
        static Mesh FloorMesh(string assetPath, float sx, float sz, float uvPerMetre, int cells)
        {
            int n = Mathf.Clamp(cells, 1, 64);
            var verts = new Vector3[(n + 1) * (n + 1)];
            var uvs = new Vector2[verts.Length];
            var normals = new Vector3[verts.Length];
            var tangents = new Vector4[verts.Length];
            for (int z = 0; z <= n; z++)
                for (int x = 0; x <= n; x++)
                {
                    int i = z * (n + 1) + x;
                    var p = new Vector3((x / (float)n - 0.5f) * sx, 0f, (z / (float)n - 0.5f) * sz);
                    verts[i] = p;
                    uvs[i] = new Vector2(p.x, p.z) * uvPerMetre;
                    normals[i] = Vector3.up;
                    tangents[i] = new Vector4(1f, 0f, 0f, -1f);
                }
            var tris = new int[n * n * 6];
            int t = 0;
            for (int z = 0; z < n; z++)
                for (int x = 0; x < n; x++)
                {
                    int i = z * (n + 1) + x;
                    tris[t++] = i; tris[t++] = i + n + 1; tris[t++] = i + 1;
                    tris[t++] = i + 1; tris[t++] = i + n + 1; tris[t++] = i + n + 2;
                }
            var mesh = new Mesh { name = Path.GetFileNameWithoutExtension(assetPath) };
            mesh.vertices = verts;
            mesh.uv = uvs;
            mesh.normals = normals;
            mesh.tangents = tangents;
            mesh.triangles = tris;
            mesh.RecalculateBounds();
            AssetDatabase.CreateAsset(mesh, assetPath);
            return mesh;
        }

        static void BuildShell(RoomSpec spec, Dictionary<string, string> media, string genFolder, Transform parent, List<string> failures)
        {
            var s = spec.environment.shell;
            var c = V3(s.center);
            var size = V3(s.size, 1f);
            size = new Vector3(Mathf.Max(1f, size.x), Mathf.Max(1f, size.y), Mathf.Max(1f, size.z));
            var mat = new Material(Shader.Find("Standard"));
            mat.color = Col(s.wall_color);
            mat.SetFloat("_Glossiness", 0.08f);
            string path;
            if (!string.IsNullOrEmpty(s.wall_texture_url) && media.TryGetValue(s.wall_texture_url.Trim(), out path))
            {
                var tex = ImportTexture(path, false, 2048, TextureWrapMode.Repeat, failures);
                if (tex != null) { mat.mainTexture = tex; mat.mainTextureScale = new Vector2(Mathf.Max(1f, size.x / 2f), Mathf.Max(1f, size.y / 2f)); }
            }
            AssetDatabase.CreateAsset(mat, genFolder + "/Walls.mat");
            var shell = Group(parent.gameObject, "Room Shell");
            const float t = 0.08f;
            Wall(shell, "Wall North", c + new Vector3(0f, 0f, size.z / 2f + t / 2f), new Vector3(size.x + 2 * t, size.y, t), mat);
            Wall(shell, "Wall South", c + new Vector3(0f, 0f, -size.z / 2f - t / 2f), new Vector3(size.x + 2 * t, size.y, t), mat);
            Wall(shell, "Wall East", c + new Vector3(size.x / 2f + t / 2f, 0f, 0f), new Vector3(t, size.y, size.z), mat);
            Wall(shell, "Wall West", c + new Vector3(-size.x / 2f - t / 2f, 0f, 0f), new Vector3(t, size.y, size.z), mat);
            if (s.ceiling)
                Wall(shell, "Ceiling", c + new Vector3(0f, size.y / 2f + t / 2f, 0f), new Vector3(size.x + 2 * t, t, size.z + 2 * t), mat);
        }

        static void Wall(Transform parent, string name, Vector3 center, Vector3 size, Material mat)
        {
            var w = GameObject.CreatePrimitive(PrimitiveType.Cube);
            w.name = name;
            w.transform.SetParent(parent, false);
            w.transform.position = center;
            w.transform.localScale = size;
            w.GetComponent<Renderer>().sharedMaterial = mat;
        }

        // ------------------------------------------------------------------
        // Splats and objects
        // ------------------------------------------------------------------

        /// <summary>Adds a GsplatRenderer for the asset at path to go. Returns the asset or null.</summary>
        static Gsplat.GsplatAsset AttachSplat(GameObject go, string path, out string error)
        {
            error = null;
            if (string.IsNullOrEmpty(path)) { error = "no splat_path"; return null; }
            var asset = AssetDatabase.LoadAssetAtPath<Gsplat.GsplatAsset>(path);
            if (asset == null)
            {
                if (File.Exists(path)) AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
                asset = AssetDatabase.LoadAssetAtPath<Gsplat.GsplatAsset>(path);
            }
            if (asset == null) { error = (File.Exists(path) ? "not a splat: " : "missing: ") + path; return null; }
            var r = go.AddComponent<Gsplat.GsplatRenderer>();
            r.GsplatAsset = asset;
            var so = new SerializedObject(r);
            var migrated = so.FindProperty("m_gammaToLinearDefaultApplied");
            if (migrated != null) migrated.boolValue = true;
            // Splat colours are sRGB: convert to linear only when the project renders in linear space.
            var g2l = so.FindProperty("GammaToLinear");
            if (g2l != null) g2l.boolValue = PlayerSettings.colorSpace == ColorSpace.Linear;
            so.ApplyModifiedPropertiesWithoutUndo();
            return asset;
        }

        static GameObject BuildObject(Transform root, RoomObject o, string id, string genFolder, List<string> failures, out string kind)
        {
            var go = new GameObject(id);
            go.transform.SetParent(root, false);
            bool upright = o.mode != "transform";
            float sizeM = Mathf.Clamp(o.size_m > 0f ? o.size_m : 0.4f, 0.02f, 20f);

            var child = new GameObject("Splat");
            child.transform.SetParent(go.transform, false);
            string err = null;
            Gsplat.GsplatAsset asset = null;
            if (!string.IsNullOrEmpty(o.splat_path)) asset = AttachSplat(child, o.splat_path, out err);

            if (asset == null)
            {
                UnityEngine.Object.DestroyImmediate(child);
                if (!string.IsNullOrEmpty(o.splat_path)) failures.Add(id + ": " + err + " -> cube");
                var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
                cube.name = "Placeholder";
                UnityEngine.Object.DestroyImmediate(cube.GetComponent<Collider>());
                cube.transform.SetParent(go.transform, false);
                var mat = new Material(Shader.Find("Standard"));
                mat.color = Col(o.tint);
                mat.SetFloat("_Glossiness", 0.25f);
                AssetDatabase.CreateAsset(mat, genFolder + "/Placeholder_" + SafeFile(id) + ".mat");
                cube.GetComponent<Renderer>().sharedMaterial = mat;
                float s = upright ? sizeM : Mathf.Clamp(o.size_m > 0f ? o.size_m : 0.3f, 0.02f, 20f);
                cube.transform.localScale = Vector3.one * s;
                go.transform.position = V3(o.position);
                go.transform.rotation = upright ? YawOnly(Q(o.rotation)) : Q(o.rotation);
                // Upright: position is the floor contact point, so lift the cube by half its size.
                cube.transform.localPosition = upright ? new Vector3(0f, s / 2f, 0f) : Vector3.zero;
                var cb = go.AddComponent<BoxCollider>();
                cb.center = cube.transform.localPosition;
                cb.size = Vector3.one * s;
                kind = "cube";
                return go;
            }

            var ab = asset.Bounds;
            if (upright)
            {
                // Fast-SAM3D scans are right-handed and Z-up in PLY coordinates. Gsplat imports
                // PLY (x,y,z) as (x,y,-z) - that z flip is exactly the one reflection a right-handed
                // source needs in left-handed Unity - so a proper rotation is all that is left:
                // Euler(90,0,0) maps the asset to Unity (x_ply, z_ply, y_ply): PLY +Z becomes up,
                // unmirrored. (Verified: a camera-frame scene splat placed the same way matches its photo.)
                float largest = Mathf.Max(ab.size.x, Mathf.Max(ab.size.y, ab.size.z));
                float s = sizeM / Mathf.Max(1e-4f, largest);
                child.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
                child.transform.localScale = new Vector3(s, s, s);
                var local = TransformBounds(Matrix4x4.TRS(Vector3.zero, child.transform.localRotation, child.transform.localScale), ab);
                // Stand the bottom-centre of the scan on the parent's origin (the floor contact point).
                child.transform.localPosition = -new Vector3(local.center.x, local.min.y, local.center.z);
                go.transform.position = V3(o.position);
                go.transform.rotation = YawOnly(Q(o.rotation));
                var box = go.AddComponent<BoxCollider>();
                box.center = new Vector3(0f, local.size.y / 2f, 0f);
                box.size = local.size;
                kind = "splat,upright";
            }
            else
            {
                // Transform mode: the splat's world transform is exactly position/rotation/scale.
                go.transform.position = V3(o.position);
                go.transform.rotation = Q(o.rotation);
                child.transform.localScale = V3(o.scale, 1f);
                var local = TransformBounds(Matrix4x4.Scale(child.transform.localScale), ab);
                var box = go.AddComponent<BoxCollider>();
                box.center = local.center;
                box.size = new Vector3(Mathf.Max(0.01f, local.size.x), Mathf.Max(0.01f, local.size.y), Mathf.Max(0.01f, local.size.z));
                kind = "splat,transform";
            }
            return go;
        }

        /// <summary>
        /// Splats cast no shadows, so a soft dark blob under each floor-standing object keeps it
        /// visually grounded. Skipped when the object doesn't touch the floor (e.g. on a sofa).
        /// </summary>
        static void AddContactShadow(GameObject obj, float floorY, string genFolder)
        {
            var box = obj.GetComponent<BoxCollider>();
            if (box == null) return;
            var world = TransformBounds(obj.transform.localToWorldMatrix, new Bounds(box.center, box.size));
            if (world.min.y - floorY > 0.06f) return;
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Contact Shadow";
            UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
            quad.transform.SetParent(obj.transform, true);
            quad.transform.position = new Vector3(world.center.x, floorY + 0.004f, world.center.z);
            // Upright objects are yaw-only: use their own footprint and yaw. Otherwise the
            // world-aligned footprint of the (arbitrarily rotated) object.
            var up = obj.transform.up;
            bool yawOnly = Vector3.Dot(up, Vector3.up) > 0.999f;
            float fx = yawOnly ? box.size.x : world.size.x;
            float fz = yawOnly ? box.size.z : world.size.z;
            quad.transform.rotation = Quaternion.Euler(90f, yawOnly ? obj.transform.eulerAngles.y : 0f, 0f);
            float sx = Mathf.Max(0.08f, fx * 1.6f + 0.06f), sz = Mathf.Max(0.08f, fz * 1.6f + 0.06f);
            quad.transform.localScale = new Vector3(sx, sz, 1f);   // object roots are never scaled
            var r = quad.GetComponent<Renderer>();
            r.sharedMaterial = ContactShadowMaterial(genFolder);
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
        }

        static Material s_shadowMat;

        static Material ContactShadowMaterial(string genFolder)
        {
            string matPath = genFolder + "/ContactShadow.mat";
            if (s_shadowMat != null && AssetDatabase.GetAssetPath(s_shadowMat) == matPath) return s_shadowMat;
            var shader = Shader.Find("SketchScape/ContactShadow");
            var mat = new Material(shader != null ? shader : Shader.Find("Sprites/Default"));
            mat.mainTexture = RadialTexture("_contact_shadow_v4", 1.3f, 0.25f);
            mat.SetFloat("_Strength", 0.72f);
            AssetDatabase.CreateAsset(mat, matPath);
            s_shadowMat = mat;
            return mat;
        }

        /// <summary>A white 64x64 texture whose alpha falls off radially; cached in WebCache.</summary>
        static Texture2D RadialTexture(string name, float power, float core = 0f)
        {
            string texPath = RoomKitWeb.CacheFolder + "/" + name + ".png";
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
            if (tex != null) return tex;
            RoomKitWeb.EnsureFolder(RoomKitWeb.CacheFolder);
            const int n = 64;
            var t = new Texture2D(n, n, TextureFormat.RGBA32, false);
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                {
                    float dx = (x + 0.5f) / n * 2f - 1f, dy = (y + 0.5f) / n * 2f - 1f;
                    float a = Mathf.Pow(1f - Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(core, 1f, Mathf.Sqrt(dx * dx + dy * dy))), power);
                    t.SetPixel(x, y, new Color(1f, 1f, 1f, a));
                }
            File.WriteAllBytes(texPath, t.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(t);
            AssetDatabase.ImportAsset(texPath, ImportAssetOptions.ForceSynchronousImport);
            var imp = AssetImporter.GetAtPath(texPath) as TextureImporter;
            if (imp != null)
            {
                imp.alphaIsTransparency = true;
                imp.wrapMode = TextureWrapMode.Clamp;
                imp.mipmapEnabled = true;
                imp.SaveAndReimport();
            }
            return AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
        }

        /// <summary>8x64 white texture whose alpha falls off across V (the line's width): soft line edges.</summary>
        static Texture2D SoftLineTexture()
        {
            string texPath = RoomKitWeb.CacheFolder + "/_soft_line_v1.png";
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
            if (tex != null) return tex;
            RoomKitWeb.EnsureFolder(RoomKitWeb.CacheFolder);
            var t = new Texture2D(8, 64, TextureFormat.RGBA32, false);
            for (int y = 0; y < 64; y++)
            {
                float d = Mathf.Abs((y + 0.5f) / 64f * 2f - 1f);
                float a = Mathf.Pow(1f - Mathf.SmoothStep(0f, 1f, d), 1.6f);
                for (int x = 0; x < 8; x++) t.SetPixel(x, y, new Color(1f, 1f, 1f, a));
            }
            File.WriteAllBytes(texPath, t.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(t);
            AssetDatabase.ImportAsset(texPath, ImportAssetOptions.ForceSynchronousImport);
            var imp = AssetImporter.GetAtPath(texPath) as TextureImporter;
            if (imp != null)
            {
                imp.alphaIsTransparency = true;
                imp.wrapMode = TextureWrapMode.Clamp;
                imp.mipmapEnabled = true;
                imp.SaveAndReimport();
            }
            return AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
        }

        static Material GlowMaterial(string genFolder, string name, bool additive, Texture2D tex)
        {
            var shader = Shader.Find("SketchScape/Glow");
            Material mat;
            if (shader != null)
            {
                mat = new Material(shader);
                mat.SetFloat("_DstBlend", additive ? (float)BlendMode.One : (float)BlendMode.OneMinusSrcAlpha);
            }
            else mat = new Material(AssetDatabase.GetBuiltinExtraResource<Material>("Default-ParticleSystem.mat"));
            if (tex != null) mat.mainTexture = tex;
            AssetDatabase.CreateAsset(mat, genFolder + "/" + name + ".mat");
            return mat;
        }

        static Bounds TransformBounds(Matrix4x4 m, Bounds b)
        {
            var min = b.min; var max = b.max;
            var result = new Bounds(m.MultiplyPoint3x4(min), Vector3.zero);
            for (int i = 1; i < 8; i++)
            {
                var p = new Vector3((i & 1) != 0 ? max.x : min.x, (i & 2) != 0 ? max.y : min.y, (i & 4) != 0 ? max.z : min.z);
                result.Encapsulate(m.MultiplyPoint3x4(p));
            }
            return result;
        }

        // ------------------------------------------------------------------
        // Images, particles, motif
        // ------------------------------------------------------------------

        static Light BuildImage(Transform parent, RoomImage im, Texture2D tex, int index, string genFolder)
        {
            float w = Mathf.Clamp(im.width, 0.1f, 6f);
            float h = w * tex.height / Mathf.Max(1f, tex.width);
            var holder = new GameObject("Image - " + Label(im.title, "picture " + (index + 1)));
            holder.transform.SetParent(parent, false);
            holder.transform.position = V3(im.position);
            holder.transform.rotation = Q(im.rotation);

            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Picture";
            UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
            quad.transform.SetParent(holder.transform, false);
            quad.transform.localScale = new Vector3(w, h, 1f);
            var mat = new Material(Shader.Find(im.lit ? "Standard" : "Unlit/Texture"));
            mat.mainTexture = tex;
            if (im.lit) { mat.color = Color.white; mat.SetFloat("_Glossiness", 0.3f); }
            AssetDatabase.CreateAsset(mat, genFolder + "/Image_" + index + ".mat");
            quad.GetComponent<Renderer>().sharedMaterial = mat;
            quad.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off;

            if (im.frame)
            {
                var frame = GameObject.CreatePrimitive(PrimitiveType.Cube);
                frame.name = "Frame";
                UnityEngine.Object.DestroyImmediate(frame.GetComponent<Collider>());
                frame.transform.SetParent(holder.transform, false);
                float b = Mathf.Clamp(w * 0.06f, 0.025f, 0.12f);
                frame.transform.localScale = new Vector3(w + 2f * b, h + 2f * b, 0.035f);
                frame.transform.localPosition = new Vector3(0f, 0f, 0.0185f);   // just behind the picture
                var fm = new Material(Shader.Find("Standard"));
                fm.color = Col(im.frame_color);
                fm.SetFloat("_Glossiness", 0.45f);
                AssetDatabase.CreateAsset(fm, genFolder + "/Frame_" + index + ".mat");
                frame.GetComponent<Renderer>().sharedMaterial = fm;
            }

            string caption = Label(im.title, "");
            if (!string.IsNullOrEmpty(im.attribution)) caption += (caption.Length > 0 ? "\n" : "") + im.attribution;
            if (caption.Length > 0)
            {
                var textGo = new GameObject("Caption");
                textGo.transform.SetParent(holder.transform, false);
                textGo.transform.localPosition = new Vector3(0f, -h / 2f - 0.09f, -0.005f);
                var tm = textGo.AddComponent<TextMesh>();
                var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                tm.font = font;
                tm.text = caption.Length > 140 ? caption.Substring(0, 137) + "..." : caption;
                tm.fontSize = 48;
                tm.characterSize = 0.0045f;
                tm.anchor = TextAnchor.UpperCenter;
                tm.alignment = TextAlignment.Center;
                tm.color = new Color(0.92f, 0.9f, 0.86f);
                textGo.GetComponent<MeshRenderer>().sharedMaterial = font.material;
            }

            if (!im.lit) return null;
            var spot = NewLight(holder.transform, "Picture Light", LightType.Spot, new Color(1f, 0.93f, 0.82f), 1.1f);
            spot.transform.localPosition = new Vector3(0f, h / 2f + 0.35f, -0.55f);
            spot.transform.LookAt(holder.transform.position);
            spot.range = 2.5f;
            spot.spotAngle = Mathf.Clamp(2f * Mathf.Rad2Deg * Mathf.Atan2(Mathf.Max(w, h) * 0.6f, 0.7f), 30f, 110f);
            spot.shadows = LightShadows.None;
            return spot;
        }

        static void BuildParticles(Transform parent, RoomParticles p, string genFolder, int index)
        {
            string kind = string.IsNullOrEmpty(p.kind) ? "dust" : p.kind.ToLowerInvariant();
            var go = new GameObject("Particles - " + kind);
            go.transform.SetParent(parent, false);
            var size = V3(p.size, 4f);
            size = new Vector3(Mathf.Max(0.2f, size.x), Mathf.Max(0.2f, size.y), Mathf.Max(0.2f, size.z));
            var center = V3(p.position);
            var color = Col(p.color);
            float rate = Mathf.Clamp(p.rate, 1f, 400f);

            var ps = go.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = ps.main;
            main.loop = true;
            main.prewarm = true;
            main.playOnAwake = true;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.gravityModifier = 0f;
            var emission = ps.emission;
            var shape = ps.shape;
            shape.enabled = true;
            shape.shapeType = ParticleSystemShapeType.Box;
            var noise = ps.noise;
            var col = ps.colorOverLifetime;
            col.enabled = true;
            var renderer = go.GetComponent<ParticleSystemRenderer>();
            bool additive = kind != "snow" && kind != "rain";
            renderer.sharedMaterial = GlowMaterial(genFolder, "Particles_" + index + "_" + SafeFile(kind), additive, RadialTexture("_soft_dot", 1.4f));
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.maxParticleSize = 0.05f;

            float lifetime;
            switch (kind)
            {
                case "fireflies":
                    lifetime = 6f;
                    main.startLifetime = new ParticleSystem.MinMaxCurve(4f, 7f);
                    main.startSpeed = new ParticleSystem.MinMaxCurve(0.02f, 0.12f);
                    main.startSize = new ParticleSystem.MinMaxCurve(0.025f, 0.045f);
                    main.startColor = color;
                    go.transform.position = center;
                    shape.scale = size;
                    noise.enabled = true; noise.strength = 0.35f; noise.frequency = 0.4f; noise.scrollSpeed = 0.2f; noise.quality = ParticleSystemNoiseQuality.Low;
                    col.color = Blink(color);
                    break;
                case "snow":
                    lifetime = size.y / 0.35f;
                    main.startLifetime = lifetime;
                    main.startSpeed = 0f;
                    main.startSize = new ParticleSystem.MinMaxCurve(0.015f, 0.035f);
                    main.startColor = color;
                    go.transform.position = center + new Vector3(0f, size.y / 2f, 0f);
                    shape.scale = new Vector3(size.x, 0.05f, size.z);
                    var vel = ps.velocityOverLifetime; vel.enabled = true; vel.space = ParticleSystemSimulationSpace.World;
                    vel.x = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f); vel.y = new ParticleSystem.MinMaxCurve(-0.4f, -0.3f); vel.z = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f);
                    noise.enabled = true; noise.strength = 0.12f; noise.frequency = 0.5f; noise.quality = ParticleSystemNoiseQuality.Low;
                    col.color = FadeInOut(color, 0.9f);
                    break;
                case "rain":
                    lifetime = size.y / 6f;
                    main.startLifetime = lifetime;
                    main.startSpeed = 0f;
                    main.startSize = new ParticleSystem.MinMaxCurve(0.008f, 0.012f);
                    main.startColor = new Color(color.r, color.g, color.b, 0.45f);
                    go.transform.position = center + new Vector3(0f, size.y / 2f, 0f);
                    shape.scale = new Vector3(size.x, 0.05f, size.z);
                    var rv = ps.velocityOverLifetime; rv.enabled = true; rv.space = ParticleSystemSimulationSpace.World;
                    rv.x = 0f; rv.y = new ParticleSystem.MinMaxCurve(-6.5f, -5.5f); rv.z = 0f;
                    renderer.renderMode = ParticleSystemRenderMode.Stretch;
                    renderer.velocityScale = 0.06f;
                    renderer.lengthScale = 1f;
                    col.color = FadeInOut(new Color(color.r, color.g, color.b, 0.45f), 1f);
                    rate *= 4f;
                    break;
                case "embers":
                    lifetime = 4f;
                    main.startLifetime = new ParticleSystem.MinMaxCurve(2.5f, 5f);
                    main.startSpeed = 0f;
                    main.startSize = new ParticleSystem.MinMaxCurve(0.012f, 0.028f);
                    main.startColor = color;
                    go.transform.position = center - new Vector3(0f, size.y / 2f, 0f);
                    shape.scale = new Vector3(size.x, 0.05f, size.z);
                    var ev = ps.velocityOverLifetime; ev.enabled = true; ev.space = ParticleSystemSimulationSpace.World;
                    ev.x = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f); ev.y = new ParticleSystem.MinMaxCurve(0.25f, 0.7f); ev.z = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f);
                    noise.enabled = true; noise.strength = 0.25f; noise.frequency = 0.8f; noise.quality = ParticleSystemNoiseQuality.Low;
                    col.color = Embers(color);
                    break;
                default: // dust motes in the light
                    lifetime = 10f;
                    main.startLifetime = new ParticleSystem.MinMaxCurve(8f, 12f);
                    main.startSpeed = new ParticleSystem.MinMaxCurve(0.005f, 0.03f);
                    main.startSize = new ParticleSystem.MinMaxCurve(0.006f, 0.016f);
                    main.startColor = new Color(color.r, color.g, color.b, 0.5f);
                    go.transform.position = center;
                    shape.scale = size;
                    noise.enabled = true; noise.strength = 0.04f; noise.frequency = 0.3f; noise.scrollSpeed = 0.05f; noise.quality = ParticleSystemNoiseQuality.Low;
                    col.color = FadeInOut(new Color(color.r, color.g, color.b, 0.5f), 0.2f);
                    break;
            }
            emission.rateOverTime = rate;
            main.maxParticles = Mathf.Clamp(Mathf.CeilToInt(rate * lifetime * 1.2f), 16, 600);
            ps.Play(true);
        }

        static ParticleSystem.MinMaxGradient FadeInOut(Color c, float edge)
        {
            var g = new Gradient();
            float e = Mathf.Clamp(edge, 0.05f, 0.45f);
            g.SetKeys(new[] { new GradientColorKey(c, 0f), new GradientColorKey(c, 1f) },
                      new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(c.a, e), new GradientAlphaKey(c.a, 1f - e), new GradientAlphaKey(0f, 1f) });
            return new ParticleSystem.MinMaxGradient(g);
        }

        static ParticleSystem.MinMaxGradient Blink(Color c)
        {
            var g = new Gradient();
            g.SetKeys(new[] { new GradientColorKey(c, 0f), new GradientColorKey(c, 1f) },
                      new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.2f), new GradientAlphaKey(0.15f, 0.45f),
                              new GradientAlphaKey(1f, 0.7f), new GradientAlphaKey(0f, 1f) });
            return new ParticleSystem.MinMaxGradient(g);
        }

        static ParticleSystem.MinMaxGradient Embers(Color c)
        {
            var g = new Gradient();
            var hot = Color.Lerp(c, new Color(1f, 0.95f, 0.6f), 0.5f);
            var cool = Color.Lerp(c, new Color(0.4f, 0.05f, 0f), 0.5f);
            g.SetKeys(new[] { new GradientColorKey(hot, 0f), new GradientColorKey(c, 0.5f), new GradientColorKey(cool, 1f) },
                      new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.1f), new GradientAlphaKey(0.8f, 0.7f), new GradientAlphaKey(0f, 1f) });
            return new ParticleSystem.MinMaxGradient(g);
        }

        static LineRenderer BuildMotif(Transform parent, float[] xz, float floorY, Color mood, string genFolder)
        {
            var pts = new List<Vector3>();
            for (int i = 0; i + 1 < xz.Length; i += 2) pts.Add(new Vector3(xz[i], floorY + 0.025f, xz[i + 1]));
            // Catmull-Rom smoothing so a few control points become a soft curve.
            var smooth = new List<Vector3>();
            if (pts.Count >= 3)
            {
                for (int i = 0; i < pts.Count - 1; i++)
                {
                    var p0 = pts[Mathf.Max(0, i - 1)]; var p1 = pts[i]; var p2 = pts[i + 1]; var p3 = pts[Mathf.Min(pts.Count - 1, i + 2)];
                    for (int k = 0; k < 8; k++)
                    {
                        float t = k / 8f, t2 = t * t, t3 = t2 * t;
                        smooth.Add(0.5f * ((2f * p1) + (-p0 + p2) * t + (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2 + (-p0 + 3f * p1 - 3f * p2 + p3) * t3));
                    }
                }
                smooth.Add(pts[pts.Count - 1]);
            }
            else smooth = pts;

            var go = new GameObject("Connecting Motif");
            go.transform.SetParent(parent, false);
            // Lie flat on the floor (TransformZ alignment with Z pointing up): a soft glowing
            // inlay path, not a camera-facing ribbon.
            go.transform.rotation = Quaternion.Euler(-90f, 0f, 0f);
            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace = true;
            lr.positionCount = smooth.Count;
            lr.SetPositions(smooth.ToArray());
            lr.widthMultiplier = 0.06f;
            lr.numCapVertices = 6;
            lr.numCornerVertices = 3;
            lr.alignment = LineAlignment.TransformZ;
            lr.textureMode = LineTextureMode.Stretch;
            lr.sharedMaterial = GlowMaterial(genFolder, "Motif", true, SoftLineTexture());
            var bright = Color.Lerp(mood, Color.white, 0.15f);
            lr.startColor = new Color(bright.r, bright.g, bright.b, 0.32f);
            lr.endColor = new Color(mood.r, mood.g, mood.b, 0.22f);
            lr.shadowCastingMode = ShadowCastingMode.Off;
            lr.receiveShadows = false;
            return lr;
        }

        // ------------------------------------------------------------------
        // Imports
        // ------------------------------------------------------------------

        static Texture2D ImportTexture(string path, bool hdr, int maxSize, TextureWrapMode wrap, List<string> failures)
        {
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) { failures.Add("not a texture: " + path); return null; }
            bool changed = false;
            if (importer.textureType != TextureImporterType.Default) { importer.textureType = TextureImporterType.Default; changed = true; }
            if (importer.textureShape != TextureImporterShape.Texture2D) { importer.textureShape = TextureImporterShape.Texture2D; changed = true; }
            if (importer.maxTextureSize != maxSize) { importer.maxTextureSize = maxSize; changed = true; }
            if (importer.wrapMode != wrap) { importer.wrapMode = wrap; changed = true; }
            if (hdr)
            {
                // Equirect sky: no mips (avoids the lat-long seam), clamp V at the poles.
                if (importer.mipmapEnabled) { importer.mipmapEnabled = false; changed = true; }
                if (importer.wrapModeV != TextureWrapMode.Clamp) { importer.wrapModeV = TextureWrapMode.Clamp; changed = true; }
            }
            else
            {
                if (!importer.mipmapEnabled) { importer.mipmapEnabled = true; changed = true; }
                if (importer.anisoLevel != 4) { importer.anisoLevel = 4; changed = true; }
                if (!importer.sRGBTexture) { importer.sRGBTexture = true; changed = true; }
            }
            if (changed) importer.SaveAndReimport();
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (tex == null) failures.Add("texture import failed: " + path);
            return tex;
        }

        static AudioClip ImportClip(string path, bool spatial, List<string> failures)
        {
            var importer = AssetImporter.GetAtPath(path) as AudioImporter;
            if (importer == null) { failures.Add("not audio: " + path); return null; }
            bool changed = false;
            long bytes = new FileInfo(path).Length;
            var s = importer.defaultSampleSettings;
            var load = bytes > 1024 * 1024 ? AudioClipLoadType.Streaming : AudioClipLoadType.CompressedInMemory;
            if (s.loadType != load) { s.loadType = load; changed = true; }
            if (s.compressionFormat != AudioCompressionFormat.Vorbis) { s.compressionFormat = AudioCompressionFormat.Vorbis; s.quality = 0.6f; changed = true; }
            if (changed) importer.defaultSampleSettings = s;
            if (importer.forceToMono != spatial) { importer.forceToMono = spatial; changed = true; }
            if (changed) importer.SaveAndReimport();
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(path);
            if (clip == null) failures.Add("audio import failed: " + path);
            return clip;
        }

        // ------------------------------------------------------------------
        // Credits, helpers
        // ------------------------------------------------------------------

        static string WriteCredits(RoomSpec spec)
        {
            var lines = new List<string> { "Credits for " + spec.slug + " (" + spec.scene_path + ")", "" };
            foreach (var c in spec.credits) if (!string.IsNullOrEmpty(c) && !lines.Contains(c)) lines.Add(c);
            foreach (var im in spec.images)
                if (!string.IsNullOrEmpty(im.url)) AddCredit(lines, "Image", im.title, im.attribution, im.url);
            foreach (var au in spec.audio)
                if (!string.IsNullOrEmpty(au.url)) AddCredit(lines, "Sound", au.title, au.attribution, au.url);
            if (!string.IsNullOrEmpty(spec.environment.hdri_url)) AddCredit(lines, "Sky (HDRI)", "", "", spec.environment.hdri_url);
            if (!string.IsNullOrEmpty(spec.environment.floor.texture_url)) AddCredit(lines, "Floor texture", "", "", spec.environment.floor.texture_url);
            if (!string.IsNullOrEmpty(spec.staging.narration)) { lines.Add(""); lines.Add("Narration: " + spec.staging.narration); }
            string path = AgentRoomsFolder + "/" + spec.slug + "_credits.txt";
            try
            {
                File.WriteAllText(path, string.Join("\n", lines) + "\n");
                AssetDatabase.ImportAsset(path);
                return path;
            }
            catch (Exception) { return null; }
        }

        static void AddCredit(List<string> lines, string kind, string title, string attribution, string url)
        {
            var line = kind + ": " + (string.IsNullOrEmpty(title) ? "" : "'" + title + "' ") +
                       (string.IsNullOrEmpty(attribution) ? "" : attribution + " ") + "<" + url + ">";
            if (!lines.Contains(line)) lines.Add(line);
        }

        static void Normalize(RoomSpec s)
        {
            if (s.slug == null) s.slug = "";
            if (s.scene_path == null) s.scene_path = "";
            if (s.root == null) s.root = "";
            if (s.player == null) s.player = new RoomPlayer();
            if (s.photo_scene == null) s.photo_scene = new RoomPhotoScene();
            if (s.objects == null) s.objects = new RoomObject[0];
            if (s.environment == null) s.environment = new RoomEnvironment();
            if (s.environment.fog == null) s.environment.fog = new RoomFog();
            if (s.environment.floor == null) s.environment.floor = new RoomFloor();
            if (s.environment.shell == null) s.environment.shell = new RoomShell();
            if (s.lights == null) s.lights = new RoomLight[0];
            if (s.images == null) s.images = new RoomImage[0];
            if (s.audio == null) s.audio = new RoomAudio[0];
            if (s.particles == null) s.particles = new RoomParticles[0];
            if (s.staging == null) s.staging = new RoomStaging();
            if (s.teleport == null) s.teleport = new RoomTeleport();
            if (s.credits == null) s.credits = new string[0];
            foreach (var o in s.objects) if (o != null && o.light == null) o.light = new RoomObjectLight();
            var list = new List<RoomObject>();
            foreach (var o in s.objects) if (o != null) list.Add(o);
            s.objects = list.ToArray();
        }

        static string CheckSlug(string slug)
        {
            if (string.IsNullOrEmpty(slug)) return "slug is required.";
            if (slug.Length > 64) return "slug is too long.";
            foreach (char ch in slug)
                if (!(char.IsLetterOrDigit(ch) || ch == '_' || ch == '-'))
                    return "slug may contain only letters, digits, '_' and '-' (got '" + slug + "').";
            return null;
        }

        static Transform Group(GameObject root, string name)
        {
            var g = new GameObject(name);
            g.transform.SetParent(root.transform, false);
            return g.transform;
        }

        static Transform Group(Transform root, string name) { return Group(root.gameObject, name); }

        static Light NewLight(Transform parent, string name, LightType type, Color color, float intensity)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var l = go.AddComponent<Light>();
            l.type = type;
            l.color = color;
            l.intensity = Mathf.Max(0f, intensity);
            l.shadows = LightShadows.None;
            l.lightmapBakeType = LightmapBakeType.Realtime;
            return l;
        }

        static LightType ParseLightType(string s)
        {
            switch ((s ?? "").ToLowerInvariant())
            {
                case "point": return LightType.Point;
                case "spot": return LightType.Spot;
                default: return LightType.Directional;
            }
        }

        static LightShadows ParseShadows(string s)
        {
            switch ((s ?? "").ToLowerInvariant())
            {
                case "soft": return LightShadows.Soft;
                case "hard": return LightShadows.Hard;
                default: return LightShadows.None;
            }
        }

        static string UniqueName(string id, Dictionary<string, Transform> used)
        {
            if (!used.ContainsKey(id)) return id;
            for (int i = 2; ; i++) if (!used.ContainsKey(id + "_" + i)) return id + "_" + i;
        }

        static string Label(string s, string fallback)
        {
            if (string.IsNullOrEmpty(s)) return fallback;
            s = s.Replace("\n", " ").Trim();
            return s.Length > 48 ? s.Substring(0, 45) + "..." : s;
        }

        static string SafeFile(string s)
        {
            var sb = new StringBuilder();
            foreach (char ch in s) sb.Append(char.IsLetterOrDigit(ch) || ch == '_' || ch == '-' ? ch : '_');
            return sb.ToString();
        }

        static Quaternion YawOnly(Quaternion q)
        {
            var f = q * Vector3.forward;
            f.y = 0f;
            if (f.sqrMagnitude < 1e-6f) return Quaternion.identity;
            return Quaternion.LookRotation(f.normalized, Vector3.up);
        }

        static Vector3 V3(float[] a, float fallback = 0f)
        {
            if (a == null) return new Vector3(fallback, fallback, fallback);
            return new Vector3(a.Length > 0 ? a[0] : fallback, a.Length > 1 ? a[1] : fallback, a.Length > 2 ? a[2] : fallback);
        }

        static Quaternion Q(float[] a)
        {
            if (a == null || a.Length < 4) return Quaternion.identity;
            var q = new Quaternion(a[0], a[1], a[2], a[3]);
            float n = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            if (n < 1e-6f || float.IsNaN(n)) return Quaternion.identity;
            return new Quaternion(q.x / n, q.y / n, q.z / n, q.w / n);
        }

        static Color Col(float[] a)
        {
            if (a == null || a.Length < 3) return Color.white;
            return new Color(Mathf.Clamp01(a[0]), Mathf.Clamp01(a[1]), Mathf.Clamp01(a[2]), 1f);
        }

        /// <summary>
        /// Puts the Scene View camera exactly where the player's eyes are at the spawn point, facing
        /// the spawn yaw and pitched down towards the room's content (photo scene or objects).
        /// </summary>
        static void FrameSceneView(Vector3 spawn, float yaw, float eyeHeight, GameObject root)
        {
            var view = SceneView.lastActiveSceneView;
            if (view == null) return;
            view.orthographic = false;
            var eye = new Vector3(spawn.x, spawn.y + Mathf.Clamp(eyeHeight > 0f ? eyeHeight : 1.6f, 0.5f, 2.5f), spawn.z);
            float pitch = 8f;
            Vector3 target;
            if (root != null && ContentCenter(root, out target))
            {
                float flat = new Vector2(target.x - eye.x, target.z - eye.z).magnitude;
                pitch = Mathf.Clamp(Mathf.Atan2(eye.y - target.y, Mathf.Max(0.3f, flat)) * Mathf.Rad2Deg, 4f, 55f);
            }
            var rot = Quaternion.Euler(pitch, yaw, 0f);
            const float size = 0.25f;
            // cameraDistance depends only on size and FOV: set once to read it, then place the pivot.
            view.LookAtDirect(eye, rot, size);
            view.LookAtDirect(eye + rot * Vector3.forward * view.cameraDistance, rot, size);
            view.Repaint();
        }

        /// <summary>World centre of the photo scene splat if there is one, else of the objects' colliders.</summary>
        static bool ContentCenter(GameObject root, out Vector3 center)
        {
            center = Vector3.zero;
            var photo = root.transform.Find("Photo Scene");
            if (photo != null)
            {
                var r = photo.GetComponent<Gsplat.GsplatRenderer>();
                if (r != null && r.GsplatAsset != null)
                {
                    var wb = TransformBounds(photo.localToWorldMatrix, r.GsplatAsset.Bounds);
                    center = wb.center;
                    return true;
                }
            }
            bool any = false;
            var all = new Bounds();
            foreach (Transform child in root.transform)
            {
                var box = child.GetComponent<BoxCollider>();
                if (box == null) continue;
                var wb = TransformBounds(child.localToWorldMatrix, new Bounds(box.center, box.size));
                if (!any) { all = wb; any = true; } else all.Encapsulate(wb);
            }
            if (any) center = all.center;
            return any;
        }

        static readonly List<Material> s_floorMats = new List<Material>();
        static Color s_floorTexMean = Color.white;

        /// <summary>Mean sRGB colour of an image file; returns its luminance (0..1), or -1 if it can't be decoded.</summary>
        static float MeanColor(string path, out Color mean)
        {
            mean = Color.gray;
            try
            {
                var t = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                if (!t.LoadImage(File.ReadAllBytes(path), false)) { UnityEngine.Object.DestroyImmediate(t); return -1f; }
                float r = 0f, g = 0f, b = 0f;
                const int n = 24;
                for (int y = 0; y < n; y++)
                    for (int x = 0; x < n; x++)
                    {
                        var c = t.GetPixelBilinear((x + 0.5f) / n, (y + 0.5f) / n);
                        r += c.r; g += c.g; b += c.b;
                    }
                UnityEngine.Object.DestroyImmediate(t);
                mean = new Color(r / (n * n), g / (n * n), b / (n * n));
                return 0.2126f * mean.r + 0.7152f * mean.g + 0.0722f * mean.b;
            }
            catch (Exception) { return -1f; }
        }

        /// <summary>
        /// Mean colour of the photo scene's opaque splats that lie on the world floor plane (y ~ floorY).
        /// False when the photo has no floor there (e.g. a close-up of a raised surface).
        /// Spark packed layout: x = RGBA8, y = half(px) | half(py) << 16, z & 0xFFFF = half(pz).
        /// </summary>
        static bool PhotoFloorColor(GameObject photo, Gsplat.GsplatAsset asset, float floorY, out Color color)
        {
            color = Color.gray;
            var spark = asset as Gsplat.GsplatAssetSpark;
            if (spark == null || spark.PackedSplats == null || spark.PackedSplats.Length == 0) return false;
            var m = photo.transform.localToWorldMatrix;
            var ps = spark.PackedSplats;
            int n = ps.Length, step = Mathf.Max(1, n / 150000), sampled = 0, hits = 0;
            double r = 0, g = 0, b = 0;
            for (int i = 0; i < n; i += step)
            {
                sampled++;
                var u = ps[i];
                if ((u.x >> 24) < 128u) continue;
                float px = Mathf.HalfToFloat((ushort)(u.y & 0xFFFFu));
                float py = Mathf.HalfToFloat((ushort)(u.y >> 16));
                float pz = Mathf.HalfToFloat((ushort)(u.z & 0xFFFFu));
                float wy = m.m10 * px + m.m11 * py + m.m12 * pz + m.m13;
                if (Mathf.Abs(wy - floorY) > 0.06f) continue;
                r += u.x & 255u; g += (u.x >> 8) & 255u; b += (u.x >> 16) & 255u;
                hits++;
            }
            if (hits < 300 || hits * 50 < sampled) return false;
            color = new Color((float)(r / hits / 255.0), (float)(g / hits / 255.0), (float)(b / hits / 255.0));
            return true;
        }

        /// <summary>
        /// For a photo scene of a raised surface: finds the dominant horizontal band of opaque splats
        /// between 0.25 and 1.4 m (the seat / table top), and puts a plain box under its footprint,
        /// coloured like the surface but darker, from the room floor up to just below the band.
        /// Returns a report note, or null when no clear surface is found.
        /// </summary>
        static string BuildPlinth(Transform parent, GameObject photo, Gsplat.GsplatAsset asset, float floorY, string genFolder)
        {
            var spark = asset as Gsplat.GsplatAssetSpark;
            if (spark == null || spark.PackedSplats == null || spark.PackedSplats.Length == 0) return null;
            var m = photo.transform.localToWorldMatrix;
            var ps = spark.PackedSplats;
            int n = ps.Length, step = Mathf.Max(1, n / 120000);
            const float y0 = 0.25f, bin = 0.02f;
            const int bins = 58;
            var hist = new int[bins];
            int opaque = 0;
            for (int i = 0; i < n; i += step)
            {
                var u = ps[i];
                if ((u.x >> 24) < 128u) continue;
                float px = Mathf.HalfToFloat((ushort)(u.y & 0xFFFFu)), py = Mathf.HalfToFloat((ushort)(u.y >> 16)), pz = Mathf.HalfToFloat((ushort)(u.z & 0xFFFFu));
                float wy = m.m10 * px + m.m11 * py + m.m12 * pz + m.m13;
                opaque++;
                int b = Mathf.FloorToInt((wy - y0) / bin);
                if (b >= 0 && b < bins) hist[b]++;
            }
            int best = -1, bestCount = 0;
            for (int b = 0; b < bins; b++)
            {
                int c = hist[b] + (b > 0 ? hist[b - 1] : 0) + (b + 1 < bins ? hist[b + 1] : 0);
                if (c > bestCount) { bestCount = c; best = b; }
            }
            if (best < 0 || opaque == 0 || bestCount < opaque / 12) return null;
            float planeY = y0 + (best + 0.5f) * bin;
            var xs = new List<float>(); var zs = new List<float>();
            double r = 0, g = 0, bl = 0;
            for (int i = 0; i < n; i += step)
            {
                var u = ps[i];
                if ((u.x >> 24) < 128u) continue;
                float px = Mathf.HalfToFloat((ushort)(u.y & 0xFFFFu)), py = Mathf.HalfToFloat((ushort)(u.y >> 16)), pz = Mathf.HalfToFloat((ushort)(u.z & 0xFFFFu));
                var w = m.MultiplyPoint3x4(new Vector3(px, py, pz));
                if (Mathf.Abs(w.y - planeY) > 0.04f) continue;
                xs.Add(w.x); zs.Add(w.z);
                r += u.x & 255u; g += (u.x >> 8) & 255u; bl += (u.x >> 16) & 255u;
            }
            if (xs.Count < 200) return null;
            xs.Sort(); zs.Sort();
            int lo = xs.Count / 20, hi = xs.Count - 1 - xs.Count / 20;
            float x0 = xs[lo], x1 = xs[hi], z0 = zs[lo], z1 = zs[hi];
            // Well below the band: a real surface sags and folds (blankets, cushions) and the plinth
            // must never poke through the photo; the splat's own surface hides the gap.
            float top = planeY - 0.12f, height = top - floorY;
            if (height < 0.15f || x1 - x0 < 0.2f || z1 - z0 < 0.2f) return null;
            var mean = new Color((float)(r / xs.Count / 255.0), (float)(g / xs.Count / 255.0), (float)(bl / xs.Count / 255.0));
            var box = GameObject.CreatePrimitive(PrimitiveType.Cube);
            box.name = "Photo Plinth";
            UnityEngine.Object.DestroyImmediate(box.GetComponent<Collider>());
            box.transform.SetParent(parent, false);
            float inset = 0.97f;   // fills the holes where separately placed objects were cut out
            box.transform.position = new Vector3((x0 + x1) / 2f, floorY + height / 2f, (z0 + z1) / 2f);
            box.transform.localScale = new Vector3((x1 - x0) * inset, height, (z1 - z0) * inset);
            var mat = new Material(Shader.Find("Standard"));
            mat.color = mean * 0.55f;
            mat.SetFloat("_Glossiness", 0.08f);
            AssetDatabase.CreateAsset(mat, genFolder + "/PhotoPlinth.mat");
            box.GetComponent<Renderer>().sharedMaterial = mat;
            return "plinth under the photo surface (top " + top.ToString("0.00") + " m, " + (x1 - x0).ToString("0.0") + " x " + (z1 - z0).ToString("0.0") + " m)";
        }

        /// <summary>Material colour that makes (texture mean x colour), lit by ~1.1, match the photo floor.</summary>
        static Color FloorTint(Color photoFloor, Color texMean)
        {
            const float lit = 0.9f;
            return new Color(Mathf.Clamp(lit * photoFloor.r / Mathf.Max(0.05f, texMean.r), 0.12f, 1.1f),
                             Mathf.Clamp(lit * photoFloor.g / Mathf.Max(0.05f, texMean.g), 0.12f, 1.1f),
                             Mathf.Clamp(lit * photoFloor.b / Mathf.Max(0.05f, texMean.b), 0.12f, 1.1f), 1f);
        }

        static string Clip(string s)
        {
            return s.Length <= MaxReport ? s : s.Substring(0, MaxReport - 3) + "...";
        }
    }
}
