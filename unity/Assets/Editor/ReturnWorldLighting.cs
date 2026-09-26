using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Bakes lighting for every world scene under Assets/Scenes/Worlds (see ReturnWorldScenes). Marks every
/// non-dynamic renderer static, makes sure there is exactly one directional sun at a fixed, consistent
/// direction, drops a light probe group grid over the scene bounds, and runs Lightmapping.Bake with
/// baked/mixed lighting. Menu: Return &gt; Bake World Lighting. Batch: BakeAll(), e.g.
/// -executeMethod ReturnWorldLighting.BakeAll.
/// </summary>
public static class ReturnWorldLighting
{
    /// <summary>Same sun direction for every world, so baked lighting is consistent room to room.</summary>
    public static readonly Vector3 SunEulerAngles = new Vector3(50f, -30f, 0f);

    const float ProbeSpacing = 4f;
    const float ProbeHeightLow = 0.2f;
    const float ProbeHeightHigh = 2.2f;

    [MenuItem("Return/Bake World Lighting")]
    public static void BakeFromMenu() => BakeAll();

    /// <summary>Bakes every world scene. Safe to call from -batchmode -executeMethod.</summary>
    public static void BakeAll()
    {
        var setup = Application.isBatchMode ? null : EditorSceneManager.GetSceneManagerSetup();
        foreach (var path in WorldScenePaths())
            BakeScene(path);
        if (setup != null && setup.Length > 0) EditorSceneManager.RestoreSceneManagerSetup(setup);
    }

    static IEnumerable<string> WorldScenePaths() =>
        Directory.Exists(ReturnWorldScenes.WorldsFolder)
            ? Directory.GetFiles(ReturnWorldScenes.WorldsFolder, "*.unity").OrderBy(p => p)
            : Enumerable.Empty<string>();

    static void BakeScene(string path)
    {
        var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
        MarkStaticRenderers(scene);
        EnsureSun(scene);
        EnsureLightProbeGrid(scene);
        ConfigureLightingSettings();
        Lightmapping.Bake();
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
    }

    /// <summary>Marks every renderer static unless it (or a parent) has a Rigidbody, or is named/tagged as dynamic.</summary>
    static void MarkStaticRenderers(Scene scene)
    {
        foreach (var root in scene.GetRootGameObjects())
            foreach (var r in root.GetComponentsInChildren<Renderer>(true))
            {
                if (IsDynamic(r.gameObject)) continue;
                GameObjectUtility.SetStaticEditorFlags(r.gameObject, (StaticEditorFlags)~0);
            }
    }

    static bool IsDynamic(GameObject go)
    {
        if (go.GetComponentInParent<Rigidbody>() != null) return true;
        if (go.CompareTag("Dynamic")) return true;
        for (var t = go.transform; t != null; t = t.parent)
            if (t.name.ToLowerInvariant().Contains("dynamic")) return true;
        return false;
    }

    /// <summary>Finds the scene's directional light (creates one named "Sun" if missing) and points it at the fixed direction.</summary>
    static void EnsureSun(Scene scene)
    {
        Light sun = null;
        foreach (var root in scene.GetRootGameObjects())
        {
            sun = root.GetComponentsInChildren<Light>(true).FirstOrDefault(l => l.type == LightType.Directional);
            if (sun != null) break;
        }
        if (sun == null)
            sun = new GameObject("Sun").AddComponent<Light>();

        sun.type = LightType.Directional;
        sun.transform.rotation = Quaternion.Euler(SunEulerAngles);
        sun.lightmapBakeType = LightmapBakeType.Mixed;
        sun.shadows = LightShadows.Soft;
        GameObjectUtility.SetStaticEditorFlags(sun.gameObject, (StaticEditorFlags)~0);
    }

    /// <summary>Drops (or repositions) a light probe group in a grid over the bounds of every renderer in the scene.</summary>
    static void EnsureLightProbeGrid(Scene scene)
    {
        Bounds? bounds = null;
        foreach (var root in scene.GetRootGameObjects())
            foreach (var r in root.GetComponentsInChildren<Renderer>(true))
            {
                if (bounds.HasValue) { var acc = bounds.Value; acc.Encapsulate(r.bounds); bounds = acc; }
                else bounds = r.bounds;
            }
        if (!bounds.HasValue) return;

        LightProbeGroup group = null;
        foreach (var root in scene.GetRootGameObjects())
        {
            group = root.GetComponentInChildren<LightProbeGroup>(true);
            if (group != null) break;
        }
        if (group == null)
            group = new GameObject("Light Probe Group").AddComponent<LightProbeGroup>();
        group.transform.position = Vector3.zero; // probe positions below are world-space, keep the group unrotated/unscaled at the origin

        var b = bounds.Value;
        var positions = new List<Vector3>();
        for (float x = b.min.x; x <= b.max.x; x += ProbeSpacing)
            for (float z = b.min.z; z <= b.max.z; z += ProbeSpacing)
            {
                positions.Add(new Vector3(x, ProbeHeightLow, z));
                positions.Add(new Vector3(x, ProbeHeightHigh, z));
            }
        group.probePositions = positions.ToArray();
    }

    static void ConfigureLightingSettings()
    {
        var settings = Lightmapping.lightingSettings ?? new LightingSettings();
        settings.bakedGI = true;
        settings.mixedBakeMode = MixedLightingMode.IndirectOnly;
        Lightmapping.lightingSettings = settings;
    }
}
