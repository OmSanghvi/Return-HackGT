using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public enum TextStyle { Hero, DisplayL, DisplayM, Title, H1, H2, BodyL, Body, Label, Caption, Kicker, Overline }

    /// <summary>Tiny programmatic UGUI builder. Everything is themed: colors are token roles, not values. Units are dp (1 canvas unit).</summary>
    public static class UI
    {
        // ---- structure ---------------------------------------------------------------------
        public static RectTransform Box(Transform parent, string name, float w = -1, float h = -1)
        {
            var go = new GameObject(name, typeof(RectTransform));
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            if (w >= 0 || h >= 0) rt.sizeDelta = new Vector2(Mathf.Max(w, 0), Mathf.Max(h, 0));
            if (w >= 0 || h >= 0) Size(rt, w, h);
            return rt;
        }

        /// <summary>Preferred size for layout groups (-1 = leave to content).</summary>
        public static RectTransform Size(RectTransform rt, float w = -1, float h = -1, float flexW = -1, float flexH = -1)
        {
            var le = rt.GetOrAdd<LayoutElement>();
            if (w >= 0) le.preferredWidth = w;
            if (h >= 0) le.preferredHeight = h;
            if (flexW >= 0) le.flexibleWidth = flexW;
            if (flexH >= 0) le.flexibleHeight = flexH;
            return rt;
        }

        public static RectTransform Stretch(RectTransform rt, float l = 0, float b = 0, float r = 0, float t = 0)
        {
            rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.pivot = new Vector2(0.5f, 0.5f);
            rt.offsetMin = new Vector2(l, b); rt.offsetMax = new Vector2(-r, -t);
            return rt;
        }

        public static RectTransform Anchor(RectTransform rt, Vector2 anchor, Vector2 pos, Vector2? size = null)
        {
            rt.anchorMin = rt.anchorMax = rt.pivot = anchor;
            rt.anchoredPosition = pos;
            if (size.HasValue) rt.sizeDelta = size.Value;
            return rt;
        }

        static RectTransform Group<T>(Transform parent, string name, float spacing, RectOffset pad, TextAnchor align) where T : HorizontalOrVerticalLayoutGroup
        {
            var rt = Box(parent, name);
            var g = rt.gameObject.AddComponent<T>();
            g.spacing = spacing; g.padding = pad ?? new RectOffset();
            g.childAlignment = align;
            g.childControlWidth = g.childControlHeight = true;
            g.childForceExpandWidth = g is VerticalLayoutGroup; g.childForceExpandHeight = false;
            return rt;
        }

        /// <summary>Vertical stack: children fill the width, take their own height.</summary>
        public static RectTransform V(Transform parent, string name, float spacing = 0, RectOffset pad = null, TextAnchor align = TextAnchor.UpperLeft)
            => Group<VerticalLayoutGroup>(parent, name, spacing, pad, align);

        /// <summary>Horizontal row: children take their own width, fill the height.</summary>
        public static RectTransform H(Transform parent, string name, float spacing = 0, RectOffset pad = null, TextAnchor align = TextAnchor.MiddleLeft)
            => Group<HorizontalLayoutGroup>(parent, name, spacing, pad, align);

        public static RectTransform Fit(RectTransform rt, bool horizontal = false, bool vertical = true)
        {
            var f = rt.GetOrAdd<ContentSizeFitter>();
            f.horizontalFit = horizontal ? ContentSizeFitter.FitMode.PreferredSize : ContentSizeFitter.FitMode.Unconstrained;
            f.verticalFit = vertical ? ContentSizeFitter.FitMode.PreferredSize : ContentSizeFitter.FitMode.Unconstrained;
            return rt;
        }

        public static RectTransform Spacer(Transform parent, float w = 0, float h = 0, bool flex = false)
        {
            var rt = Box(parent, "Spacer");
            Size(rt, w, h, flex ? 1 : -1, flex ? 1 : -1);
            return rt;
        }

        /// <summary>A fixed w x h slot that does not stretch inside a filling layout group (V stacks stretch children).</summary>
        public static RectTransform Fixed(Transform parent, string name, float w, float h, TextAnchor align = TextAnchor.MiddleCenter)
        {
            var row = H(parent, name + "Slot", 0, null, align); Size(row, -1, h);
            var inner = Box(row, name, w, h); Size(inner, w, h);
            return inner;
        }

        public static RectOffset Pad(int all) => new RectOffset(all, all, all, all);
        public static RectOffset Pad(int x, int y) => new RectOffset(x, x, y, y);

        /// <summary>Ignore the parent's layout group (overlay children: badges, scrims, corner buttons).</summary>
        public static RectTransform Overlay(RectTransform rt) { rt.gameObject.AddComponent<LayoutElement>().ignoreLayout = true; return rt; }

        // ---- visuals -----------------------------------------------------------------------
        public static Image Img(Transform parent, string name, ColorRole role, Sprite sprite = null, Image.Type type = Image.Type.Simple, bool raycast = false)
        {
            var rt = Box(parent, name);
            var img = rt.gameObject.AddComponent<Image>();
            img.sprite = sprite; img.type = type; img.raycastTarget = raycast; img.preserveAspect = false;
            var tg = rt.gameObject.AddComponent<ThemedGraphic>(); tg.role = role; tg.Refresh();
            return img;
        }

        /// <summary>Rounded background filling its parent (behind siblings). Add it FIRST, or call SetAsFirstSibling.</summary>
        public static Image Bg(RectTransform parent, ColorRole role, int radius = 24)
        {
            var img = Img(parent, "Bg", role, Shapes.Rounded(radius), Image.Type.Sliced);
            Stretch(img.rectTransform); Overlay(img.rectTransform); img.rectTransform.SetAsFirstSibling();
            return img;
        }

        public static Image Border(RectTransform parent, ColorRole role, int radius = 24, int thickness = 2)
        {
            var img = Img(parent, "Border", role, Shapes.Ring(radius, thickness), Image.Type.Sliced);
            Stretch(img.rectTransform); Overlay(img.rectTransform);
            return img;
        }

        public static Image Icon(Transform parent, string name, ColorRole role, float size = 20)
        {
            var img = Img(parent, "Icon:" + name, role, UIAssets.Icon(name));
            img.preserveAspect = true;
            Size(img.rectTransform, size, size);
            img.rectTransform.sizeDelta = new Vector2(size, size);
            return img;
        }

        /// <summary>Photo or sky texture cropped to fill (cover), inside a mask so corners can round.</summary>
        public static RawImage Photo(Transform parent, string name, Texture tex, float w = -1, float h = -1)
        {
            var rt = Box(parent, name, w, h);
            var raw = rt.gameObject.AddComponent<RawImage>();
            raw.texture = tex; raw.raycastTarget = false; raw.color = Color.white;
            var fit = rt.gameObject.AddComponent<CoverFit>(); fit.raw = raw;
            return raw;
        }

        // ---- text --------------------------------------------------------------------------
        static void Apply(TMP_Text t, TextStyle s)
        {
            switch (s)
            {
                case TextStyle.Hero: Set(t, FontFace.Display, 76, 1.02f); break;
                case TextStyle.DisplayL: Set(t, FontFace.Display, ReturnType.VrDisplaySizeDp + 8, 1.05f); break;
                case TextStyle.DisplayM: Set(t, FontFace.Display, ReturnType.VrDisplaySizeDp, 1.08f); break;
                case TextStyle.Title: Set(t, FontFace.Display, 32, 1.1f); break;
                case TextStyle.H1: Set(t, FontFace.SemiBold, ReturnType.VrH1SizeDp, 1.15f); break;
                case TextStyle.H2: Set(t, FontFace.Medium, ReturnType.VrH2SizeDp, 1.2f); break;
                case TextStyle.BodyL: Set(t, FontFace.Body, 22, 1.35f); break;
                case TextStyle.Body: Set(t, FontFace.Body, ReturnType.VrBodySizeDp, 1.4f); break;
                case TextStyle.Label: Set(t, FontFace.Medium, ReturnType.VrBodySizeDp, 1.1f); break;
                case TextStyle.Caption: Set(t, FontFace.Body, ReturnType.VrCaptionSizeDp + 1, 1.35f); break;
                case TextStyle.Kicker: Set(t, FontFace.Kicker, 18, 1.1f); t.characterSpacing = 4; break;
                case TextStyle.Overline: Set(t, FontFace.SemiBold, 14, 1.1f); t.characterSpacing = 6; t.fontStyle = FontStyles.UpperCase; break;
            }
        }

        static void Set(TMP_Text t, FontFace f, float size, float lineHeight)
        {
            t.font = UIAssets.Font(f); t.fontSize = size; t.lineSpacing = (lineHeight - 1f) * 100f;
        }

        public static TextMeshProUGUI Text(Transform parent, string text, TextStyle style = TextStyle.Body, ColorRole role = ColorRole.Ink,
            TextAlignmentOptions align = TextAlignmentOptions.TopLeft, bool wrap = true)
        {
            var rt = Box(parent, "Text");
            var t = rt.gameObject.AddComponent<TextMeshProUGUI>();
            Apply(t, style);
            t.text = text; t.raycastTarget = false; t.alignment = align;
            t.textWrappingMode = wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
            t.overflowMode = TextOverflowModes.Overflow;
            t.extraPadding = false;
            var tg = rt.gameObject.AddComponent<ThemedGraphic>(); tg.role = role; tg.Refresh();
            return t;
        }

        /// <summary>Wrap a feeling word in the accent italic (Cormorant Light Italic), like the web headlines.</summary>
        public static string Em(string word) => "<font=\"" + UIAssets.AccentFontName + "\">" + word + "</font>";

        public static void SetRole(Graphic g, ColorRole role) { var tg = g.GetOrAdd<ThemedGraphic>(); tg.role = role; tg.Refresh(); }
    }

    public static class ComponentExt
    {
        /// <summary>Get or add. Never use `GetComponent ?? AddComponent`: Unity's fake-null defeats ??.</summary>
        public static T GetOrAdd<T>(this Component c) where T : Component => c.TryGetComponent(out T t) ? t : c.gameObject.AddComponent<T>();
    }

    /// <summary>Crops a RawImage to fill its rect (object-fit: cover) via uvRect.</summary>
    [ExecuteAlways, RequireComponent(typeof(RawImage))]
    public class CoverFit : MonoBehaviour
    {
        public RawImage raw;
        void OnEnable() { if (raw == null) raw = GetComponent<RawImage>(); Apply(); }
        void OnRectTransformDimensionsChange() { Apply(); }
        public void Apply()
        {
            if (raw == null || raw.texture == null) return;
            var r = ((RectTransform)transform).rect;
            if (r.width < 1 || r.height < 1) return;
            float ca = r.width / r.height, ta = (float)raw.texture.width / raw.texture.height;
            raw.uvRect = ca > ta ? new Rect(0, (1 - ta / ca) / 2f, 1, ta / ca) : new Rect((1 - ca / ta) / 2f, 0, ca / ta, 1);
        }
    }
}
