using System.IO;
using UnityEngine;

/// <summary>
/// Dependency-free desktop photo chooser. Paste a local PNG/JPEG/WebP path or
/// drag a file from Finder/Explorer into the text field. This is intentionally
/// a hackathon-friendly path input rather than a platform-specific picker
/// plugin, so it works without adding a vendor package or cloud service.
/// </summary>
[RequireComponent(typeof(SketchScapeReconstructionClient))]
public class SketchScapeDesktopPhotoInput : MonoBehaviour
{
    [SerializeField] private string initialPath = "";
    [SerializeField] private bool showDebugUi = true;

    private SketchScapeReconstructionClient reconstructionClient;
    private string imagePath;

    private void Awake()
    {
        reconstructionClient = GetComponent<SketchScapeReconstructionClient>();
        imagePath = initialPath;
    }

    public void LoadPath(string path)
    {
        imagePath = path?.Trim().Trim('"') ?? "";
        reconstructionClient.SetInputFile(imagePath);
    }

    private void OnGUI()
    {
        if (!showDebugUi)
        {
            return;
        }
        GUILayout.BeginArea(new Rect(24f, 370f, 560f, 92f), GUI.skin.box);
        GUILayout.Label("OPTIONAL: USE ANY LOCAL PHOTO");
        imagePath = GUILayout.TextField(imagePath, 280);
        if (GUILayout.Button("Load photo path"))
        {
            LoadPath(imagePath);
        }
        GUILayout.Label("Paste or drag in a PNG/JPEG/WebP path. Default remains the Resources showcase image.");
        GUILayout.EndArea();
    }
}
