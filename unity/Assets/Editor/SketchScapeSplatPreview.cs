using Gsplat;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Drops a raw reconstruction PLY into the open scene so its splat rendering
/// can be eyeballed without going through the compiled-scene export.
/// </summary>
public static class SketchScapeSplatPreview
{
    private const string PreviewPlyPath = "Assets/SketchScape/Preview/reconstruction.ply";
    private const string PreviewObjectName = "Reconstruction Preview";

    [MenuItem("Tools/SketchScape/Preview/Place reconstruction.ply In Scene")]
    public static void PlacePreview()
    {
        AssetDatabase.ImportAsset(PreviewPlyPath, ImportAssetOptions.ForceSynchronousImport);
        var asset = AssetDatabase.LoadAssetAtPath<GsplatAsset>(PreviewPlyPath);
        if (asset == null)
        {
            Debug.LogError("SketchScapeSplatPreview: " + PreviewPlyPath + " did not import as a GsplatAsset.");
            return;
        }

        var existing = GameObject.Find(PreviewObjectName);
        if (existing != null)
        {
            Undo.DestroyObjectImmediate(existing);
        }

        var instance = new GameObject(PreviewObjectName);
        Undo.RegisterCreatedObjectUndo(instance, "Place reconstruction preview");
        instance.AddComponent<GsplatRenderer>().GsplatAsset = asset;

        // Stand it on the floor about 1.5 m in front of the main camera.
        var cam = Camera.main;
        Vector3 origin = cam != null ? cam.transform.position : Vector3.zero;
        Vector3 forward = cam != null ? Vector3.ProjectOnPlane(cam.transform.forward, Vector3.up).normalized : Vector3.forward;
        if (forward == Vector3.zero)
        {
            forward = Vector3.forward;
        }
        Vector3 position = origin + forward * 1.5f;
        position.y = -asset.Bounds.min.y;
        instance.transform.position = position;
        instance.transform.rotation = Quaternion.LookRotation(-forward, Vector3.up);

        Selection.activeGameObject = instance;
        SceneView.lastActiveSceneView?.FrameSelected();
        EditorSceneManager.MarkSceneDirty(instance.scene);
        Debug.Log("SketchScapeSplatPreview: placed " + asset.name + " at " + position + ", bounds " + asset.Bounds.size);
    }
}
