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
                t.mipmapEnabled = false;
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
            }
        }
    }
}
