// SketchScape shared layer — small procedural building blocks (boxes, text, cards) used by the
// shared layer both when RoomKit bakes the room in the Editor and at runtime.
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// Convention for every flat thing (card, badge, envelope, page): its transform is the face, the
// face looks along -Z (towards the viewer), local +Y is "up" on the paper. Text sits a hair in
// front (negative z). Built-in meshes only; no colliders (nothing blocks grabs or teleport arcs).
using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace SketchScape
{
    public static class SharedShapes
    {
        static Mesh s_cube, s_quad, s_cylinder, s_flap;

        public static Mesh Cube { get { if (s_cube == null) s_cube = Resources.GetBuiltinResource<Mesh>("Cube.fbx"); return s_cube; } }
        public static Mesh Quad { get { if (s_quad == null) s_quad = Resources.GetBuiltinResource<Mesh>("Quad.fbx"); return s_quad; } }
        public static Mesh Cylinder { get { if (s_cylinder == null) s_cylinder = Resources.GetBuiltinResource<Mesh>("Cylinder.fbx"); return s_cylinder; } }

        /// <summary>Envelope flap: a double-sided triangle hanging from its pivot (the envelope's top edge).</summary>
        public static Mesh Flap
        {
            get
            {
                if (s_flap != null) return s_flap;
                s_flap = new Mesh { name = "SharedEnvelopeFlap" };
                s_flap.vertices = new[] { new Vector3(-0.5f, 0f, 0f), new Vector3(0.5f, 0f, 0f), new Vector3(0f, -1f, 0f) };
                s_flap.normals = new[] { Vector3.back, Vector3.back, Vector3.back };
                s_flap.uv = new[] { new Vector2(0f, 1f), new Vector2(1f, 1f), new Vector2(0.5f, 0f) };
                s_flap.triangles = new[] { 0, 1, 2, 0, 2, 1 };
                s_flap.RecalculateBounds();
                return s_flap;
            }
        }

        public static GameObject Node(Transform parent, string name, Vector3 localPos, Quaternion localRot)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos;
            go.transform.localRotation = localRot;
            return go;
        }

        public static MeshRenderer MeshNode(Transform parent, string name, Mesh mesh, Vector3 localPos, Quaternion localRot, Vector3 scale, Material mat)
        {
            var go = Node(parent, name, localPos, localRot);
            go.transform.localScale = scale;
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var r = go.AddComponent<MeshRenderer>();
            r.sharedMaterial = mat;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.lightProbeUsage = LightProbeUsage.Off;
            r.reflectionProbeUsage = ReflectionProbeUsage.Off;
            return r;
        }

        public static MeshRenderer Box(Transform parent, string name, Vector3 localPos, Vector3 size, Material mat)
        {
            return MeshNode(parent, name, Cube, localPos, Quaternion.identity, size, mat);
        }

        /// <summary>3D TextMeshPro text. em = font em size in metres; box = wrap rectangle in metres.</summary>
        public static TextMeshPro Text(Transform parent, string name, TMP_FontAsset font, string text, Vector3 localPos,
                                       Vector2 box, float em, Color color, TextAlignmentOptions align,
                                       bool autoSize = false, FontStyles style = FontStyles.Normal)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var t = go.AddComponent<TextMeshPro>();
            go.transform.localPosition = localPos;
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one;
            if (font != null) t.font = font;
            t.rectTransform.sizeDelta = box;
            t.fontSize = em * 10f;              // TextMeshPro (3D): 1 pt ~ 0.1 world units of em
            if (autoSize)
            {
                t.enableAutoSizing = true;
                t.fontSizeMax = em * 10f;
                t.fontSizeMin = em * 10f * 0.5f;
            }
            t.fontStyle = style;
            t.color = color;
            t.alignment = align;
            t.textWrappingMode = TextWrappingModes.Normal;
            t.overflowMode = TextOverflowModes.Truncate;
            t.richText = false;
            t.text = text ?? "";
            var r = go.GetComponent<MeshRenderer>();
            if (r != null)
            {
                r.shadowCastingMode = ShadowCastingMode.Off;
                r.receiveShadows = false;
            }
            return t;
        }

        /// <summary>A sheet of paper with a coloured header band, body text and a footer.</summary>
        public static Transform Card(Transform parent, string name, SharedLayerLook look, Vector3 localPos, Quaternion localRot,
                                     Vector2 size, Color band, string header, string body, string footer)
        {
            var root = Node(parent, name, localPos, localRot).transform;
            const float bandH = 0.046f;
            Box(root, "Paper", new Vector3(0f, 0f, 0.002f), new Vector3(size.x, size.y, 0.004f), look.paper);
            Box(root, "Band", new Vector3(0f, size.y / 2f - bandH / 2f, -0.0003f), new Vector3(size.x, bandH, 0.0006f), look.Tinted(look.color, band));
            Text(root, "Header", look.font, header, new Vector3(0f, size.y / 2f - bandH / 2f, -0.0015f),
                 new Vector2(size.x - 0.03f, bandH - 0.008f), 0.021f, Color.white, TextAlignmentOptions.MidlineLeft, true, FontStyles.Bold);
            float footerH = string.IsNullOrEmpty(footer) ? 0f : 0.03f;
            Text(root, "Body", look.font, body, new Vector3(0f, -bandH / 2f + footerH / 2f, -0.0015f),
                 new Vector2(size.x - 0.034f, size.y - bandH - footerH - 0.022f), 0.024f, SharedPalette.Ink, TextAlignmentOptions.TopLeft, true);
            if (footerH > 0f)
                Text(root, "Footer", look.font, footer, new Vector3(0f, -size.y / 2f + footerH / 2f + 0.004f, -0.0015f),
                     new Vector2(size.x - 0.034f, footerH), 0.0135f, new Color(0.38f, 0.35f, 0.32f), TextAlignmentOptions.MidlineLeft, true, FontStyles.Italic);
            return root;
        }

        public static void Destroy(UnityEngine.Object o)
        {
            if (o == null) return;
            if (Application.isPlaying) UnityEngine.Object.Destroy(o);
            else UnityEngine.Object.DestroyImmediate(o);
        }

        public static string Clip(string s, int max)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Trim();
            return s.Length <= max ? s : s.Substring(0, Mathf.Max(1, max - 3)) + "...";
        }
    }

    /// <summary>Materials + font the layer draws with. Tinted copies are cached (and, while RoomKit bakes, saved as assets).</summary>
    [Serializable]
    public class SharedLayerLook
    {
        public TMP_FontAsset font;
        public Material paper;       // lit, off-white
        public Material wood;        // lit, furniture
        public Material color;       // lit, tinted per account
        public Material envelope;    // lit, cream
        public Material glow;        // additive soft glow (SketchScape/Glow)
        public Material page;        // unlit textured page

        /// <summary>Set by RoomKit while it bakes in the Editor so tinted materials become assets. Null at runtime.</summary>
        public static Func<Material, Color, Material> TintFactory;

        [NonSerialized] Dictionary<(Material, uint), Material> _tintCache;
        [NonSerialized] List<Material> _ownedList;
        Dictionary<(Material, uint), Material> _tints { get { if (_tintCache == null) _tintCache = new Dictionary<(Material, uint), Material>(); return _tintCache; } }
        List<Material> _owned { get { if (_ownedList == null) _ownedList = new List<Material>(); return _ownedList; } }

        public void EnsureDefaults()
        {
            if (font == null) { try { font = TMP_Settings.defaultFontAsset; } catch (Exception) { } }
            if (paper == null) paper = Make("Standard", SharedPalette.Paper, 0.12f);
            if (wood == null) wood = Make("Standard", new Color(0.36f, 0.24f, 0.15f), 0.25f);
            if (color == null) color = Make("Standard", Color.white, 0.35f);
            if (envelope == null) envelope = Make("Standard", new Color(0.93f, 0.87f, 0.74f), 0.1f);
            if (page == null) page = Make("Unlit/Texture", Color.white, 0f);
            if (glow == null)
            {
                var sh = Shader.Find("SketchScape/Glow");
                if (sh != null) { glow = new Material(sh); glow.SetFloat("_DstBlend", (float)BlendMode.One); _owned.Add(glow); }
                else glow = Make("Standard", Color.white, 0f);
            }
        }

        Material Make(string shader, Color c, float gloss)
        {
            var sh = Shader.Find(shader);
            if (sh == null) sh = Shader.Find("Standard");
            var m = new Material(sh) { color = c };
            if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", gloss);
            _owned.Add(m);
            return m;
        }

        public Material Tinted(Material baseMat, Color c)
        {
            if (baseMat == null) return null;
            Color32 c32 = c;
            var key = (baseMat, (uint)(c32.r | (c32.g << 8) | (c32.b << 16) | (c32.a << 24)));
            Material m;
            if (_tints.TryGetValue(key, out m) && m != null) return m;
            if (TintFactory != null) m = TintFactory(baseMat, c);
            if (m == null)
            {
                m = new Material(baseMat) { name = baseMat.name + " " + ColorUtility.ToHtmlStringRGB(c), color = c };
                _owned.Add(m);
            }
            _tints[key] = m;
            return m;
        }

        public void Release()
        {
            if (!Application.isPlaying) { _owned.Clear(); _tints.Clear(); return; }
            foreach (var m in _owned) if (m != null) UnityEngine.Object.Destroy(m);
            _owned.Clear();
            _tints.Clear();
        }
    }
}
