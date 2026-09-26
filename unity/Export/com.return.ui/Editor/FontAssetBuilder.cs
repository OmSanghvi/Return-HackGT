using System.IO;
using System.Linq;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;

namespace Return.UI.Editor
{
    /// <summary>Builds TMP SDF font assets from the TTFs in Runtime/Fonts. Run: Return/Build Font Assets, or -executeMethod Return.UI.Editor.FontAssetBuilder.Build.</summary>
    public static class FontAssetBuilder
    {
        const string Dir = "Packages/com.return.ui/Runtime/Resources/ReturnUI/Fonts";

        /// <summary>TMP needs its Essential Resources (TMP Settings) in the host project. Run once per project, then Build.</summary>
        [MenuItem("Return/Import TMP Essentials")]
        public static void ImportEssentials()
        {
            if (TMP_Settings.instance != null) return;
            AssetDatabase.ImportPackage("Packages/com.unity.ugui/Package Resources/TMP Essential Resources.unitypackage", false);
        }

        /// <summary>Headless variant: waits for the import to finish, then exits. Do not pass -quit.</summary>
        public static void ImportEssentialsAndExit()
        {
            if (TMP_Settings.instance != null) { EditorApplication.Exit(0); return; }
            AssetDatabase.importPackageCompleted += _ => EditorApplication.Exit(0);
            AssetDatabase.importPackageFailed += (_, e) => { Debug.LogError(e); EditorApplication.Exit(1); };
            ImportEssentials();
        }

        [MenuItem("Return/Build Font Assets")]
        public static void Build()
        {
            // .otf too: Bemirs ships as OpenType (TMP_FontAsset.CreateFontAsset works from either via the same Font import).
            foreach (var path in Directory.GetFiles(Dir, "*.ttf").Concat(Directory.GetFiles(Dir, "*.otf")))
            {
                var assetPath = path.Replace('\\', '/');
                var font = AssetDatabase.LoadAssetAtPath<Font>(assetPath);
                var outPath = Path.ChangeExtension(assetPath, null) + " SDF.asset";
                if (font == null || File.Exists(outPath)) continue;

                var fa = TMP_FontAsset.CreateFontAsset(font, 90, 9, GlyphRenderMode.SDFAA, 1024, 1024, AtlasPopulationMode.Dynamic, true);
                fa.name = Path.GetFileNameWithoutExtension(assetPath) + " SDF";
                AssetDatabase.CreateAsset(fa, outPath);
                fa.material.name = fa.name + " Material";
                fa.atlasTexture.name = fa.name + " Atlas";
                AssetDatabase.AddObjectToAsset(fa.material, fa);
                AssetDatabase.AddObjectToAsset(fa.atlasTexture, fa);
                EditorUtility.SetDirty(fa);
            }
            AssetDatabase.SaveAssets();
            Debug.Log("Return: font assets built");
        }
    }
}
