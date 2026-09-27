// SketchScape HubBuilder — the "Worlds Hub": a small dusk plaza with one glowing doorway per polished room.
// Walk through a doorway (PortalTrigger) to load that room; every room has a matching doorway back.
//
// The hub is generated from a copy of bed.unity so it inherits the finished Meta rig (camera rig, interaction rig,
// locomotor, hand/controller visuals) without going through the Meta MCP handlers; the room content is deleted and
// only the teleport hotspots + teleport floor are kept and re-laid. Fully regenerated on every run.
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace SketchScape
{
    internal static class HubBuilder
    {
        internal const string HubFolder = "Assets/SketchScape/Hub";
        internal const string HubScenePath = HubFolder + "/WorldsHub.unity";
        internal const string HubSceneName = "WorldsHub";
        internal const string HubSkyPath = HubFolder + "/return-sky-dusk-hub.jpg";
        const string SourceScene = "Assets/SketchScape/AgentRooms/bed.unity";

        internal struct Destination
        {
            public string slug, label, hdr;
            public Color rim;
            public Destination(string slug, string label, string hdr, Color rim) { this.slug = slug; this.label = label; this.hdr = hdr; this.rim = rim; }
        }

        internal static readonly Destination[] Destinations =
        {
            new Destination("bed", "Bench by the Window", "Assets/SketchScape/WebCache/dc654f4399f58713.hdr", new Color(0.25f, 0.85f, 0.90f)),
            new Destination("hackathon_spot", "Hackathon Table", "Assets/SketchScape/WebCache/c5e38171ceca8839.hdr", new Color(1.00f, 0.70f, 0.30f)),
            new Destination("hackgt_workspace", "Whiteboard Room", "Assets/SketchScape/WebCache/9c740be5148ce00b.hdr", new Color(0.70f, 0.55f, 1.00f)),
        };

        [MenuItem("SketchScape/Polish/Build Worlds Hub")]
        static void Menu() { BuildHub(); }

        internal static Texture2D HubSky()
        {
            return AssetDatabase.LoadAssetAtPath<Texture2D>(HubSkyPath);
        }

        public static void BuildHub()
        {
            RoomKitWeb.EnsureFolder(HubFolder);
            if (!File.Exists(SourceScene)) throw new FileNotFoundException("source scene missing: " + SourceScene);
            if (File.Exists(HubScenePath)) AssetDatabase.DeleteAsset(HubScenePath);
            if (!AssetDatabase.CopyAsset(SourceScene, HubScenePath)) throw new System.Exception("could not copy " + SourceScene + " to " + HubScenePath);
            AssetDatabase.Refresh();

            var scene = EditorSceneManager.OpenScene(HubScenePath, OpenSceneMode.Single);
            GameObject roomRoot = null;
            foreach (var go in scene.GetRootGameObjects())
                if (go.name == "SharedRoom_bed") { roomRoot = go; break; }
            if (roomRoot == null) throw new System.Exception("SharedRoom_bed root missing in the copied scene");

            var hub = new GameObject(HubSceneName).transform;

            // Keep the locomotion pieces Finalize built (Meta teleport hotspots live under the markers).
            var hotspots = roomRoot.transform.Find("TeleportHotspots");
            if (hotspots != null) hotspots.SetParent(hub, true);
            var tfloor = roomRoot.transform.Find("Environment/Teleport Floor");
            if (tfloor != null) tfloor.SetParent(hub, true);
            Object.DestroyImmediate(roomRoot);

            // Sky, ambient, no fog.
            var skyTex = HubSky();
            var skyMat = LoadOrCreate(HubFolder + "/HubSky.mat", Shader.Find("Skybox/Panoramic"));
            skyMat.mainTexture = skyTex;
            if (skyMat.HasProperty("_Exposure")) skyMat.SetFloat("_Exposure", 1.05f);
            if (skyMat.HasProperty("_Rotation")) skyMat.SetFloat("_Rotation", 0f);
            EditorUtility.SetDirty(skyMat);
            RenderSettings.skybox = skyMat;
            RenderSettings.ambientMode = AmbientMode.Skybox;
            RenderSettings.ambientIntensity = 1f;
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
            RenderSettings.fog = false;
            Lightmapping.lightingDataAsset = null;

            // Floor: a dark, slightly glossy plaza.
            var floorMat = LoadOrCreate(HubFolder + "/HubFloor.mat", Shader.Find("Standard"));
            floorMat.color = new Color(0.07f, 0.08f, 0.12f);
            floorMat.SetFloat("_Metallic", 0.25f);
            floorMat.SetFloat("_Glossiness", 0.6f);
            EditorUtility.SetDirty(floorMat);
            var floor = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            floor.name = "Plaza Floor";
            Object.DestroyImmediate(floor.GetComponent<Collider>());
            floor.transform.SetParent(hub, false);
            floor.transform.position = new Vector3(0f, -0.02f, 1.5f);
            floor.transform.localScale = new Vector3(16f, 0.02f, 16f);
            var fr = floor.GetComponent<Renderer>();
            fr.sharedMaterial = floorMat;
            fr.shadowCastingMode = ShadowCastingMode.Off;
            fr.receiveShadows = true;
            GameObjectUtility.SetStaticEditorFlags(floor, StaticEditorFlags.ReflectionProbeStatic);

            // A soft ring of ground light under the spawn so the player is not standing in the dark.
            var spawnLight = new GameObject("Spawn Light").AddComponent<Light>();
            spawnLight.transform.SetParent(hub, false);
            spawnLight.transform.position = new Vector3(0f, 2.6f, 0.8f);
            spawnLight.type = LightType.Point;
            spawnLight.color = new Color(0.95f, 0.85f, 0.75f);
            spawnLight.intensity = 0.9f;
            spawnLight.range = 6f;
            spawnLight.lightmapBakeType = LightmapBakeType.Realtime;

            var key = new GameObject("Key Light").AddComponent<Light>();
            key.transform.SetParent(hub, false);
            key.transform.rotation = Quaternion.Euler(48f, 205f, 0f);
            key.type = LightType.Directional;
            key.color = new Color(1f, 0.78f, 0.62f);
            key.intensity = 0.55f;
            key.shadows = LightShadows.Soft;
            key.shadowStrength = 0.5f;
            key.shadowResolution = LightShadowResolution.Low;
            key.lightmapBakeType = LightmapBakeType.Realtime;

            // Teleport floor + hotspots re-laid for the plaza.
            if (tfloor != null)
            {
                tfloor.position = new Vector3(0f, -0.07f, 1.4f);
                var box = tfloor.GetComponent<BoxCollider>();
                if (box != null) { box.center = Vector3.zero; box.size = new Vector3(6.4f, 0.1f, 6.8f); }
            }
            var hotspotPositions = new[]
            {
                new Vector3(0f, 0f, 0f), new Vector3(-1.3f, 0f, 2.0f), new Vector3(1.3f, 0f, 2.0f),
                new Vector3(-2.3f, 0f, 0.4f), new Vector3(2.3f, 0f, 0.4f),
            };
            if (hotspots != null)
                for (int i = 0; i < hotspots.childCount && i < hotspotPositions.Length; i++)
                    hotspots.GetChild(i).position = hotspotPositions[i];

            // Doorways on an arc in front of the spawn, each turned to face it.
            const float radius = 3.2f;
            var arcCenter = new Vector3(0f, 0f, 0.6f);
            float[] angles = { -34f, 0f, 34f };
            for (int i = 0; i < Destinations.Length; i++)
            {
                var d = Destinations[i];
                float a = angles[i] * Mathf.Deg2Rad;
                var pos = arcCenter + new Vector3(Mathf.Sin(a) * radius, 0f, Mathf.Cos(a) * radius);
                // PortalKit: at yaw 0 the doorway faces -Z. Face the spawn: yaw = atan2(-dx, dz) of (portal - spawn).
                float yaw = Mathf.Atan2(-pos.x, pos.z) * Mathf.Rad2Deg;
                var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(d.hdr);
                PortalKit.Build(hub, "Portal " + d.slug, pos, yaw, d.label, tex, d.rim, d.slug, HubFolder);
            }

            RoomPolish.AddScreenFade(scene);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();

            // Bake the ambient probe from the new sky (no GI, no probes).
            string lightingPath = HubFolder + "/Hub.lighting";
            var ls = AssetDatabase.LoadAssetAtPath<LightingSettings>(lightingPath);
            if (ls == null) { ls = new LightingSettings { bakedGI = false, realtimeGI = false }; AssetDatabase.CreateAsset(ls, lightingPath); }
            Lightmapping.lightingSettings = ls;
            bool baked = Lightmapping.Bake();
            DynamicGI.UpdateEnvironment();
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();
            Debug.Log("Polish: hub ok (" + (baked ? "baked" : "unbaked") + ") " + HubScenePath);
        }

        static Material LoadOrCreate(string path, Shader shader)
        {
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (m == null) { m = new Material(shader); AssetDatabase.CreateAsset(m, path); }
            else m.shader = shader;
            return m;
        }
    }
}
