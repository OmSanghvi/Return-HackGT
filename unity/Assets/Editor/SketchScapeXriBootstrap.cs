using System.Linq;
using UnityEditor;
using UnityEditor.PackageManager.UI;
using UnityEngine;

/// <summary>Imports pinned XRI authoring samples used by generated Quest scenes.</summary>
public static class SketchScapeXriBootstrap
{
    private const string PackageName = "com.unity.xr.interaction.toolkit";
    private const string PackageVersion = "3.0.11";

    [MenuItem("Tools/SketchScape/Quest/Import XRI Starter Assets and Simulator")]
    public static void ImportSamples()
    {
        Import("Starter Assets");
        Import("XR Device Simulator");
        AssetDatabase.Refresh();
        Debug.Log("Imported XRI Starter Assets and XR Device Simulator for desktop validation.");
    }

    private static void Import(string displayName)
    {
        Sample sample = Sample.FindByPackage(PackageName, PackageVersion)
            .FirstOrDefault(item => item.displayName == displayName);
        if (string.IsNullOrWhiteSpace(sample.displayName))
        {
            throw new System.InvalidOperationException("XRI sample not found: " + displayName);
        }
        if (!sample.isImported && !sample.Import(Sample.ImportOptions.OverridePreviousImports))
        {
            throw new System.InvalidOperationException("Could not import XRI sample: " + displayName);
        }
    }
}
