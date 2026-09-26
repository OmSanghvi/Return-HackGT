using System;
using System.IO;
using System.Linq;
using Return.Data;
using Return.UI;
using Unity.AI.MCP.Editor.Helpers;
using Unity.AI.MCP.Editor.ToolRegistry;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Unity MCP tools for agents building placeholder room worlds. Loop: Return.ListWorldRooms -> Return.ListProps ->
/// Return.ApplyWorldLayout -> Return.CaptureWorld (look at the PNG) -> adjust the layout -> apply again.
/// See .claude/skills/world-scene-authoring/SKILL.md for the layout format and conventions.
/// </summary>
public static class ReturnWorldMcpTools
{
    public class ListPropsParams
    {
        [McpDescription("Only props whose id contains this text, e.g. 'tree', 'chair' or 'pirate-kit/'. Empty lists all (~620).")]
        public string Filter { get; set; } = "";
    }

    public class ApplyParams
    {
        [McpDescription("Room id, e.g. 'lake-house'.", Required = true)]
        public string RoomId { get; set; } = "";

        [McpDescription("Full layout JSON to save to Assets/Worlds/Layouts/{roomId}.json before building. Omit to rebuild from the saved file.")]
        public string LayoutJson { get; set; } = "";
    }

    public class CaptureParams
    {
        [McpDescription("Room id, e.g. 'lake-house'.", Required = true)]
        public string RoomId { get; set; } = "";

        [McpDescription("front | left | right | back (from the viewer's arrival spot, eye height 1.6 m) or top (orthographic plan, +Z up the image).")]
        public string View { get; set; } = "front";
    }

    [McpTool("Return.ListWorldRooms", "List the hub's rooms (id, title, place, date, sky, phase) and whether each has a world layout yet. Ready rooms are the ones with portals.", EnabledByDefault = true, Groups = new[] { "scene" })]
    public static object ListWorldRooms()
    {
        var rooms = RoomLogic.Seed(0).Select(r =>
        {
            var path = ReturnWorldScenes.LayoutPath(r.id);
            return new { r.id, r.title, r.place, r.date, sky = r.scene.ToString(), phase = r.phase.ToString(), layoutPath = path, hasLayout = File.Exists(path) };
        }).ToList();
        return Response.Success(rooms.Count + " rooms.", rooms);
    }

    [McpTool("Return.ListProps", "List placeholder props usable in a world layout: id (use as 'prop') and real-world size [x, y, z] in metres at scale 1. Also always available: primitive/plane|cube|cylinder|sphere, sized by 'size' [x, y, z] metres and colored by 'color'.", EnabledByDefault = true, Groups = new[] { "scene" })]
    public static object ListProps(ListPropsParams p)
    {
        var filter = p?.Filter ?? "";
        var props = ReturnWorldScenes.Props()
            .Where(x => x.id.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
            .Select(x => new { x.id, size = new[] { R(x.size.x), R(x.size.y), R(x.size.z) } })
            .ToList();
        return Response.Success(props.Count + " props.", props);
    }

    [McpTool("Return.ApplyWorldLayout", "Save a world layout JSON (optional) and rebuild that room's world scene from it. Returns props placed and per-prop warnings.", EnabledByDefault = true, Groups = new[] { "scene" })]
    public static object ApplyWorldLayout(ApplyParams p)
    {
        if (string.IsNullOrWhiteSpace(p?.RoomId)) return Response.Error("roomId is required.");
        if (DirtyScene() is string dirty) return Response.Error("Scene '" + dirty + "' has unsaved changes; save or discard them first.");
        try
        {
            var path = ReturnWorldScenes.LayoutPath(p.RoomId);
            var json = string.IsNullOrWhiteSpace(p.LayoutJson) ? (File.Exists(path) ? File.ReadAllText(path) : null) : p.LayoutJson;
            if (json == null) return Response.Error("No layout at " + path + "; pass layoutJson.");
            var layout = ReturnWorldScenes.ParseLayout(json);
            if (layout.roomId != p.RoomId) return Response.Error("layout.roomId '" + layout.roomId + "' does not match roomId '" + p.RoomId + "'.");
            if (!string.IsNullOrWhiteSpace(p.LayoutJson))
            {
                Directory.CreateDirectory(ReturnWorldScenes.LayoutsFolder);
                File.WriteAllText(path, JsonUtility.ToJson(layout, true));
                AssetDatabase.ImportAsset(path);
            }
            var r = ReturnWorldScenes.BuildFromLayout(layout);
            return Response.Success("Built " + r.scenePath + " with " + r.placed + "/" + layout.props.Count + " props.", new { r.scenePath, r.placed, r.warnings, layoutPath = path });
        }
        catch (Exception e) { return Response.Error(e.Message); }
    }

    [McpTool("Return.CaptureWorld", "Render a room's world scene to a PNG and return its absolute path; open it to check the layout. The painted sky is not drawn (it is built at runtime).", EnabledByDefault = true, Groups = new[] { "scene" })]
    public static object CaptureWorld(CaptureParams p)
    {
        if (string.IsNullOrWhiteSpace(p?.RoomId)) return Response.Error("roomId is required.");
        if (DirtyScene() is string dirty) return Response.Error("Scene '" + dirty + "' has unsaved changes; save or discard them first.");
        var layoutPath = ReturnWorldScenes.LayoutPath(p.RoomId);
        if (!File.Exists(layoutPath)) return Response.Error("No layout for " + p.RoomId + "; apply one first.");
        var scenePath = ReturnWorldScenes.WorldsFolder + "/" + ReturnWorldScenes.ParseLayout(File.ReadAllText(layoutPath)).sceneName + ".unity";
        if (!File.Exists(scenePath)) return Response.Error(scenePath + " does not exist; apply the layout first.");

        var scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
        var root = scene.GetRootGameObjects().Select(g => g.GetComponentInChildren<WorldSceneRoot>(true)).FirstOrDefault(r => r != null);
        var view = (p.View ?? "front").ToLowerInvariant();
        var sun = new GameObject("Capture Sun").AddComponent<Light>();
        var cam = new GameObject("Capture Camera").AddComponent<Camera>();
        var rt = new RenderTexture(1280, 720, 32);
        try
        {
            // Fixed, neutral lighting so captures are comparable (the runtime world is lit by the hub; the scene reopen below discards this).
            var ambient = new Color(0.55f, 0.58f, 0.62f);
            var sh = new UnityEngine.Rendering.SphericalHarmonicsL2(); sh.AddAmbientLight(ambient);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat; RenderSettings.ambientLight = ambient; RenderSettings.ambientProbe = sh;
            RenderSettings.reflectionIntensity = 0f; RenderSettings.fog = false;
            sun.type = LightType.Directional; sun.intensity = 1.1f; sun.shadows = LightShadows.Soft;
            sun.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.62f, 0.74f, 0.86f);
            cam.nearClipPlane = 0.3f; cam.farClipPlane = 500f; cam.targetTexture = rt;
            if (view == "top")
            {
                var b = SceneBounds(root);
                cam.orthographic = true;
                cam.orthographicSize = Mathf.Max(b.extents.z, b.extents.x / cam.aspect) * 1.1f + 1f;
                cam.transform.SetPositionAndRotation(new Vector3(b.center.x, b.max.y + 20f, b.center.z), Quaternion.Euler(90f, 0f, 0f));
            }
            else
            {
                float yaw = view == "right" ? 90f : view == "back" ? 180f : view == "left" ? -90f : 0f;
                cam.fieldOfView = 70f;
                cam.transform.SetPositionAndRotation(new Vector3(0f, 1.6f, 0f), Quaternion.Euler(8f, yaw, 0f));
            }
            cam.Render(); cam.Render(); // the first render after opening a scene can draw every material of a shader with one material's values

            var prev = RenderTexture.active; RenderTexture.active = rt;
            var tex = new Texture2D(rt.width, rt.height, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0); tex.Apply();
            RenderTexture.active = prev;
            var outPath = Path.GetFullPath("Library/WorldCaptures/" + p.RoomId + "-" + view + ".png");
            Directory.CreateDirectory(Path.GetDirectoryName(outPath));
            File.WriteAllBytes(outPath, tex.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(tex);
            return Response.Success("Captured " + view + " view.", new { path = outPath });
        }
        catch (Exception e) { return Response.Error(e.Message); }
        finally
        {
            cam.targetTexture = null; rt.Release();
            UnityEngine.Object.DestroyImmediate(rt);
            UnityEngine.Object.DestroyImmediate(cam.gameObject);
            UnityEngine.Object.DestroyImmediate(sun.gameObject);
            EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single); // drop the dirty flag the temp objects left
        }
    }

    /// <summary>The same loop without an MCP client (the editor must be closed):
    /// Unity -batchmode -quit -projectPath unity -executeMethod ReturnWorldMcpTools.BatchApplyAndCapture -worldRoom night-hike
    /// Applies the saved layout and captures every view; results are logged on lines starting "WORLD ".</summary>
    public static void BatchApplyAndCapture()
    {
        var args = Environment.GetCommandLineArgs();
        var i = Array.IndexOf(args, "-worldRoom");
        if (i < 0 || i + 1 >= args.Length) { Debug.LogError("WORLD pass -worldRoom <roomId>"); return; }
        var room = args[i + 1];
        Debug.Log("WORLD " + Newtonsoft.Json.JsonConvert.SerializeObject(ApplyWorldLayout(new ApplyParams { RoomId = room })));
        foreach (var view in new[] { "front", "left", "right", "back", "top" })
            Debug.Log("WORLD " + Newtonsoft.Json.JsonConvert.SerializeObject(CaptureWorld(new CaptureParams { RoomId = room, View = view })));
    }

    static Bounds SceneBounds(WorldSceneRoot root)
    {
        var rs = root != null ? root.GetComponentsInChildren<Renderer>().Where(r => r.name != "Ground").ToArray() : Array.Empty<Renderer>();
        if (rs.Length == 0) return new Bounds(new Vector3(0f, 0f, 5f), new Vector3(10f, 2f, 10f));
        var b = rs[0].bounds;
        foreach (var r in rs) b.Encapsulate(r.bounds);
        return b;
    }

    static string DirtyScene()
    {
        for (int i = 0; i < SceneManager.sceneCount; i++) { var s = SceneManager.GetSceneAt(i); if (s.isDirty) return string.IsNullOrEmpty(s.path) ? s.name : s.path; }
        return null;
    }

    static float R(float v) => Mathf.Round(v * 100f) / 100f;
}
