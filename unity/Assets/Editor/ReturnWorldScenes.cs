using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Gsplat;
using Return.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Builds the per-room world scenes that hub portals open. Each world is its own scene under Assets/Scenes/Worlds with a
/// WorldSceneRoot (children authored in viewer space), listed in Build Settings and mapped roomId -> scene in the hub's
/// HubApp.worldMap. A world is described by a layout JSON at Assets/Worlds/Layouts/{roomId}.json (props from
/// Assets/Worlds/Props) and rebuilt from it, so hand edits to a world scene are overwritten; edit the layout instead.
/// Agents use the Return.* MCP tools (ReturnWorldMcpTools); humans use Tools/Return/Worlds.
/// Batch: Unity -batchmode -quit -projectPath unity -executeMethod ReturnWorldScenes.BuildAllFromLayouts
/// </summary>
public static class ReturnWorldScenes
{
    public const string WorldsFolder = "Assets/Scenes/Worlds";
    public const string HubScenePath = "Assets/Scenes/ReturnHub.unity";
    public const string LayoutsFolder = "Assets/Worlds/Layouts";
    public const string PropsFolder = "Assets/Worlds/Props";
    static readonly string[] PropExtensions = { ".prefab", ".glb", ".gltf", ".fbx", ".ply" };

    /// <summary>Per-kit factor that brings a kit to real-world metres (Kenney nature/furniture kits are authored small).
    /// Props() reports sizes and Place() applies scale with this already multiplied in. Add an entry when you add a kit.</summary>
    public static readonly Dictionary<string, float> KitScale = new Dictionary<string, float>
    {
        { "nature-kit", 4f },
        { "furniture-kit", 2f },
        { "survival-kit", 4f },
    };

    static float KitScaleOf(string path)
    {
        if (!path.StartsWith(PropsFolder + "/")) return 1f;
        var kit = path.Substring(PropsFolder.Length + 1).Split('/')[0];
        return KitScale.TryGetValue(kit, out var s) ? s : 1f;
    }

    [Serializable] public class WorldLayout
    {
        public string roomId, sceneName;
        public bool sky = true;
        public List<Placement> props = new List<Placement>();
    }

    /// <summary>prop: id under Assets/Worlds/Props without extension (e.g. "nature-kit/tree_oak"), an Assets/ path, or a
    /// built-in primitive/plane|cube|cylinder|sphere sized by `size` [x, y, z] metres (ground, water, walls, blockouts).
    /// pos: [x, y, z] metres in viewer space, where y is the height the model's lowest point rests on. yaw: degrees about +Y.
    /// scale: multiplier on the real-world size Return.ListProps reports. color: optional "#rrggbb"; on a model it replaces
    /// the base color of every material, on a primitive it is the color (default grey).</summary>
    [Serializable] public class Placement { public string prop, name, color; public float[] pos = new float[3], size; public float yaw, scale = 1f; }

    public class BuildResult { public string roomId, scenePath; public int placed; public List<string> warnings = new List<string>(); }

    [MenuItem("Tools/Return/Worlds/Build All From Layouts")]
    public static void BuildAllFromLayouts()
    {
        if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
        var setup = Application.isBatchMode ? null : EditorSceneManager.GetSceneManagerSetup();
        foreach (var path in LayoutPaths())
        {
            var r = BuildFromLayout(ParseLayout(File.ReadAllText(path)));
            Debug.Log("ReturnWorldScenes: " + r.roomId + " -> " + r.scenePath + ", " + r.placed + " props" + string.Concat(r.warnings.Select(w => "\n  " + w)));
        }
        if (setup != null && setup.Length > 0) EditorSceneManager.RestoreSceneManagerSetup(setup);
    }

    public static IEnumerable<string> LayoutPaths() =>
        Directory.Exists(LayoutsFolder) ? Directory.GetFiles(LayoutsFolder, "*.json").OrderBy(p => p) : Enumerable.Empty<string>();

    public static string LayoutPath(string roomId) => LayoutsFolder + "/" + roomId + ".json";

    public static WorldLayout ParseLayout(string json)
    {
        var layout = JsonUtility.FromJson<WorldLayout>(json);
        if (layout == null || string.IsNullOrWhiteSpace(layout.roomId) || string.IsNullOrWhiteSpace(layout.sceneName))
            throw new ArgumentException("layout needs roomId and sceneName.");
        return layout;
    }

    /// <summary>Recreates the room's world scene from the layout. Bad props are skipped and reported, not fatal.</summary>
    public static BuildResult BuildFromLayout(WorldLayout layout)
    {
        var root = CreateWorldScene(layout.roomId, layout.sceneName);
        var result = new BuildResult { roomId = layout.roomId, scenePath = root.gameObject.scene.path };
        root.buildSky = layout.sky;
        for (int i = 0; i < layout.props.Count; i++)
        {
            try { Place(root, layout.props[i]); result.placed++; }
            catch (Exception e) { result.warnings.Add("props[" + i + "] " + layout.props[i].prop + ": " + e.Message); }
        }
        SaveWorldScene(root);
        return result;
    }

    /// <summary>New empty world scene with a WorldSceneRoot at the origin, registered in Build Settings and the hub's worldMap.
    /// Replaces an existing scene of the same name. The scene is open (single) when this returns.</summary>
    public static WorldSceneRoot CreateWorldScene(string roomId, string sceneName)
    {
        if (string.IsNullOrWhiteSpace(roomId) || string.IsNullOrWhiteSpace(sceneName)) throw new ArgumentException("roomId and sceneName are required.");
        string path = WorldsFolder + "/" + sceneName + ".unity";
        if (!AssetDatabase.IsValidFolder(WorldsFolder)) AssetDatabase.CreateFolder("Assets/Scenes", "Worlds");

        RegisterInHub(roomId, sceneName);
        AddToBuildSettings(path);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var root = new GameObject("World Root").AddComponent<WorldSceneRoot>();
        EditorSceneManager.SaveScene(scene, path);
        return root;
    }

    public static void SaveWorldScene(WorldSceneRoot root)
    {
        EditorSceneManager.MarkSceneDirty(root.gameObject.scene);
        EditorSceneManager.SaveScene(root.gameObject.scene);
    }

    public static GameObject Place(WorldSceneRoot root, Placement p)
    {
        if (p.pos == null || p.pos.Length != 3) throw new ArgumentException("pos must be [x, y, z].");
        if (p.prop != null && p.prop.StartsWith(PrimitivePrefix)) return PlacePrimitive(root, p);
        var path = ResolveProp(p.prop) ?? throw new FileNotFoundException("no such prop; list them with Return.ListProps.");
        float scale = (p.scale > 0 ? p.scale : 1f) * KitScaleOf(path);

        GameObject go; Bounds? local;
        if (path.EndsWith(".ply", StringComparison.OrdinalIgnoreCase))
        {
            var asset = AssetDatabase.LoadAssetAtPath<GsplatAsset>(path) ?? throw new InvalidDataException("did not import as a GsplatAsset.");
            go = new GameObject();
            go.AddComponent<GsplatRenderer>().GsplatAsset = asset;
            var collider = go.AddComponent<BoxCollider>();
            collider.center = asset.Bounds.center;
            collider.size = asset.Bounds.size;
            local = asset.Bounds;
        }
        else
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path) ?? throw new InvalidDataException("did not import as a model.");
            go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            local = MeshBounds(prefab);
        }

        go.name = string.IsNullOrEmpty(p.name) ? Path.GetFileNameWithoutExtension(path) : p.name;
        Pose(root, go, p, Vector3.one * scale, local);
        if (!string.IsNullOrEmpty(p.color)) Tint(go, p.color);
        return go;
    }

    const string PrimitivePrefix = "primitive/";

    static GameObject PlacePrimitive(WorldSceneRoot root, Placement p)
    {
        var kind = p.prop.Substring(PrimitivePrefix.Length);
        if (!Enum.TryParse<PrimitiveType>(kind, true, out var type) || type == PrimitiveType.Capsule || type == PrimitiveType.Quad)
            throw new ArgumentException("primitive must be plane, cube, cylinder or sphere.");
        var size = p.size != null && p.size.Length == 3 ? new Vector3(p.size[0], p.size[1], p.size[2]) : Vector3.one;
        var go = GameObject.CreatePrimitive(type);
        go.name = string.IsNullOrEmpty(p.name) ? kind : p.name;
        var mesh = go.GetComponent<MeshFilter>().sharedMesh.bounds.size; // plane is 10 x 0 x 10, cylinder 1 x 2 x 1
        // Planes keep y = 1: their mesh is flat, and a zero y scale collapses the normals so the sun stops lighting them.
        var scale = new Vector3(size.x / mesh.x, type == PrimitiveType.Plane || size.y <= 0f ? 1f : size.y / mesh.y, size.z / mesh.z) * (p.scale > 0 ? p.scale : 1f);
        Pose(root, go, p, scale, go.GetComponent<MeshFilter>().sharedMesh.bounds);
        var mat = new Material(Shader.Find("Universal Render Pipeline/Lit")) { name = go.name };
        mat.color = string.IsNullOrEmpty(p.color) ? Color.gray : ColorUtility.TryParseHtmlString(p.color, out var c) ? c : throw new ArgumentException("color '" + p.color + "' is not #rrggbb.");
        mat.SetFloat("_Smoothness", 0.15f);
        go.GetComponent<MeshRenderer>().sharedMaterial = mat;
        return go;
    }

    /// <summary>Parent, yaw, scale, and rest the model's lowest point on pos.y (yaw never changes the bottom).</summary>
    static void Pose(WorldSceneRoot root, GameObject go, Placement p, Vector3 scale, Bounds? local)
    {
        go.transform.SetParent(root.transform, false);
        go.transform.localRotation = Quaternion.Euler(0f, p.yaw, 0f);
        go.transform.localScale = scale;
        float lift = local.HasValue ? -local.Value.min.y * scale.y : 0f;
        go.transform.localPosition = new Vector3(p.pos[0], p.pos[1] + lift, p.pos[2]);
    }

    static void Tint(GameObject go, string html)
    {
        if (!ColorUtility.TryParseHtmlString(html, out var c)) throw new ArgumentException("color '" + html + "' is not #rrggbb.");
        foreach (var r in go.GetComponentsInChildren<Renderer>())
            r.sharedMaterials = r.sharedMaterials.Select(m =>
            {
                if (m == null) return null;
                var t = new Material(m) { name = m.name + " (tinted)" };
                if (t.HasProperty("baseColorFactor")) t.SetColor("baseColorFactor", c); // glTFast
                else t.color = c;
                return t;
            }).ToArray();
    }

    /// <summary>Asset path for a prop id ("nature-kit/tree_oak") or a literal Assets/ path; null if missing.</summary>
    public static string ResolveProp(string id)
    {
        if (string.IsNullOrWhiteSpace(id)) return null;
        if (id.StartsWith("Assets/")) return File.Exists(id) ? id : null;
        return PropExtensions.Select(ext => PropsFolder + "/" + id + ext).FirstOrDefault(File.Exists);
    }

    /// <summary>Every prop id under Assets/Worlds/Props with its size in metres at scale 1 (x width, y height, z depth).</summary>
    public static IEnumerable<(string id, Vector3 size)> Props()
    {
        var ids = Directory.GetFiles(PropsFolder, "*", SearchOption.AllDirectories)
            .Where(f => PropExtensions.Contains(Path.GetExtension(f).ToLowerInvariant()))
            .Select(f => f.Replace('\\', '/'))
            .OrderBy(f => f);
        foreach (var path in ids)
        {
            var id = path.Substring(PropsFolder.Length + 1);
            id = id.Substring(0, id.Length - Path.GetExtension(id).Length);
            Bounds? b = path.EndsWith(".ply", StringComparison.OrdinalIgnoreCase)
                ? AssetDatabase.LoadAssetAtPath<GsplatAsset>(path)?.Bounds
                : MeshBounds(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            yield return (id, (b?.size ?? Vector3.zero) * KitScaleOf(path));
        }
    }

    /// <summary>Mesh bounds in the model root's own space (ignores the root's transform).</summary>
    static Bounds? MeshBounds(GameObject model)
    {
        if (model == null) return null;
        Bounds? b = null;
        var toRoot = model.transform.worldToLocalMatrix;
        void Add(Transform t, Mesh mesh)
        {
            if (mesh == null) return;
            var m = toRoot * t.localToWorldMatrix; var mb = mesh.bounds;
            for (int i = 0; i < 8; i++)
            {
                var corner = m.MultiplyPoint3x4(mb.center + Vector3.Scale(mb.extents, new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1)));
                if (b.HasValue) { var e = b.Value; e.Encapsulate(corner); b = e; } else b = new Bounds(corner, Vector3.zero);
            }
        }
        foreach (var mf in model.GetComponentsInChildren<MeshFilter>(true)) Add(mf.transform, mf.sharedMesh);
        foreach (var sm in model.GetComponentsInChildren<SkinnedMeshRenderer>(true)) Add(sm.transform, sm.sharedMesh);
        return b;
    }

    static void AddToBuildSettings(string path)
    {
        var scenes = EditorBuildSettings.scenes.ToList();
        var existing = scenes.FindIndex(s => s.path == path);
        if (existing >= 0) { if (scenes[existing].enabled) return; scenes.RemoveAt(existing); }
        scenes.Add(new EditorBuildSettingsScene(path, true));
        EditorBuildSettings.scenes = scenes.ToArray();
    }

    static void RegisterInHub(string roomId, string sceneName)
    {
        var hub = EditorSceneManager.OpenScene(HubScenePath, OpenSceneMode.Single);
        var app = hub.GetRootGameObjects().SelectMany(g => g.GetComponentsInChildren<HubApp>(true)).FirstOrDefault();
        if (app == null) throw new InvalidOperationException(HubScenePath + " has no HubApp to register " + roomId + " in.");

        var entry = app.worldMap.FirstOrDefault(e => e.roomId == roomId);
        if (entry != null && entry.sceneName == sceneName) return;
        Undo.RecordObject(app, "Map " + roomId + " world");
        if (entry != null) entry.sceneName = sceneName;
        else app.worldMap.Add(new WorldEntry { roomId = roomId, sceneName = sceneName });
        EditorUtility.SetDirty(app);
        EditorSceneManager.SaveScene(hub);
    }
}
