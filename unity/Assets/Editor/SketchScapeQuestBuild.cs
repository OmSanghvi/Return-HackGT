using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>Deterministic Meta Quest Android configuration and no-device build.</summary>
public static class SketchScapeQuestBuild
{
    private const string ScenePath = "Assets/Generated/SketchScape/Scenes/Experience.unity";
    private const string OutputPath = "Builds/MetaQuest/SketchScape.apk";

    [MenuItem("Tools/SketchScape/Quest/Validate Build Readiness")]
    public static void ValidateBuildReadiness()
    {
        string[] errors = GetReadinessErrors();
        if (errors.Length > 0)
        {
            throw new BuildFailedException(string.Join("\n", errors));
        }
        Debug.Log("SketchScape Quest build prerequisites are ready. Hardware execution is not validated.");
    }

    [MenuItem("Tools/SketchScape/Quest/Configure Android Player")]
    public static void ConfigureAndroidPlayer()
    {
        SketchScapeOpenXRConfigurator.ConfigureAndroidOpenXR();
        PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, "com.sketchscape.experience");
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
        PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
        PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;
        PlayerSettings.colorSpace = ColorSpace.Linear;
        PlayerSettings.MTRendering = true;
        AssetDatabase.SaveAssets();
        Debug.Log("Configured Android ARM64/IL2CPP/Vulkan settings for Meta Quest.");
    }

    [MenuItem("Tools/SketchScape/Quest/Build APK Without Device")]
    public static void BuildApkWithoutDevice()
    {
        ConfigureAndroidPlayer();
        ValidateBuildReadiness();
        Directory.CreateDirectory(Path.GetDirectoryName(OutputPath));
        var options = new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = OutputPath,
            target = BuildTarget.Android,
            options = BuildOptions.None
        };
        var report = BuildPipeline.BuildPlayer(options);
        if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            throw new BuildFailedException("Quest APK build failed: " + report.summary.result);
        }
        Debug.Log("Built Meta Quest APK without deployment: " + OutputPath);
    }

    public static string[] GetReadinessErrors()
    {
        var errors = new System.Collections.Generic.List<string>();
        if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Android, BuildTarget.Android))
        {
            errors.Add("Android Build Support is not installed for Unity 6000.2.10f1. Add Android Build Support, SDK/NDK Tools, and OpenJDK in Unity Hub.");
        }
        if (!File.Exists(ScenePath))
        {
            errors.Add("Offline experience scene is missing. Run Tools/SketchScape/Authoring/Build Offline Experience Scene.");
        }
        else if (File.ReadAllText(ScenePath).Contains("Assembly-CSharp::AuthoredAssetReference"))
        {
            errors.Add("The generated scene still contains remote reconstruction placeholders. Package every object as Assets/SketchScape/Authoring/Artifacts/{object-id}.ply and rebuild.");
        }
        const string starterRig = "Assets/Samples/XR Interaction Toolkit/3.0.11/Starter Assets/Prefabs/XR Origin (XR Rig).prefab";
        if (!File.Exists(starterRig))
        {
            errors.Add("XRI Starter Assets are not imported. Run Tools/SketchScape/Quest/Import XRI Starter Assets and Simulator.");
        }
        string manifest = File.Exists("Packages/manifest.json") ? File.ReadAllText("Packages/manifest.json") : string.Empty;
        foreach (string package in new[] { "com.unity.xr.openxr", "com.unity.xr.meta-openxr", "com.unity.xr.interaction.toolkit", "com.arloopa.unitysplats" })
        {
            if (!manifest.Contains(package))
            {
                errors.Add("Required Quest package is missing: " + package);
            }
        }
        return errors.ToArray();
    }
}
