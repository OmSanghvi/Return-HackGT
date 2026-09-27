// SketchScape RoomPolish — hardcoded visual polish for selected AgentRooms scenes.
//
// Adds a real room shell (walls, ceiling, baseboards, light panels) around the photo splat,
// grounds props, retunes lights/ambient/probe, shrinks the teleport floor to the room and
// makes the splat renderers sort every few frames. Everything it creates lives under a
// "Polish" child of the room root, so running it again is safe (Polish is rebuilt).
//
// Per-scene work: RoomPolish.Bed.cs, RoomPolish.HackgtWorkspace.cs, RoomPolish.HackathonSpot.cs.
// Menu: SketchScape > Polish > ...   Batch: -executeMethod SketchScape.RoomPolish.PolishAllBatch
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace SketchScape
{
    public static partial class RoomPolish
    {
        internal sealed class Ctx
        {
            public string slug;
            public string genFolder;      // Assets/SketchScape/AgentRooms/<slug>_Generated
            public Transform root;        // SharedRoom_<slug>
            public Transform polish;      // root/Polish (fresh each run)
            public List<Light> keepLights = new List<Light>();
            public List<string> log = new List<string>();
        }

        const string AgentRooms = "Assets/SketchScape/AgentRooms";
        const string CacheFolder = "Assets/SketchScape/WebCache";
        const string PolishName = "Polish";
        static readonly string[] Slugs = { "bed", "hackgt_workspace", "hackathon_spot" };

        // ------------------------------------------------------------------
        // Entry points
        // ------------------------------------------------------------------

        [MenuItem("SketchScape/Polish/bed")] static void MenuBed() { PolishScene("bed"); }
        [MenuItem("SketchScape/Polish/hackgt_workspace")] static void MenuWorkspace() { PolishScene("hackgt_workspace"); }
        [MenuItem("SketchScape/Polish/hackathon_spot")] static void MenuHackathon() { PolishScene("hackathon_spot"); }
        [MenuItem("SketchScape/Polish/All three")] static void MenuAll() { PolishAll(); }

        public static void PolishAll()
        {
            foreach (var slug in Slugs) PolishScene(slug);
        }

        /// <summary>Batch-mode entry: polishes all three rooms, exits 1 on any failure.</summary>
        public static void PolishAllBatch()
        {
            try
            {
                PolishAll();
                Debug.Log("Polish: ALL DONE");
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                Debug.LogError("Polish: FAILED " + e.GetType().Name + ": " + e.Message);
                EditorApplication.Exit(1);
            }
        }

        // ------------------------------------------------------------------
        // APK with all three rooms (SceneCycler switches between them at runtime)
        // ------------------------------------------------------------------

        static readonly string[] BuildScenes =
        {
            HubBuilder.HubScenePath,
            AgentRooms + "/hackgt_workspace.unity",
            AgentRooms + "/bed.unity",
            AgentRooms + "/hackathon_spot.unity",
        };

        [MenuItem("SketchScape/Polish/Build APK (hub + three rooms)")]
        static void MenuBuild() { BuildApk(false); }

        /// <summary>Batch-mode entry: -buildTarget Android -executeMethod SketchScape.RoomPolish.BuildApkBatch</summary>
        public static void BuildApkBatch() { BuildApk(true); }

        /// <summary>Batch-mode entry: polish the three rooms, build the hub, set the Build Settings scene list. No APK.</summary>
        public static void PrepareBatch()
        {
            try
            {
                PolishAll();
                HubBuilder.BuildHub();
                SetBuildScenes();
                Debug.Log("Polish: rooms + hub done, build list set (hub first)");
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                Debug.LogError("Polish: FAILED: " + e.Message);
                EditorApplication.Exit(1);
            }
        }

        /// <summary>Batch-mode entry that does everything: polish the three rooms, build the hub, build the APK.</summary>
        public static void ShipBatch()
        {
            try
            {
                PolishAll();
                HubBuilder.BuildHub();
                Debug.Log("Polish: rooms + hub done, building APK");
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                Debug.LogError("Polish: FAILED before build: " + e.Message);
                EditorApplication.Exit(1);
                return;
            }
            BuildApk(true);
        }

        [MenuItem("SketchScape/Polish/Set Build Settings (hub + three rooms)")]
        static void SetBuildScenes()
        {
            var list = new List<EditorBuildSettingsScene>();
            foreach (var s in BuildScenes)
            {
                if (!File.Exists(s)) throw new FileNotFoundException("scene missing: " + s);
                list.Add(new EditorBuildSettingsScene(s, true));
            }
            EditorBuildSettings.scenes = list.ToArray();
            AssetDatabase.SaveAssets();
        }

        // ------------------------------------------------------------------
        // Per-room staging for the hub link-up: return doorway, the pinch-to-read letter, notes board nudges
        // ------------------------------------------------------------------

        struct Staging
        {
            public Vector3 portalPos; public float portalYaw;
            public Vector3 letterPos; public float letterYaw;
            public string heading, body;
            public Vector3? notesBoardPos; public float notesBoardYaw;
        }

        static Staging StagingFor(string slug)
        {
            switch (slug)
            {
                case "bed":
                    return new Staging
                    {
                        portalPos = new Vector3(0f, 0f, -1.55f), portalYaw = 180f,
                        letterPos = new Vector3(0.5f, -0.02f, 0.45f), letterYaw = 48f,
                        heading = "For Alice, from Bob",
                        body = "Alice,\n\nThis is the bench where we waited for the results that night. You said the blinds looked like a spreadsheet and I couldn't stop laughing.\n\nI kept the seat by the extinguisher for you.\n\n- Bob",
                    };
                case "hackgt_workspace":
                    return new Staging
                    {
                        portalPos = new Vector3(-0.5f, 0f, -1.05f), portalYaw = 180f,
                        letterPos = new Vector3(0.5f, -0.02f, 0.45f), letterYaw = 48f,
                        heading = "For Alice, from Bob",
                        body = "Alice,\n\nThe whiteboard still has our first diagram on it: boxes, arrows, and the word 'portal' circled three times.\n\nI left my backpack by the door so you'd know I'm coming back.\n\n- Bob",
                    };
                case "hackathon_spot":
                    return new Staging
                    {
                        portalPos = new Vector3(0.4f, 0f, -1.6f), portalYaw = 180f,
                        letterPos = new Vector3(0.62f, -0.02f, 0.12f), letterYaw = 79f,
                        heading = "For Bob, from Alice",
                        body = "Bob,\n\nThirty-six hours at this table. Two laptops, one working charger, and the little whiteboard that finally made the plan make sense.\n\nWe built Return here. Come sit back down.\n\n- Alice",
                        notesBoardPos = new Vector3(-1.9f, -0.02f, -1.2f), notesBoardYaw = 150f,
                    };
            }
            return new Staging();
        }

        /// <summary>The hub link-up applied to every polished room after its own staging.</summary>
        static void StageForHub(Ctx c)
        {
            var st = StagingFor(c.slug);
            DisableChild(c, "Shared Room/Account Switcher");
            if (st.notesBoardPos.HasValue)
            {
                foreach (var path in new[] { "Shared Room/Notes Board Anchor", "Shared Room/Shared Content/Notes Board" })
                {
                    var nb = c.root.Find(path);
                    if (nb == null) continue;
                    nb.position = new Vector3(st.notesBoardPos.Value.x, nb.position.y, st.notesBoardPos.Value.z);
                    nb.rotation = Quaternion.Euler(0f, st.notesBoardYaw, 0f);
                    EditorUtility.SetDirty(nb);
                }
                c.log.Add("notes board moved aside");
            }
            PortalKit.Build(c.polish, "Return Portal", st.portalPos, st.portalYaw, "Worlds Hub", HubBuilder.HubSky(),
                            new Color(0.55f, 0.80f, 1f), HubBuilder.HubSceneName, c.genFolder);
            c.log.Add("return portal at " + st.portalPos);
            FakeLetterKit.Build(c.polish, c.genFolder, st.letterPos, st.letterYaw, st.heading, st.body);
            c.log.Add("fake letter at " + st.letterPos);
            AddScreenFade(c.root.gameObject.scene);
        }

        /// <summary>OVRScreenFade on the rig's centre eye: fades in on load, and PortalTrigger fades out before loading.</summary>
        internal static void AddScreenFade(Scene scene)
        {
            OVRCameraRig rig = null;
            foreach (var go in scene.GetRootGameObjects())
            {
                rig = go.GetComponentInChildren<OVRCameraRig>(true);
                if (rig != null) break;
            }
            if (rig == null || rig.centerEyeAnchor == null) { Debug.LogWarning("Polish: no OVRCameraRig centre eye for the screen fade in " + scene.name); return; }
            var eye = rig.centerEyeAnchor.gameObject;
            var fade = eye.GetComponent<OVRScreenFade>();
            if (fade == null) fade = eye.AddComponent<OVRScreenFade>();
            fade.fadeOnStart = true;
            fade.fadeTime = 0.5f;
            fade.fadeColor = new Color(0.01f, 0.01f, 0.01f, 1f);
            EditorUtility.SetDirty(fade);
        }

        static void BuildApk(bool batch)
        {
            try
            {
                SetBuildScenes();
                EditorUserBuildSettings.androidBuildSubtarget = MobileTextureSubtarget.ASTC;
                EditorUserBuildSettings.buildAppBundle = false;
                EditorUserBuildSettings.exportAsGoogleAndroidProject = false;

                string apk = Path.GetFullPath("stupid house polished.apk");
                var opts = new BuildPlayerOptions
                {
                    scenes = BuildScenes,
                    locationPathName = apk,
                    target = BuildTarget.Android,
                    targetGroup = BuildTargetGroup.Android,
                    options = BuildOptions.None,
                };
                var report = BuildPipeline.BuildPlayer(opts);
                var sum = report.summary;
                Debug.Log("Build: " + sum.result + " " + (sum.totalSize / (1024 * 1024)) + " MB, errors " + sum.totalErrors +
                          ", " + sum.totalTime.TotalSeconds.ToString("0") + " s -> " + apk);
                if (sum.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                {
                    if (batch) EditorApplication.Exit(1);
                }
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                Debug.LogError("Build: FAILED " + e.Message);
                if (batch) EditorApplication.Exit(1);
            }
        }

        public static void PolishScene(string slug)
        {
            string path = AgentRooms + "/" + slug + ".unity";
            if (!File.Exists(path)) throw new FileNotFoundException("scene missing: " + path);
            var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
            var rootGo = FindRoot(scene, "SharedRoom_" + slug);
            if (rootGo == null) throw new Exception("room root SharedRoom_" + slug + " missing in " + path);

            var c = new Ctx { slug = slug, genFolder = AgentRooms + "/" + slug + "_Generated", root = rootGo.transform };
            RoomKitWeb.EnsureFolder(c.genFolder);
            ResetPolish(c);

            switch (slug)
            {
                case "bed": PolishBed(c); break;
                case "hackgt_workspace": PolishHackgtWorkspace(c); break;
                case "hackathon_spot": PolishHackathonSpot(c); break;
                default: throw new Exception("no polish for " + slug);
            }

            StageForHub(c);

            // Common polish.
            MarkReflective(c.root.Find("Environment/Floor"));
            TuneSplats(c);
            TuneKeyFill(c);
            SyncDirectorLights(c);

            EditorSceneManager.MarkSceneDirty(scene);
            if (!EditorSceneManager.SaveScene(scene)) throw new Exception("could not save " + path);
            AssetDatabase.SaveAssets();

            string bake = RebakeEnvironment(c);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();
            Debug.Log("Polish: " + slug + " ok (lighting=" + bake + ")\n  " + string.Join("\n  ", c.log));
        }

        static GameObject FindRoot(Scene scene, string name)
        {
            foreach (var go in scene.GetRootGameObjects())
                if (go.name == name) return go;
            return null;
        }

        /// <summary>Deletes the previous Polish group (and its Polish_* materials) and makes a fresh one.</summary>
        static void ResetPolish(Ctx c)
        {
            var old = c.root.Find(PolishName);
            if (old != null) UnityEngine.Object.DestroyImmediate(old.gameObject);
            var go = new GameObject(PolishName);
            go.transform.SetParent(c.root, false);
            c.polish = go.transform;
            c.log.Add(old != null ? "rebuilt Polish group" : "created Polish group");
        }

        // ------------------------------------------------------------------
        // Geometry
        // ------------------------------------------------------------------

        internal static Transform Group(Transform parent, string name)
        {
            var existing = parent.Find(name);
            if (existing != null) return existing;
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            return go.transform;
        }

        /// <summary>Cube primitive at a world center with a world size. Walls keep their BoxCollider (the barriers).</summary>
        internal static GameObject Box(Transform parent, string name, Vector3 center, Vector3 size, Material mat, bool collider = true, bool castShadows = false)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            go.transform.SetParent(parent, false);
            go.transform.position = center;
            go.transform.rotation = Quaternion.identity;
            go.transform.localScale = size;
            var r = go.GetComponent<Renderer>();
            r.sharedMaterial = mat;
            r.shadowCastingMode = castShadows ? ShadowCastingMode.On : ShadowCastingMode.Off;
            r.receiveShadows = true;
            if (!collider) UnityEngine.Object.DestroyImmediate(go.GetComponent<Collider>());
            MarkReflective(go.transform);
            return go;
        }

        /// <summary>Quad primitive without a collider. Its normal is -Z at identity.</summary>
        internal static GameObject QuadAt(Transform parent, string name, Vector3 center, Vector3 euler, Vector2 size, Material mat)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = name;
            UnityEngine.Object.DestroyImmediate(go.GetComponent<Collider>());
            go.transform.SetParent(parent, false);
            go.transform.position = center;
            go.transform.rotation = Quaternion.Euler(euler);
            go.transform.localScale = new Vector3(size.x, size.y, 1f);
            var r = go.GetComponent<Renderer>();
            r.sharedMaterial = mat;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = true;
            MarkReflective(go.transform);
            return go;
        }

        /// <summary>Baked reflection probes only see Reflection Probe Static objects.</summary>
        static void MarkReflective(Transform t)
        {
            if (t == null) return;
            GameObjectUtility.SetStaticEditorFlags(t.gameObject, StaticEditorFlags.ReflectionProbeStatic);
        }

        /// <summary>Standard material saved as &lt;genFolder&gt;/Polish_&lt;name&gt;.mat. Colours are sRGB as in the Inspector.</summary>
        internal static Material Mat(Ctx c, string name, Color srgb, float gloss = 0.05f, Texture2D tex = null, Vector2? tiling = null, Color? emissionSrgb = null)
        {
            string path = c.genFolder + "/Polish_" + name + ".mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat == null)
            {
                mat = new Material(Shader.Find("Standard"));
                AssetDatabase.CreateAsset(mat, path);
            }
            else mat.shader = Shader.Find("Standard");
            mat.color = srgb;
            mat.SetFloat("_Glossiness", Mathf.Clamp01(gloss));
            mat.SetFloat("_Metallic", 0f);
            mat.mainTexture = tex;
            mat.mainTextureScale = tiling ?? Vector2.one;
            if (emissionSrgb.HasValue)
            {
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", emissionSrgb.Value);
                mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            }
            else
            {
                mat.DisableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", Color.black);
                mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.EmissiveIsBlack;
            }
            EditorUtility.SetDirty(mat);
            return mat;
        }

        /// <summary>512 px seamless acoustic ceiling tile texture (4x4 tiles, light grout lines), cached in WebCache.</summary>
        internal static Texture2D CeilingTiles()
        {
            string texPath = CacheFolder + "/_ceiling_tiles_v1.png";
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
            if (tex != null) return tex;
            RoomKitWeb.EnsureFolder(CacheFolder);
            const int n = 512, tile = 128;
            var t = new Texture2D(n, n, TextureFormat.RGBA32, false);
            var rnd = new System.Random(1234);
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                {
                    int tx = x % tile, ty = y % tile;
                    bool grout = tx < 3 || ty < 3;
                    float v = grout ? 0.68f : 0.96f + (float)(rnd.NextDouble() - 0.5) * 0.06f;
                    // faint pinhole speckle like acoustic tile
                    if (!grout && rnd.NextDouble() < 0.02) v -= 0.10f;
                    t.SetPixel(x, y, new Color(v, v, v, 1f));
                }
            File.WriteAllBytes(texPath, t.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(t);
            AssetDatabase.ImportAsset(texPath, ImportAssetOptions.ForceSynchronousImport);
            var imp = AssetImporter.GetAtPath(texPath) as TextureImporter;
            if (imp != null)
            {
                imp.wrapMode = TextureWrapMode.Repeat;
                imp.mipmapEnabled = true;
                imp.sRGBTexture = true;
                imp.SaveAndReimport();
            }
            return AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
        }

        // ------------------------------------------------------------------
        // Lights / ambient / probe
        // ------------------------------------------------------------------

        internal static Light DirLight(Ctx c, string name, Vector3 euler, Color srgb, float intensity, bool softShadows)
        {
            var go = new GameObject(name);
            go.transform.SetParent(Group(c.polish, "Lights"), false);
            go.transform.rotation = Quaternion.Euler(euler);
            var l = go.AddComponent<Light>();
            l.type = LightType.Directional;
            l.color = srgb;
            l.intensity = intensity;
            l.lightmapBakeType = LightmapBakeType.Realtime;
            l.shadows = softShadows ? LightShadows.Soft : LightShadows.None;
            l.shadowStrength = 0.6f;
            l.shadowBias = 0.03f;
            l.shadowResolution = LightShadowResolution.Low;
            c.keepLights.Add(l);
            c.log.Add("light " + name + " dir " + euler + " x" + intensity);
            return l;
        }

        internal static Light PointLight(Ctx c, string name, Vector3 pos, Color srgb, float intensity, float range)
        {
            var go = new GameObject(name);
            go.transform.SetParent(Group(c.polish, "Lights"), false);
            go.transform.position = pos;
            var l = go.AddComponent<Light>();
            l.type = LightType.Point;
            l.color = srgb;
            l.intensity = intensity;
            l.range = Mathf.Max(0.1f, range);
            l.lightmapBakeType = LightmapBakeType.Realtime;
            l.shadows = LightShadows.None;
            c.keepLights.Add(l);
            c.log.Add("light " + name + " point " + pos + " x" + intensity);
            return l;
        }

        /// <summary>Tweaks an existing light found by path under the room root; null arguments are left alone.</summary>
        internal static void SetLight(Ctx c, string path, Vector3? pos, Vector3? euler, Color? srgb, float? intensity, float? range)
        {
            var t = c.root.Find(path);
            var l = t != null ? t.GetComponent<Light>() : null;
            if (l == null) { c.log.Add("WARN no light at " + path); return; }
            if (pos.HasValue) t.position = pos.Value;
            if (euler.HasValue) t.rotation = Quaternion.Euler(euler.Value);
            if (srgb.HasValue) l.color = srgb.Value;
            if (intensity.HasValue) l.intensity = intensity.Value;
            if (range.HasValue) l.range = range.Value;
            EditorUtility.SetDirty(l);
            EditorUtility.SetDirty(t);
            c.log.Add("light " + path + " tuned");
        }

        /// <summary>Trilight ambient from the scan's own colours; fog off (splats ignore fog, so fog only creates seams).</summary>
        internal static void SetAmbient(Color skySrgb, Color equatorSrgb, Color groundSrgb)
        {
            RenderSettings.fog = false;
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = skySrgb;
            RenderSettings.ambientEquatorColor = equatorSrgb;
            RenderSettings.ambientGroundColor = groundSrgb;
            RenderSettings.ambientIntensity = 1f;
        }

        internal static void FitProbe(Ctx c, Bounds interior)
        {
            var t = c.root.Find("Environment/Reflection Probe");
            var probe = t != null ? t.GetComponent<ReflectionProbe>() : null;
            if (probe == null)
            {
                var go = new GameObject("Reflection Probe");
                go.transform.SetParent(Group(c.root, "Environment"), false);
                probe = go.AddComponent<ReflectionProbe>();
                t = go.transform;
            }
            t.position = interior.center;
            probe.mode = ReflectionProbeMode.Baked;
            probe.boxProjection = true;
            probe.size = interior.size;
            probe.center = Vector3.zero;
            probe.resolution = 128;
            probe.hdr = true;
            EditorUtility.SetDirty(probe);
            c.log.Add("probe " + interior.center + " size " + interior.size + " box projection");
        }

        internal static void ShrinkTeleportFloor(Ctx c, Bounds interior, float margin = 0.3f)
        {
            var t = c.root.Find("Environment/Teleport Floor");
            var box = t != null ? t.GetComponent<BoxCollider>() : null;
            if (box == null) { c.log.Add("WARN no Teleport Floor"); return; }
            t.position = new Vector3(interior.center.x, -0.07f, interior.center.z);
            box.center = Vector3.zero;
            box.size = new Vector3(Mathf.Max(1f, interior.size.x - 2f * margin), 0.1f, Mathf.Max(1f, interior.size.z - 2f * margin));
            EditorUtility.SetDirty(box);
            c.log.Add("teleport floor " + box.size.x.ToString("0.0") + " x " + box.size.z.ToString("0.0"));
        }

        internal static void MoveHotspot(Ctx c, int index, Vector3 pos)
        {
            var t = c.root.Find("TeleportHotspots/TeleportHotspot_" + index);
            if (t == null) { c.log.Add("WARN no TeleportHotspot_" + index); return; }
            t.position = pos;
            EditorUtility.SetDirty(t);
            c.log.Add("hotspot " + index + " -> " + pos);
        }

        internal static void DisableChild(Ctx c, string path)
        {
            var t = c.root.Find(path);
            if (t == null) { c.log.Add("WARN no child " + path); return; }
            t.gameObject.SetActive(false);
            EditorUtility.SetDirty(t.gameObject);
            c.log.Add("disabled " + path);
        }

        // ------------------------------------------------------------------
        // Props
        // ------------------------------------------------------------------

        internal static void SetWorldY(Transform t, float y)
        {
            if (t == null) return;
            var p = t.position;
            p.y = y;
            t.position = p;
            EditorUtility.SetDirty(t);
        }

        static Bounds WorldBounds(Transform t, BoxCollider box)
        {
            var b = new Bounds(box.center, box.size);
            var m = t.localToWorldMatrix;
            var min = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
            var max = new Vector3(float.MinValue, float.MinValue, float.MinValue);
            for (int i = 0; i < 8; i++)
            {
                var corner = new Vector3((i & 1) == 0 ? b.min.x : b.max.x, (i & 2) == 0 ? b.min.y : b.max.y, (i & 4) == 0 ? b.min.z : b.max.z);
                var w = m.MultiplyPoint3x4(corner);
                min = Vector3.Min(min, w);
                max = Vector3.Max(max, w);
            }
            var r = new Bounds();
            r.SetMinMax(min, max);
            return r;
        }

        /// <summary>Moves a prop root straight down/up so the bottom of its BoxCollider sits on floorY.</summary>
        internal static void RestOnFloor(Transform objRoot, float floorY = 0f)
        {
            if (objRoot == null) return;
            var box = objRoot.GetComponent<BoxCollider>();
            if (box == null) return;
            var wb = WorldBounds(objRoot, box);
            float dy = floorY - wb.min.y;
            if (Mathf.Abs(dy) < 0.001f) return;
            objRoot.position += new Vector3(0f, dy, 0f);
            EditorUtility.SetDirty(objRoot);
        }

        /// <summary>RoomKit's contact-shadow recipe: a soft dark quad under a prop that touches the floor.</summary>
        internal static void EnsureContactShadow(Ctx c, Transform objRoot, float floorY)
        {
            if (objRoot == null) return;
            if (objRoot.Find("Contact Shadow") != null) return;
            var box = objRoot.GetComponent<BoxCollider>();
            if (box == null) { c.log.Add("no collider for contact shadow on " + objRoot.name); return; }
            var world = WorldBounds(objRoot, box);
            if (world.min.y - floorY > 0.06f) { c.log.Add(objRoot.name + " floats " + (world.min.y - floorY).ToString("0.00") + " m, no contact shadow"); return; }
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Contact Shadow";
            UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
            quad.transform.SetParent(objRoot, true);
            quad.transform.position = new Vector3(world.center.x, floorY + 0.004f, world.center.z);
            bool yawOnly = Vector3.Dot(objRoot.up, Vector3.up) > 0.999f;
            float fx = yawOnly ? box.size.x : world.size.x;
            float fz = yawOnly ? box.size.z : world.size.z;
            quad.transform.rotation = Quaternion.Euler(90f, yawOnly ? objRoot.eulerAngles.y : 0f, 0f);
            float sx = Mathf.Max(0.08f, fx * 1.6f + 0.06f), sz = Mathf.Max(0.08f, fz * 1.6f + 0.06f);
            quad.transform.localScale = new Vector3(sx, sz, 1f);
            var r = quad.GetComponent<Renderer>();
            r.sharedMaterial = ContactShadowMaterial(c);
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
            c.log.Add("contact shadow added under " + objRoot.name);
        }

        static Material ContactShadowMaterial(Ctx c)
        {
            string matPath = c.genFolder + "/ContactShadow.mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
            if (mat != null) return mat;
            var shader = Shader.Find("SketchScape/ContactShadow");
            mat = new Material(shader != null ? shader : Shader.Find("Sprites/Default"));
            mat.mainTexture = RoomKit.RadialTexture("_contact_shadow_v4", 1.3f, 0.25f);
            mat.SetFloat("_Strength", 0.72f);
            AssetDatabase.CreateAsset(mat, matPath);
            return mat;
        }

        // ------------------------------------------------------------------
        // Common tuning
        // ------------------------------------------------------------------

        /// <summary>
        /// Splats must sort every frame. With SortEveryNFrames the package still recomputes depth keys and runs the
        /// global k-way merge every frame (GsplatSorter.DispatchSort), so on the frames between sorts the merge combines
        /// fresh depths with stale per-renderer orders and the room flickers like static in VR.
        /// </summary>
        static void TuneSplats(Ctx c)
        {
            int n = 0;
            foreach (var r in c.root.GetComponentsInChildren<Gsplat.GsplatRenderer>(true))
            {
                r.SortMode = Gsplat.GsplatRenderer.GsplatSortMode.Always;
                r.SortRefreshRate = 1;
                EditorUtility.SetDirty(r);
                n++;
            }
            c.log.Add("splat renderers tuned: " + n);
        }

        /// <summary>Key light: soft, low-res, gentler shadows. Fill: vertex only (Android allows 2 pixel lights).</summary>
        static void TuneKeyFill(Ctx c)
        {
            foreach (var l in c.root.GetComponentsInChildren<Light>(true))
            {
                if (l.type == LightType.Directional && l.shadows != LightShadows.None)
                {
                    l.shadows = LightShadows.Soft;
                    l.shadowStrength = 0.6f;
                    l.shadowBias = 0.03f;
                    l.shadowResolution = LightShadowResolution.Low;
                    EditorUtility.SetDirty(l);
                }
                if (l.name == "Fill Light")
                {
                    l.renderMode = LightRenderMode.ForceVertex;
                    l.shadows = LightShadows.None;
                    EditorUtility.SetDirty(l);
                }
            }
        }

        /// <summary>RoomDirector fades its light list in from zero: keep it in step with the lights that are actually on.</summary>
        static void SyncDirectorLights(Ctx c)
        {
            var d = c.root.GetComponent<RoomDirector>();
            if (d == null) { c.log.Add("WARN no RoomDirector"); return; }
            var lights = new List<Light>();
            foreach (var l in c.root.GetComponentsInChildren<Light>(false))
                if (l.enabled && l.gameObject.activeInHierarchy) lights.Add(l);
            d.fadeLights = lights.ToArray();
            EditorUtility.SetDirty(d);
            c.log.Add("director fades " + lights.Count + " lights");
        }

        /// <summary>Same recipe as RoomKit.Bake: no GI, just the ambient probe and the reflection probe.</summary>
        static string RebakeEnvironment(Ctx c)
        {
            try
            {
                string settingsPath = c.genFolder + "/Lighting.lighting";
                var settings = AssetDatabase.LoadAssetAtPath<LightingSettings>(settingsPath);
                if (settings == null)
                {
                    settings = new LightingSettings { bakedGI = false, realtimeGI = false };
                    AssetDatabase.CreateAsset(settings, settingsPath);
                }
                settings.bakedGI = false;
                settings.realtimeGI = false;
                Lightmapping.lightingSettings = settings;
                bool ok = Lightmapping.Bake();
                DynamicGI.UpdateEnvironment();
                return ok ? "baked" : "unbaked";
            }
            catch (Exception e)
            {
                Debug.LogWarning("Polish: bake failed for " + c.slug + ": " + e.Message);
                return "unbaked";
            }
        }
    }
}
