using System.IO;
using UnityEditor;
using UnityEngine;

namespace Return.UI.Editor
{
    /// <summary>
    /// Bakes the hub's photoreal tree impostors (Runtime/Hub/DistantTrees.cs): loads a scanned Poly Haven tree from
    /// Assets/_PhotorealSource (git-ignored; re-download with the URLs in THIRD-PARTY.md), renders it once, side on,
    /// with an orthographic camera on a transparent background under a soft daylight key, and writes a PNG card to
    /// Runtime/Resources/ReturnUI/Impostors. Only the PNG ships; the heavy source mesh never reaches the Quest build.
    /// </summary>
    public static class ReturnImpostorBaker
    {
        const string Source = "Assets/_PhotorealSource/";
        const string Out = "Packages/com.return.ui/Runtime/Resources/ReturnUI/Impostors/";
        const int Layer = 31, Height = 1024;

        static readonly (string gltf, string name)[] Trees =
        {
            ("jacaranda_tree/jacaranda_tree.gltf", "jacaranda"),
            ("island_tree_02/island_tree_02.gltf", "island-tree"),
        };

        [MenuItem("Tools/Return/Bake Tree Impostors")]
        public static void BakeAll()
        {
            Directory.CreateDirectory(Path.GetFullPath(Out));
            foreach (var (gltf, name) in Trees) Bake(Source + gltf, name);
            AssetDatabase.Refresh();
        }

        static void Bake(string assetPath, string name)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null) { Debug.LogError("[Return] Impostor baker: missing " + assetPath); return; }
            var tree = Object.Instantiate(prefab); tree.hideFlags = HideFlags.HideAndDontSave;
            tree.transform.position = new Vector3(0, -2000f, 0);
            var bounds = new Bounds(tree.transform.position, Vector3.zero); bool any = false;
            foreach (var r in tree.GetComponentsInChildren<Renderer>())
            {
                r.gameObject.layer = Layer;
                if (any) bounds.Encapsulate(r.bounds); else { bounds = r.bounds; any = true; }
            }

            var camGo = new GameObject("ImpostorCam") { hideFlags = HideFlags.HideAndDontSave };
            var cam = camGo.AddComponent<Camera>();
            cam.orthographic = true; cam.orthographicSize = bounds.extents.y * 1.02f;
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.cullingMask = 1 << Layer; cam.nearClipPlane = 0.01f; cam.farClipPlane = bounds.size.z * 4f + 10f;
            camGo.transform.position = bounds.center - Vector3.forward * (bounds.size.z * 2f + 5f);
            camGo.transform.rotation = Quaternion.identity;

            var lightGo = new GameObject("ImpostorSun") { hideFlags = HideFlags.HideAndDontSave };
            var sun = lightGo.AddComponent<Light>(); sun.type = LightType.Directional; sun.cullingMask = 1 << Layer;
            sun.color = new Color(1f, 0.97f, 0.92f); sun.intensity = 1.4f; sun.shadows = LightShadows.Soft;
            lightGo.transform.rotation = Quaternion.Euler(40f, 30f, 0f); // front-left key so the canopy has form, like the HDRI's afternoon sun

            int width = Mathf.Max(8, Mathf.RoundToInt(Height * bounds.size.x / bounds.size.y));
            var rt = new RenderTexture(width, Height, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4 };
            cam.aspect = (float)width / Height; cam.targetTexture = rt;
            // bake under neutral warm daylight, not whatever sky the open scene has (a blue editor sky tints the leaves grey-blue)
            var (mode, amb, refl) = (RenderSettings.ambientMode, RenderSettings.ambientLight, RenderSettings.reflectionIntensity);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat; RenderSettings.ambientLight = new Color(0.52f, 0.52f, 0.46f); RenderSettings.reflectionIntensity = 0.15f;
            cam.Render();
            (RenderSettings.ambientMode, RenderSettings.ambientLight, RenderSettings.reflectionIntensity) = (mode, amb, refl);

            RenderTexture.active = rt;
            var tex = new Texture2D(width, Height, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, width, Height), 0, 0); tex.Apply();
            RenderTexture.active = null;
            DilateEdges(tex); // bleed leaf color into the transparent border so mips and alpha cutout don't fringe dark
            File.WriteAllBytes(Path.GetFullPath(Out + name + ".png"), tex.EncodeToPNG());
            Debug.Log("[Return] Impostor baked: " + name + " " + width + "x" + Height + ", tree height " + bounds.size.y.ToString("0.0") + " m");

            cam.targetTexture = null; rt.Release();
            Object.DestroyImmediate(rt); Object.DestroyImmediate(tex);
            Object.DestroyImmediate(camGo); Object.DestroyImmediate(lightGo); Object.DestroyImmediate(tree);
        }

        /// <summary>Several passes copying each transparent pixel's color from an opaque neighbour, alpha left at 0.</summary>
        static void DilateEdges(Texture2D tex)
        {
            int w = tex.width, h = tex.height; var px = tex.GetPixels32();
            for (int pass = 0; pass < 8; pass++)
            {
                var src = (Color32[])px.Clone();
                for (int y = 1; y < h - 1; y++)
                for (int x = 1; x < w - 1; x++)
                {
                    int i = y * w + x; if (Filled(src[i])) continue;
                    int j = Filled(src[i + 1]) ? i + 1 : Filled(src[i - 1]) ? i - 1 : Filled(src[i + w]) ? i + w : Filled(src[i - w]) ? i - w : -1;
                    if (j >= 0) px[i] = new Color32(src[j].r, src[j].g, src[j].b, 0);
                }
            }
            tex.SetPixels32(px); tex.Apply();
        }

        /// <summary>Opaque, or already given a color by an earlier dilation pass (the clear color is pure black).</summary>
        static bool Filled(Color32 c) => c.a > 8 || c.r + c.g + c.b > 0;
    }
}
