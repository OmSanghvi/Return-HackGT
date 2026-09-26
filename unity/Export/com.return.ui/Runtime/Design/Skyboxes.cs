using System.Collections.Generic;
using Return.Data;
using UnityEngine;

namespace Return.Design
{
    /// <summary>
    /// Real equirectangular skyboxes (graded CC0 Poly Haven skies, see THIRD-PARTY.md) for each painted SceneKey.
    /// Replaces the old static dome + painted panorama backdrop: HubEnvironment sets RenderSettings.skybox to
    /// MaterialFor(scene) instead of building geometry. Textures and materials are cached; MaterialFor uses
    /// ReturnShaders' template-material pattern so Return/SkyboxEquirect survives stripping in a device build.
    /// </summary>
    public static class Skyboxes
    {
        const string Root = "ReturnUI/Skyboxes/";
        static readonly Dictionary<SceneKey, Texture2D> TexCache = new Dictionary<SceneKey, Texture2D>();
        static readonly Dictionary<SceneKey, Material> MatCache = new Dictionary<SceneKey, Material>();
        static readonly Dictionary<SceneKey, Color> HorizonCache = new Dictionary<SceneKey, Color>();

        static readonly int MainTex = Shader.PropertyToID("_MainTex");

        /// <summary>Which graded sky a SceneKey opens on. Skies group scenes that share a mood rather than one per scene.</summary>
        public static string FileFor(SceneKey k)
        {
            switch (k)
            {
                case SceneKey.Clouds:
                case SceneKey.CloudSea: return "sky-citrus-orchard";
                case SceneKey.Beach: return "sky-kloofendal-38d-partly-cloudy";
                case SceneKey.Painted:
                case SceneKey.Home: return "sky-kloppenheim-06";
                case SceneKey.Night: return "sky-belfast-sunset";
                default: return "sky-kloofendal-48d-partly-cloudy"; // Hub, Meadow, Plain
            }
        }

        public static Texture2D For(SceneKey k)
        {
            if (TexCache.TryGetValue(k, out var t) && t != null) return t;
            t = Resources.Load<Texture2D>(Root + FileFor(k));
            if (t == null) Debug.LogWarning("Return UI: missing skybox " + Root + FileFor(k));
            TexCache[k] = t;
            return t;
        }

        public static Material MaterialFor(SceneKey k)
        {
            if (MatCache.TryGetValue(k, out var m) && m != null) return m;
            m = ReturnShaders.Create(ReturnShaders.SkyboxEquirect);
            var tex = For(k);
            if (tex != null) m.SetTexture(MainTex, tex);
            MatCache[k] = m;
            return m;
        }

        /// <summary>Average color of a thin band just above the equirect's horizon row (v just below 0.5, the row order
        /// SkyboxEquirect's frag shader uses: v=0 is straight up, v=1 is straight down). Reads as "sky near the ground"
        /// rather than the ground itself. Pure and testable; the texture must be readable (see TextureImportRules).</summary>
        public static Color HorizonColorFrom(Texture2D tex)
        {
            if (tex == null) return Color.white;
            int h = tex.height, w = tex.width;
            int band = Mathf.Max(1, h / 48);
            int y = Mathf.Clamp(h / 2 - band, 0, h - band);
            var px = tex.GetPixels(0, y, w, band);
            if (px.Length == 0) return Color.white;
            Color sum = Color.black;
            foreach (var c in px) sum += c;
            return sum / px.Length;
        }

        /// <summary>Cached horizon color for a scene's sky, used to tint fog, ambient and the portal edge/glow so
        /// nothing painted or fogged reads as a different color than the real sky behind it.</summary>
        public static Color Horizon(SceneKey k)
        {
            if (HorizonCache.TryGetValue(k, out var c)) return c;
            c = HorizonColorFrom(For(k));
            HorizonCache[k] = c;
            return c;
        }
    }
}
