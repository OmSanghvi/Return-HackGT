using UnityEditor;

namespace Return.UI.Editor
{
    /// <summary>Import settings for the package's runtime art, applied on import so a fresh host project needs no setup.</summary>
    public class TextureImportRules : AssetPostprocessor
    {
        const string Root = "com.return.ui/Runtime/Resources/ReturnUI/";

        void OnPreprocessTexture()
        {
            if (!assetPath.Contains(Root)) return;
            var t = (TextureImporter)assetImporter;
            if (assetPath.Contains("/Icons/") || assetPath.Contains("/Logos/"))
            {
                t.textureType = TextureImporterType.Sprite;
                t.spriteImportMode = SpriteImportMode.Single;
                t.mipmapEnabled = false; // UI sprites: no mips, they're always drawn at native size on a flat canvas
                t.alphaIsTransparency = true;
                t.filterMode = UnityEngine.FilterMode.Bilinear;
            }
            else if (assetPath.Contains("/Depth/"))
            {
                t.sRGBTexture = false;
                t.mipmapEnabled = false;
                t.maxTextureSize = 1024;
                t.textureCompression = TextureImporterCompression.Compressed;
            }
            else if (assetPath.Contains("/Skies/"))
            {
                t.maxTextureSize = 2048;
                t.wrapMode = UnityEngine.TextureWrapMode.Clamp;
                t.textureCompression = TextureImporterCompression.Compressed;
                t.mipmapEnabled = true; // sky paintings: seen at grazing angles and huge scale, mips + trilinear keep them from shimmering
                t.filterMode = UnityEngine.FilterMode.Trilinear;
            }
            else if (assetPath.Contains("/Skyboxes/"))
            {
                t.textureType = TextureImporterType.Default;
                t.sRGBTexture = true;
                t.isReadable = true; // Skyboxes.HorizonColorFrom samples one band of pixels once, at load
                t.maxTextureSize = 4096;
                t.mipmapEnabled = true;
                t.filterMode = UnityEngine.FilterMode.Trilinear;
                t.wrapModeU = UnityEngine.TextureWrapMode.Repeat; // equirect: must wrap horizontally or the seam behind the viewer shows
                t.wrapModeV = UnityEngine.TextureWrapMode.Clamp;  // vertical never wraps (poles), Clamp avoids edge bleed there
                t.textureCompression = TextureImporterCompression.Compressed;
            }
            SetAndroidASTC(t);
        }

        /// <summary>Every rule above lands on Quest, so force ASTC there regardless of the default platform format.</summary>
        static void SetAndroidASTC(TextureImporter t)
        {
            var settings = t.GetPlatformTextureSettings("Android");
            settings.overridden = true;
            settings.format = TextureImporterFormat.ASTC_6x6;
            t.SetPlatformTextureSettings(settings);
        }
    }
}
