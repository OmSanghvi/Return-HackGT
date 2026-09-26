using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.PackageManager.UI;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR.Hands.OpenXR;
using UnityEngine.XR.OpenXR;

// Wires the Return UI package (Export/com.return.ui-0.2.0.tgz) into this project:
// a Quest-tuned URP asset (the package's shaders are URP-only), the XRI Hands Interaction Demo
// rig with Quest hand tracking, and the ReturnHub scene. Each step is idempotent and can also run in batch mode
// (TMP Essentials import on their own in the editor; headless, run
// -executeMethod Return.UI.Editor.FontAssetBuilder.ImportEssentialsAndExit without -quit):
//   Unity -batchmode -projectPath unity -executeMethod ReturnHubSetup.SetupProject -quit
//   Unity -batchmode -projectPath unity -executeMethod ReturnHubSetup.BuildHubScene -quit
public static class ReturnHubSetup
{
    const string RenderingDir = "Assets/Settings/Rendering";
    const string PipelinePath = RenderingDir + "/Return_Quest_URP.asset";
    const string RendererPath = RenderingDir + "/Return_Quest_Renderer.asset";

    [MenuItem("Tools/SketchScape/Return Hub/1. Setup URP + XRI Hands Sample")]
    public static void SetupProject()
    {
        EnsureUrp();
        ImportHandsSamples();
        EnableQuestHandTracking();
        AssetDatabase.SaveAssets();
        Debug.Log("ReturnHubSetup: project setup done. Run step 2 once scripts recompile.");
    }

    [MenuItem("Tools/SketchScape/Return Hub/2. Build Return Hub Scene")]
    public static void BuildHubScene()
    {
        // Builds Assets/Scenes/ReturnHub.unity and puts it first in Build Settings.
        Return.UI.XR.Editor.ReturnVRSceneBuilder.Build();
        AssetDatabase.SaveAssets();
    }

    static void EnsureUrp()
    {
        var asset = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(PipelinePath);
        if (asset == null)
        {
            Directory.CreateDirectory(RenderingDir);
            var rendererData = ScriptableObject.CreateInstance<UniversalRendererData>();
            AssetDatabase.CreateAsset(rendererData, RendererPath);

            asset = UniversalRenderPipelineAsset.Create(rendererData);
            // Quest: MSAA instead of post AA, no HDR, no extra camera copies.
            asset.msaaSampleCount = 4;
            asset.supportsHDR = false;
            asset.supportsCameraDepthTexture = false;
            asset.supportsCameraOpaqueTexture = false;
            asset.shadowDistance = 20f;
            AssetDatabase.CreateAsset(asset, PipelinePath);
        }

        GraphicsSettings.defaultRenderPipeline = asset;
        // Quality levels without their own pipeline fall back to the default one.
        var current = QualitySettings.GetQualityLevel();
        for (int i = 0; i < QualitySettings.names.Length; i++)
        {
            QualitySettings.SetQualityLevel(i, false);
            if (QualitySettings.renderPipeline != null && QualitySettings.renderPipeline != asset)
                QualitySettings.renderPipeline = asset;
        }
        QualitySettings.SetQualityLevel(current, false);
    }

    // Only the Hands Interaction Demo (plus XR Hands' HandVisualizer, which its hand visuals are
    // variants of): this project already has the XRI 3.0.11 Starter Assets and Device Simulator
    // (Experience.unity references them), and a second copy would clash. So don't use
    // Return > Import XRI Samples, which imports all three.
    static void ImportHandsSamples()
    {
        ImportSample("com.unity.xr.hands", "HandVisualizer");
        ImportSample("com.unity.xr.interaction.toolkit", "Hands Interaction");
        AssetDatabase.Refresh();
    }

    static void ImportSample(string package, string sampleName)
    {
        var info = UnityEditor.PackageManager.PackageInfo.FindForPackageName(package);
        var sample = Sample.FindByPackage(info.name, info.version).FirstOrDefault(s => s.displayName.Contains(sampleName));
        if (sample.displayName == null) { Debug.LogError("ReturnHubSetup: sample '" + sampleName + "' not found in " + info.name + " " + info.version); return; }
        if (!sample.isImported) sample.Import(Sample.ImportOptions.HideImportWindow);
    }

    static void EnableQuestHandTracking()
    {
        var settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
        if (settings == null) { Debug.LogWarning("ReturnHubSetup: no Android OpenXR settings. Run Tools/SketchScape/Quest/Enable Android OpenXR first."); return; }
        foreach (var feature in new UnityEngine.XR.OpenXR.Features.OpenXRFeature[] { settings.GetFeature<HandTracking>(), settings.GetFeature<MetaHandTrackingAim>() })
        {
            if (feature == null || feature.enabled) continue;
            feature.enabled = true;
            EditorUtility.SetDirty(feature);
        }
    }
}
