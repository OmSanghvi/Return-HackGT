using UnityEditor;
using UnityEngine;

/// <summary>Constrained menu hooks discoverable by Unity MCP menu tooling.</summary>
public static class SketchScapeMcpMenu
{
    [MenuItem("Tools/SketchScape/MCP/Log Named Interactive Registry")]
    public static void LogRegistry()
    {
        var bridge = Object.FindAnyObjectByType<SketchScapeMcpBridge>();
        if (bridge == null)
        {
            Debug.LogWarning("Configure the current SketchScape scene before using the MCP bridge.");
            return;
        }
        bridge.LogRegistry();
    }

    [MenuItem("Tools/SketchScape/MCP/Build Offline Experience Scene")]
    public static void BuildOfflineExperienceScene()
    {
        SketchScapeOfflineExperienceBuilder.BuildOfflineExperienceScene();
    }

    [MenuItem("Tools/SketchScape/MCP/Validate Quest Build Readiness")]
    public static void ValidateQuestBuildReadiness()
    {
        SketchScapeQuestBuild.ValidateBuildReadiness();
    }

    [MenuItem("Tools/SketchScape/MCP/Compile Published Experience")]
    public static void CompilePublishedExperience()
    {
        var compiler = Object.FindAnyObjectByType<SketchScapeExperienceCompiler>();
        if (compiler == null)
        {
            Debug.LogWarning("Configure the current SketchScape scene before compiling an experience.");
            return;
        }
        if (!EditorApplication.isPlaying)
        {
            Debug.LogWarning("Enter Play mode before compiling a published experience.");
            return;
        }
        compiler.CompilePublishedExperience();
    }

    [MenuItem("Tools/SketchScape/MCP/Execute Configured Safe Action")]
    public static void ExecuteConfiguredAction()
    {
        var bridge = Object.FindAnyObjectByType<SketchScapeMcpBridge>();
        if (bridge == null)
        {
            Debug.LogWarning("Configure the current SketchScape scene before using the MCP bridge.");
            return;
        }
        bridge.ExecuteConfiguredAction();
        EditorUtility.SetDirty(bridge.gameObject);
    }
}
