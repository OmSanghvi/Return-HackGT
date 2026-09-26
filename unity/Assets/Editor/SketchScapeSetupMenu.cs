using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// One-click scene setup for the desktop SketchScape demo. It deliberately
/// adds no cloud credentials and never starts a reconstruction by itself.
/// </summary>
public static class SketchScapeSetupMenu
{
    public static void ConfigureSampleSceneBatch()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/SampleScene.unity", OpenSceneMode.Single);
        ConfigureCurrentScene();
    }

    [MenuItem("Tools/SketchScape/Configure Current Scene")]
    public static void ConfigureCurrentScene()
    {
        var loader = Object.FindAnyObjectByType<SketchSceneLoader>();
        if (loader == null)
        {
            var host = new GameObject("SketchScape Runtime");
            Undo.RegisterCreatedObjectUndo(host, "Create SketchScape Runtime");
            loader = Undo.AddComponent<SketchSceneLoader>(host);
        }

        AddIfMissing<SketchScapeReconstructionClient>(loader.gameObject);
        AddIfMissing<SketchScapeDesktopPhotoInput>(loader.gameObject);
        AddIfMissing<SketchScapeDemoPicker>(loader.gameObject);
        AddIfMissing<FurniturePortalWorld>(loader.gameObject);
        AddIfMissing<SketchSceneStatus>(loader.gameObject);
        AddIfMissing<SketchSceneModifier>(loader.gameObject);
        AddIfMissing<SceneInteractionController>(loader.gameObject);
        AddIfMissing<SketchScapeMcpBridge>(loader.gameObject);
        AddIfMissing<SketchScapeExperienceCompiler>(loader.gameObject);
        EditorUtility.SetDirty(loader.gameObject);
        EditorSceneManager.MarkSceneDirty(loader.gameObject.scene);
        EditorSceneManager.SaveScene(loader.gameObject.scene);
        Debug.Log("SketchScape is configured and the active scene was saved. Assign Tree, House, and Portal references on SketchSceneLoader, then set the API URL. Named interactives and the safe MCP bridge are installed on this host.");
    }

    private static void AddIfMissing<T>(GameObject host) where T : Component
    {
        if (host.GetComponent<T>() == null)
        {
            Undo.AddComponent<T>(host);
        }
    }
}
