using System.Text;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace SketchScape
{
    /// <summary>
    /// Editor-only builder for a walk-through "portal" doorway: a cropped panorama quad framed by a glowing rim,
    /// a soft floor pool, a point light, a TMP title and a PortalTrigger on the root.
    /// </summary>
    internal static class PortalKit
    {
        private const string SoftDotPath = "Assets/SketchScape/WebCache/_soft_dot.png";
        private const string LabelFontPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";

        private const float DoorW = 1.4f;
        private const float DoorH = 2.3f;
        private const float RimT = 0.07f;   // rim thickness (x/y)
        private const float RimD = 0.08f;   // rim depth (z)

        /// floorPos = world position of the doorway's bottom centre on the floor. yawDeg = rotation about Y; at yaw 0 the doorway
        /// FACES -Z (a viewer standing at smaller z sees it). label = title text above the doorway. sky = equirect image shown
        /// inside the doorway (may be null -> flat dark blue). rimSrgb = glow colour (plain sRGB, no conversion). targetScene =
        /// scene name PortalTrigger loads. matFolder = an existing Assets/ folder where materials are saved as Portal_<safeName>_*.mat.
        internal static GameObject Build(Transform parent, string name, Vector3 floorPos, float yawDeg, string label,
                                         Texture2D sky, Color rimSrgb, string targetScene, string matFolder)
        {
            string safeName = SafeName(name);
            matFolder = NormalizeFolder(matFolder);

            GameObject root = new GameObject(string.IsNullOrEmpty(name) ? "Portal" : name);
            if (parent != null)
            {
                root.transform.SetParent(parent, false);
            }
            root.transform.position = floorPos;
            root.transform.rotation = Quaternion.Euler(0f, yawDeg, 0f);
            root.transform.localScale = Vector3.one;

            BuildDoorway(root.transform, sky, safeName, matFolder);
            BuildRim(root.transform, rimSrgb, safeName, matFolder);
            BuildPool(root.transform, rimSrgb, safeName, matFolder);
            BuildLight(root.transform, rimSrgb);
            BuildLabel(root.transform, label);

            PortalTrigger trigger = root.AddComponent<PortalTrigger>();
            trigger.targetScene = targetScene ?? "";
            trigger.size = new Vector3(DoorW, DoorH, 0.6f);

            AssetDatabase.SaveAssets();
            return root;
        }

        // ------------------------------------------------------------------ pieces

        private static void BuildDoorway(Transform root, Texture2D sky, string safeName, string matFolder)
        {
            GameObject go = MakePrimitive(PrimitiveType.Quad, "Doorway", root);
            go.transform.localPosition = new Vector3(0f, 1.15f, 0f);
            go.transform.localRotation = Quaternion.identity; // Quad normal is -Z: faces the viewer at yaw 0.
            go.transform.localScale = new Vector3(DoorW, DoorH, 1f);

            Material mat;
            if (sky != null)
            {
                mat = GetOrCreateMaterial(matFolder, safeName, "Sky", "Unlit/Texture", "Standard");
                mat.mainTexture = sky;
                mat.mainTextureScale = new Vector2(0.32f, 0.55f);
                mat.mainTextureOffset = new Vector2(0.34f, 0.22f);
            }
            else
            {
                mat = GetOrCreateMaterial(matFolder, safeName, "Sky", "Standard", "Standard");
                mat.mainTexture = null;
                mat.mainTextureScale = Vector2.one;
                mat.mainTextureOffset = Vector2.zero;
                if (mat.HasProperty("_Color"))
                {
                    mat.color = new Color(0.05f, 0.07f, 0.12f, 1f);
                }
            }
            EditorUtility.SetDirty(mat);

            ApplyRenderer(go, mat, false);
        }

        private static void BuildRim(Transform root, Color rimSrgb, string safeName, string matFolder)
        {
            Material mat = GetOrCreateMaterial(matFolder, safeName, "Rim", "Standard", "Standard");
            if (mat.HasProperty("_Color")) mat.color = rimSrgb;
            if (mat.HasProperty("_Glossiness")) mat.SetFloat("_Glossiness", 0.6f);
            mat.EnableKeyword("_EMISSION");
            if (mat.HasProperty("_EmissionColor")) mat.SetColor("_EmissionColor", rimSrgb * 2.2f);
            mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            EditorUtility.SetDirty(mat);

            GameObject rim = new GameObject("Rim");
            rim.transform.SetParent(root, false);
            rim.transform.localPosition = Vector3.zero;
            rim.transform.localRotation = Quaternion.identity;
            rim.transform.localScale = Vector3.one;

            float halfW = DoorW * 0.5f;          // 0.7
            float sideX = halfW + RimT * 0.5f;   // 0.735
            float outerW = DoorW + 2f * RimT;    // 1.54: spans the width including both posts
            float sideH = DoorH + 2f * RimT;     // 2.44: spans y -0.07 .. 2.37 so the posts meet the top and bottom bars
            float sideY = DoorH * 0.5f;          // 1.15: centre of -0.07 .. 2.37

            MakeRimBar(rim.transform, mat, "Rim Left",   new Vector3(-sideX, sideY, 0f),           new Vector3(RimT, sideH, RimD));
            MakeRimBar(rim.transform, mat, "Rim Right",  new Vector3( sideX, sideY, 0f),           new Vector3(RimT, sideH, RimD));
            MakeRimBar(rim.transform, mat, "Rim Top",    new Vector3(0f, DoorH + RimT * 0.5f, 0f), new Vector3(outerW, RimT, RimD)); // y 2.335
            MakeRimBar(rim.transform, mat, "Rim Bottom", new Vector3(0f, -RimT * 0.5f, 0f),        new Vector3(outerW, RimT, RimD)); // y -0.035
        }

        private static void MakeRimBar(Transform parent, Material mat, string name, Vector3 localPos, Vector3 localScale)
        {
            GameObject go = MakePrimitive(PrimitiveType.Cube, name, parent);
            go.transform.localPosition = localPos;
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = localScale;
            ApplyRenderer(go, mat, true);
        }

        private static void BuildPool(Transform root, Color rimSrgb, string safeName, string matFolder)
        {
            GameObject go = MakePrimitive(PrimitiveType.Quad, "Pool", root);
            go.transform.localPosition = new Vector3(0f, 0.006f, -0.55f);
            go.transform.localRotation = Quaternion.Euler(90f, 0f, 0f); // Quad normal -Z -> +Y (faces up)
            go.transform.localScale = new Vector3(2.4f, 1.6f, 1f);

            Material mat = GetOrCreateMaterial(matFolder, safeName, "Pool", "SketchScape/Glow", "Sprites/Default");
            Texture2D softDot = AssetDatabase.LoadAssetAtPath<Texture2D>(SoftDotPath);
            mat.mainTexture = softDot; // may be null; fine
            if (mat.HasProperty("_Color"))
            {
                mat.color = new Color(rimSrgb.r, rimSrgb.g, rimSrgb.b, 0.55f);
            }
            if (mat.HasProperty("_DstBlend"))
            {
                mat.SetFloat("_DstBlend", 1f); // additive
            }
            EditorUtility.SetDirty(mat);

            ApplyRenderer(go, mat, false);
        }

        private static void BuildLight(Transform root, Color rimSrgb)
        {
            GameObject go = new GameObject("Glow Light");
            go.transform.SetParent(root, false);
            go.transform.localPosition = new Vector3(0f, 1.2f, -0.45f);
            go.transform.localRotation = Quaternion.identity;

            Light light = go.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = rimSrgb;
            light.intensity = 1.3f;
            light.range = 3.2f;
            light.shadows = LightShadows.None;
            light.lightmapBakeType = LightmapBakeType.Realtime;
        }

        private static void BuildLabel(Transform root, string label)
        {
            GameObject go = new GameObject("Label");
            go.transform.SetParent(root, false);
            go.transform.localPosition = new Vector3(0f, 2.6f, 0f);
            go.transform.localRotation = Quaternion.Euler(0f, 180f, 0f); // readable from the -Z side
            // NOTE: TMP world-space fontSize 1.3 already yields ~0.13 m glyphs (TMP applies its own 0.1 factor for
            // non-orthographic text), so the transform stays at scale 1; scaling by 0.1 would give 1.3 cm glyphs.
            go.transform.localScale = Vector3.one;

            TextMeshPro tmp = go.AddComponent<TextMeshPro>();
            tmp.text = label ?? "";
            tmp.enableAutoSizing = false;
            tmp.fontSize = 1.3f;
            tmp.alignment = TextAlignmentOptions.Center;
            tmp.color = Color.white;
            tmp.textWrappingMode = TextWrappingModes.Normal;
            tmp.overflowMode = TextOverflowModes.Overflow;
            tmp.rectTransform.sizeDelta = new Vector2(2.2f, 0.3f);

            TMP_FontAsset font = null;
            try
            {
                font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(LabelFontPath);
                if (font == null)
                {
                    font = TMP_Settings.defaultFontAsset;
                }
            }
            catch (System.Exception)
            {
                font = null;
            }
            if (font != null)
            {
                tmp.font = font;
            }
            // outlineWidth deliberately not set: it forces a per-instance font material that is not saved with the scene.
        }

        // ------------------------------------------------------------------ helpers

        private static GameObject MakePrimitive(PrimitiveType type, string name, Transform parent)
        {
            GameObject go = GameObject.CreatePrimitive(type);
            go.name = name;
            go.transform.SetParent(parent, false);
            Collider col = go.GetComponent<Collider>();
            if (col != null)
            {
                UnityEngine.Object.DestroyImmediate(col);
            }
            return go;
        }

        private static void ApplyRenderer(GameObject go, Material mat, bool receiveShadows)
        {
            Renderer r = go.GetComponent<Renderer>();
            if (r == null) return;
            r.sharedMaterial = mat;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = receiveShadows;
        }

        /// Loads Portal_<safeName>_<suffix>.mat from matFolder if it exists (updating its shader), otherwise creates it.
        private static Material GetOrCreateMaterial(string matFolder, string safeName, string suffix, string shaderName, string fallbackShaderName)
        {
            Shader shader = Shader.Find(shaderName);
            if (shader == null && !string.IsNullOrEmpty(fallbackShaderName))
            {
                shader = Shader.Find(fallbackShaderName);
            }
            if (shader == null)
            {
                shader = Shader.Find("Standard");
            }

            string matName = "Portal_" + safeName + "_" + suffix;
            string path = matFolder + "/" + matName + ".mat";

            Material mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat != null)
            {
                if (shader != null && mat.shader != shader)
                {
                    mat.shader = shader;
                }
                return mat;
            }

            mat = new Material(shader);
            mat.name = matName;
            AssetDatabase.CreateAsset(mat, path);
            return mat;
        }

        private static string NormalizeFolder(string matFolder)
        {
            if (string.IsNullOrEmpty(matFolder))
            {
                matFolder = "Assets";
            }
            matFolder = matFolder.Replace('\\', '/').TrimEnd('/');
            if (!AssetDatabase.IsValidFolder(matFolder))
            {
                EnsureFolder(matFolder);
            }
            return matFolder;
        }

        private static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder)) return;
            int slash = folder.LastIndexOf('/');
            if (slash <= 0) return;
            string parent = folder.Substring(0, slash);
            string leaf = folder.Substring(slash + 1);
            EnsureFolder(parent);
            if (AssetDatabase.IsValidFolder(parent) && !string.IsNullOrEmpty(leaf))
            {
                AssetDatabase.CreateFolder(parent, leaf);
            }
        }

        private static string SafeName(string name)
        {
            if (string.IsNullOrEmpty(name)) return "Portal";
            StringBuilder sb = new StringBuilder(name.Length);
            for (int i = 0; i < name.Length; i++)
            {
                char c = name[i];
                sb.Append(char.IsLetterOrDigit(c) ? c : '_');
            }
            return sb.ToString();
        }
    }
}
