using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEditor.XR.Management;
using UnityEngine;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features.Interactions;

/// <summary>Creates and enables Android OpenXR settings required by Quest VR.</summary>
public static class SketchScapeOpenXRConfigurator
{
    private const string SettingsFolder = "Assets/XR/Settings";
    private const string LoaderPath = SettingsFolder + "/SketchScape Android OpenXR Loader.asset";

    [MenuItem("Tools/SketchScape/Quest/Enable Android OpenXR")]
    public static void ConfigureAndroidOpenXR()
    {
        EnsureFolder("Assets/XR");
        EnsureFolder(SettingsFolder);

        XRGeneralSettings general = XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Android);
        if (general == null || general.Manager == null)
        {
            MethodInfo getOrCreate = typeof(XRGeneralSettingsPerBuildTarget).GetMethod(
                "GetOrCreate", BindingFlags.Static | BindingFlags.NonPublic);
            var perTarget = getOrCreate?.Invoke(null, null) as XRGeneralSettingsPerBuildTarget;
            if (perTarget == null)
            {
                throw new System.InvalidOperationException("Unity could not create XR Plug-in Management settings.");
            }
            if (!perTarget.HasManagerSettingsForBuildTarget(BuildTargetGroup.Android))
            {
                perTarget.CreateDefaultManagerSettingsForBuildTarget(BuildTargetGroup.Android);
            }
            general = perTarget.SettingsForBuildTarget(BuildTargetGroup.Android);
        }

        OpenXRLoader loader = AssetDatabase.LoadAssetAtPath<OpenXRLoader>(LoaderPath);
        if (loader == null)
        {
            loader = ScriptableObject.CreateInstance<OpenXRLoader>();
            AssetDatabase.CreateAsset(loader, LoaderPath);
        }
        if (!general.Manager.activeLoaders.Contains(loader) && !general.Manager.TryAddLoader(loader))
        {
            throw new System.InvalidOperationException("Unity could not add the Android OpenXR loader.");
        }

        OpenXRSettings settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
        if (settings == null)
        {
            EditorUtility.SetDirty(general);
            EditorUtility.SetDirty(general.Manager);
            AssetDatabase.SaveAssets();
            Debug.LogWarning(
                "Android OpenXR settings cannot be finalized until Android Build Support is installed. Rerun this command after adding the module.");
            return;
        }
        OculusTouchControllerProfile touch = settings.GetFeature<OculusTouchControllerProfile>();
        if (touch != null)
        {
            touch.enabled = true;
            EditorUtility.SetDirty(touch);
        }

        EditorUtility.SetDirty(general);
        EditorUtility.SetDirty(general.Manager);
        AssetDatabase.SaveAssets();
        Debug.Log("Enabled Android OpenXR and the Oculus Touch controller profile for Meta Quest.");
    }

    private static void EnsureFolder(string path)
    {
        if (AssetDatabase.IsValidFolder(path))
        {
            return;
        }
        string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
        AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
    }
}
