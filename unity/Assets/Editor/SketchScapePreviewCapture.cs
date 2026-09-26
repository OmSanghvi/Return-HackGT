using System;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Builds the offline experience and renders a PNG preview of it without
/// entering Play mode, so the result can be checked from the command line:
/// Unity -batchmode -quit -projectPath . -executeMethod SketchScapePreviewCapture.BuildAndCapture -previewOut preview.png
/// The runtime-only setup (card stands, attribution rings) is run in the
/// opened scene for the capture and never saved.
/// </summary>
public static class SketchScapePreviewCapture
{
    private const string DefaultOutput = "Temp/SketchScape/experience-preview.png";

    [MenuItem("Tools/SketchScape/Authoring/Build And Capture Preview")]
    public static void BuildAndCapture()
    {
        SketchScapeOfflineExperienceBuilder.BuildOfflineExperienceScene();
        EditorSceneManager.OpenScene(SketchScapeOfflineExperienceBuilder.OutputScenePath, OpenSceneMode.Single);

        foreach (var card in UnityEngine.Object.FindObjectsByType<SketchCard>(FindObjectsSortMode.None))
        {
            RunStart(card);
        }
        foreach (var attribution in UnityEngine.Object.FindObjectsByType<ContributorAttribution>(FindObjectsSortMode.None))
        {
            RunStart(attribution);
            Debug.Log("SketchScape preview: " + attribution.name + " attributed to "
                + attribution.ContributorDisplayName + " (" + ColorUtility.ToHtmlStringRGB(attribution.AttributionColor) + ")");
        }

        string output = CommandLineValue("-previewOut") ?? DefaultOutput;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
        File.WriteAllBytes(output, Render(new Vector3(0f, 2.6f, -3.6f), new Vector3(0f, 0.7f, 0f)));
        Debug.Log("SketchScape preview written to " + Path.GetFullPath(output));

        // What the headset sees at spawn (standing eye height, facing the rig's forward).
        var rig = GameObject.Find("XR Origin (Quest)");
        if (rig != null)
        {
            Vector3 eye = new Vector3(rig.transform.position.x, 1.6f, rig.transform.position.z);
            string povOutput = Path.ChangeExtension(output, null) + "-pov.png";
            File.WriteAllBytes(povOutput, Render(eye, eye + rig.transform.forward * 3f + Vector3.down * 0.6f));
            Debug.Log("SketchScape headset preview written to " + Path.GetFullPath(povOutput));
        }

        // A second, head-on view of the first sketch card, to check the page is legible.
        var firstCard = UnityEngine.Object.FindFirstObjectByType<SketchCard>();
        if (firstCard != null)
        {
            Transform card = firstCard.transform;
            string cardOutput = Path.ChangeExtension(output, null) + "-card.png";
            File.WriteAllBytes(cardOutput, Render(card.position + card.forward * 1.1f, card.position));
            Debug.Log("SketchScape card preview written to " + Path.GetFullPath(cardOutput));
        }
    }

    private static void RunStart(MonoBehaviour component)
    {
        component.GetType()
            .GetMethod("Start", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
            ?.Invoke(component, null);
    }

    private static byte[] Render(Vector3 position, Vector3 lookAt)
    {
        const int width = 1280;
        const int height = 720;
        var cameraObject = new GameObject("Preview Camera");
        try
        {
            var camera = cameraObject.AddComponent<Camera>();
            camera.transform.position = position;
            camera.transform.LookAt(lookAt);
            camera.fieldOfView = 60f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.12f, 0.14f, 0.2f);

            var target = new RenderTexture(width, height, 24);
            camera.targetTexture = target;
            camera.Render();

            RenderTexture.active = target;
            var image = new Texture2D(width, height, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            image.Apply();
            RenderTexture.active = null;
            camera.targetTexture = null;
            UnityEngine.Object.DestroyImmediate(target);
            byte[] png = image.EncodeToPNG();
            UnityEngine.Object.DestroyImmediate(image);
            return png;
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(cameraObject);
        }
    }

    private static string CommandLineValue(string name)
    {
        string[] arguments = Environment.GetCommandLineArgs();
        int index = Array.IndexOf(arguments, name);
        return index >= 0 && index + 1 < arguments.Length ? arguments[index + 1] : null;
    }
}
