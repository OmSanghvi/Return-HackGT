using System;
using System.IO;
using System.Linq;
using Gsplat;
using Return.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Builds the per-room world scenes that hub portals open. Each world is its own scene under Assets/Scenes/Worlds with a
/// WorldSceneRoot (children authored in viewer space), listed in Build Settings and mapped roomId -> scene in the hub's
/// HubApp.worldMap. Agents building a room call CreateWorldScene, add content under the returned root, then SaveWorldScene.
/// Batch: Unity.exe -batchmode -quit -projectPath unity -executeMethod ReturnWorldScenes.BuildLakeHouseTestWorld
/// </summary>
public static class ReturnWorldScenes
{
    public const string WorldsFolder = "Assets/Scenes/Worlds";
    public const string HubScenePath = "Assets/Scenes/ReturnHub.unity";
    public const string TestPlyPath = "Assets/SketchScape/Preview/reconstruction.ply";

    [MenuItem("Tools/Return/Worlds/Build Lake House Test World")]
    public static void BuildLakeHouseTestWorld()
    {
        if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
        var setup = Application.isBatchMode ? null : EditorSceneManager.GetSceneManagerSetup();

        var root = CreateWorldScene("lake-house", "LakeHouse");
        var model = AddSplat(root, TestPlyPath, "Reconstruction Test", 1.5f);
        SaveWorldScene(root);
        Debug.Log("ReturnWorldScenes: LakeHouse built with " + (model != null ? model.name : "no model") + "; lake-house portal -> LakeHouse.");

        if (setup != null && setup.Length > 0) EditorSceneManager.RestoreSceneManagerSetup(setup);
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

    /// <summary>A Gaussian splat standing on the floor `distance` metres ahead of the arriving viewer, turned to face them.</summary>
    public static GameObject AddSplat(WorldSceneRoot root, string plyPath, string name, float distance)
    {
        AssetDatabase.ImportAsset(plyPath, ImportAssetOptions.ForceSynchronousImport);
        var asset = AssetDatabase.LoadAssetAtPath<GsplatAsset>(plyPath);
        if (asset == null) throw new InvalidDataException(plyPath + " did not import as a GsplatAsset; check the Console for the importer error.");

        var go = new GameObject(name);
        go.transform.SetParent(root.transform, false);
        go.transform.localPosition = new Vector3(0f, -asset.Bounds.min.y, distance);
        go.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);
        go.AddComponent<GsplatRenderer>().GsplatAsset = asset;
        var collider = go.AddComponent<BoxCollider>();
        collider.center = asset.Bounds.center;
        collider.size = asset.Bounds.size;
        return go;
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
