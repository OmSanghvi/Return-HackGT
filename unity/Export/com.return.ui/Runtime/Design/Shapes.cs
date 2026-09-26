using System.Collections.Generic;
using UnityEngine;

namespace Return.Design
{
    /// <summary>Procedural 9-sliced sprites (rounded rect, ring, gradient). Generated once, cached. White, tinted by Image.color.</summary>
    public static class Shapes
    {
        static readonly Dictionary<string, Sprite> Cache = new Dictionary<string, Sprite>();

        /// <summary>Filled rounded rect. Use Image.Type.Sliced. Large radii collapse to a pill on small rects.</summary>
        public static Sprite Rounded(int radius) => Get("r" + radius, () => Build(radius, 0));
        /// <summary>1 to 2dp outline of a rounded rect.</summary>
        public static Sprite Ring(int radius, int thickness = 2) => Get("o" + radius + "_" + thickness, () => Build(radius, thickness));
        public static Sprite Pill => Rounded(48);
        public static Sprite PillRing => Ring(48, 2);

        /// <summary>Vertical alpha ramp: 0 at bottom to 1 at top (flip with a negative scale or use Bottom for scrims).</summary>
        public static Sprite GradientUp => Get("gu", () => Gradient(false));
        public static Sprite GradientDown => Get("gd", () => Gradient(true));
        /// <summary>Soft radial falloff for glow and center scrims.</summary>
        public static Sprite Radial => Get("rad", BuildRadial);

        /// <summary>Soft-dot particle material, additive (fireflies) or alpha-blended (motes). Uses the package's own
        /// Return/ParticleGlow shader: its transparent blend is a plain material property, not a surface-type keyword,
        /// so it always draws correctly even in a build that strips the URP Particles/Unlit variant this used to need
        /// (that stripping made every particle quad draw with the opaque fallback pass, a hard square).</summary>
        public static Material ParticleMaterial(bool additive)
        {
            var shader = ReturnShaders.Get(ReturnShaders.ParticleGlow) ?? ReturnShaders.Get(ReturnShaders.Flat);
            var mat = new Material(shader) { hideFlags = HideFlags.HideAndDontSave, renderQueue = 3000 };
            mat.SetFloat("_DstBlend", (float)(additive ? UnityEngine.Rendering.BlendMode.One : UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha));
            return mat;
        }
        public static Sprite White => Get("w", () =>
        {
            var t = new Texture2D(4, 4, TextureFormat.RGBA32, false) { hideFlags = HideFlags.HideAndDontSave };
            var px = new Color32[16]; for (int i = 0; i < 16; i++) px[i] = new Color32(255, 255, 255, 255);
            t.SetPixels32(px); t.Apply();
            return Sprite.Create(t, new Rect(0, 0, 4, 4), Vector2.one * 0.5f, 1);
        });

        static Sprite Get(string key, System.Func<Sprite> make)
        {
            if (Cache.TryGetValue(key, out var s) && s != null) return s;
            return Cache[key] = make();
        }

        static Sprite Build(int radius, int ring)
        {
            int n = radius * 2 + 4, c = n / 2;
            var t = new Texture2D(n, n, TextureFormat.RGBA32, false) { hideFlags = HideFlags.HideAndDontSave, wrapMode = TextureWrapMode.Clamp, filterMode = FilterMode.Bilinear };
            var px = new Color32[n * n];
            float half = n / 2f - 0.5f, r = radius;
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                {
                    // signed distance to a rounded box centered in the texture
                    float qx = Mathf.Abs(x - half) - (half - r), qy = Mathf.Abs(y - half) - (half - r);
                    float d = new Vector2(Mathf.Max(qx, 0), Mathf.Max(qy, 0)).magnitude + Mathf.Min(Mathf.Max(qx, qy), 0) - r;
                    float a = Mathf.Clamp01(0.5f - d);
                    if (ring > 0) a *= Mathf.Clamp01(d + ring + 0.5f);
                    px[y * n + x] = new Color32(255, 255, 255, (byte)Mathf.RoundToInt(a * 255));
                }
            t.SetPixels32(px); t.Apply();
            int b = radius + 1;
            return Sprite.Create(t, new Rect(0, 0, n, n), Vector2.one * 0.5f, 100, 0, SpriteMeshType.FullRect, new Vector4(b, b, b, b));
        }

        static Sprite Gradient(bool down)
        {
            var t = new Texture2D(4, 64, TextureFormat.RGBA32, false) { hideFlags = HideFlags.HideAndDontSave, wrapMode = TextureWrapMode.Clamp };
            for (int y = 0; y < 64; y++)
            {
                float v = y / 63f; if (down) v = 1 - v;
                byte a = (byte)Mathf.RoundToInt(Mathf.SmoothStep(0, 1, v) * 255);
                for (int x = 0; x < 4; x++) t.SetPixel(x, y, new Color32(255, 255, 255, a));
            }
            t.Apply();
            return Sprite.Create(t, new Rect(0, 0, 4, 64), Vector2.one * 0.5f, 1);
        }

        static Sprite BuildRadial()
        {
            const int n = 128;
            var t = new Texture2D(n, n, TextureFormat.RGBA32, false) { hideFlags = HideFlags.HideAndDontSave, wrapMode = TextureWrapMode.Clamp };
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                {
                    float d = new Vector2(x - n / 2f, y - n / 2f).magnitude / (n / 2f);
                    t.SetPixel(x, y, new Color32(255, 255, 255, (byte)Mathf.RoundToInt(Mathf.SmoothStep(1, 0, d) * 255)));
                }
            t.Apply();
            return Sprite.Create(t, new Rect(0, 0, n, n), Vector2.one * 0.5f, 1);
        }
    }
}
