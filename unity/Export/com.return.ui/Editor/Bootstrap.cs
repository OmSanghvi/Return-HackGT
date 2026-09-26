using TMPro;
using UnityEditor;

namespace Return.UI.Editor
{
    /// <summary>First import into a project: bring in TextMeshPro Essentials (TMP Settings, default font) if they are missing, so text renders without the TMP importer prompt.</summary>
    static class Bootstrap
    {
        [InitializeOnLoadMethod]
        static void Init()
        {
            if (UnityEngine.Application.isBatchMode) return;
            EditorApplication.delayCall += () => { if (TMP_Settings.instance == null) FontAssetBuilder.ImportEssentials(); };
        }
    }
}
