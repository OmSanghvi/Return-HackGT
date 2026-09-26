using System.Collections.Generic;
using Return.Data;
using TMPro;
using UnityEngine;

namespace Return.Design
{
    public enum FontFace { Display, Accent, Kicker, Body, Medium, SemiBold }

    /// <summary>Loads the package's fonts, icons, logos and painted skies from Resources/ReturnUI. Cached.</summary>
    public static class UIAssets
    {
        const string Root = "ReturnUI/";
        static readonly Dictionary<string, Object> Cache = new Dictionary<string, Object>();
        static bool _fontsReady;

        static T Load<T>(string path) where T : Object
        {
            if (Cache.TryGetValue(path, out var o) && o != null) return (T)o;
            var a = Resources.Load<T>(Root + path);
            if (a == null) Debug.LogWarning("Return UI: missing asset " + Root + path);
            Cache[path] = a;
            return a;
        }

        static string FontFile(FontFace f)
        {
            switch (f)
            {
                case FontFace.Display: return "Bemirs-Regular SDF"; // caps-only, no digits (matches web --font-display); see EnsureFonts for the Role Model fallback
                case FontFace.Accent: return "Cormorant-LightItalic SDF";
                case FontFace.Kicker: return "RusillaSerif-Regular SDF";
                case FontFace.Medium: return "HankenGrotesk-Medium SDF";
                case FontFace.SemiBold: return "HankenGrotesk-SemiBold SDF";
                default: return "HankenGrotesk-Regular SDF";
            }
        }

        /// <summary>Name to use in TMP's font tag: &lt;font="Cormorant-LightItalic SDF"&gt;word&lt;/font&gt;.</summary>
        public const string AccentFontName = "Cormorant-LightItalic SDF";

        static void EnsureFonts()
        {
            if (_fontsReady) return;
            _fontsReady = true;
            if (TMP_Settings.instance == null)
                Debug.LogError("Return UI: TextMeshPro Essentials are missing, so text cannot render. Run Return > Import TMP Essentials (Window > TextMeshPro > Import TMP Essential Resources) once per project.");
            var serif = Load<TMP_FontAsset>("Fonts/Cormorant-Regular SDF");
            var numerals = Load<TMP_FontAsset>("Fonts/RoleModel-Regular SDF"); // Bemirs is caps-only with no digits (web falls back to Role Model for numerals)
            var display = Load<TMP_FontAsset>("Fonts/" + FontFile(FontFace.Display));
            if (display != null && numerals != null && !display.fallbackFontAssetTable.Contains(numerals)) display.fallbackFontAssetTable.Add(numerals);
            // Role Model's demo has letters and numbers only; punctuation falls back further to Cormorant (BRAND.md).
            if (display != null && serif != null && !display.fallbackFontAssetTable.Contains(serif)) display.fallbackFontAssetTable.Add(serif);
            // Register so <font="name"> tags resolve without TMP's own Resources path.
            foreach (FontFace f in System.Enum.GetValues(typeof(FontFace)))
            {
                var fa = Load<TMP_FontAsset>("Fonts/" + FontFile(f));
                if (fa != null) MaterialReferenceManager.AddFontAsset(fa);
            }
        }

        public static TMP_FontAsset Font(FontFace f) { EnsureFonts(); return Load<TMP_FontAsset>("Fonts/" + FontFile(f)); }
        public static Sprite Icon(string name) => Load<Sprite>("Icons/" + name);
        public static Sprite Logo(string name) => Load<Sprite>("Logos/" + name);

        static string SkyName(SceneKey k)
        {
            switch (k)
            {
                case SceneKey.Meadow: return "return-sky-day-meadow-lake";
                case SceneKey.Clouds: return "return-sky-day-cloud-field";
                case SceneKey.Painted: return "return-sky-golden-painted-clouds";
                case SceneKey.Home: return "return-sky-day-hilltop-home";
                case SceneKey.Beach: return "return-sky-day-morning-beach";
                case SceneKey.Plain: return "return-sky-day-golden-plain";
                case SceneKey.CloudSea: return "return-sky-dusk-cloud-sea";
                case SceneKey.Hub: return "return-sky-dusk-hub";
                default: return "return-sky-dusk-night-lake";
            }
        }

        /// <summary>New Return/LiquidGlass material, or null if the shader isn't in this build. Mirrors ReturnShaders'
        /// stripping-safe pattern (a Quest player build only keeps shaders something references) without editing that
        /// file, which is owned by a parallel work package; fold this into ReturnShaders proper on the next pass.
        /// Needs a template material at Resources/ReturnUI/Shaders/LiquidGlass.mat to survive stripping in a device build.</summary>
        public static Material LiquidGlass()
        {
            var s = Shader.Find("Return/LiquidGlass");
            if (s == null)
            {
                var t = Resources.Load<Material>("ReturnUI/Shaders/LiquidGlass");
                s = t != null ? t.shader : null;
            }
            return s != null ? new Material(s) { hideFlags = HideFlags.HideAndDontSave } : null;
        }

        public static Texture2D Sky(SceneKey k) => Load<Texture2D>("Skies/" + SkyName(k));
        public static Texture2D Depth(SceneKey k) => Load<Texture2D>("Depth/" + SkyName(k));
        public static bool IsDusk(SceneKey k) => k == SceneKey.CloudSea || k == SceneKey.Night || k == SceneKey.Hub;

        /// <summary>Sample photos for the stub picker (no native file picker on Quest). Ids are scene names.</summary>
        public static Texture2D Photo(string id) => System.Enum.TryParse<SceneKey>(id, out var k) ? Sky(k) : null;
    }
}
