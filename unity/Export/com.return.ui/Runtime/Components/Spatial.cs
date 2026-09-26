using System;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Framed painting with scrim and a content column: kicker, headline, subline, actions. Used by hero headers.</summary>
    public static class HeroFrame
    {
        public static RectTransform Create(Transform parent, Texture image, float h, string kicker, string headline, string sub, Action<Transform> actions = null, int radius = 40)
        {
            var frame = UI.Box(parent, "HeroFrame", -1, h); UI.Size(frame, -1, h, 1);
            var clip = UI.Box(frame, "Clip"); UI.Stretch(clip); Clip.Rounded(clip, radius);
            var ph = UI.Photo(clip, "Image", image); UI.Stretch(ph.rectTransform);
            var scrim = UI.Img(clip, "Scrim", ColorRole.ImageScrim, Shapes.GradientUp, Image.Type.Simple); scrim.rectTransform.localScale = new Vector3(1, -1, 1); UI.Stretch(scrim.rectTransform);
            UI.Border(frame, ColorRole.GlassEdge, radius, 2);
            var body = UI.V(frame, "Body", 10, new RectOffset(44, 44, 0, 40), TextAnchor.LowerLeft); UI.Stretch(body);
            if (!string.IsNullOrEmpty(kicker)) UI.Text(body, kicker, TextStyle.Kicker, ColorRole.OnImage);
            if (!string.IsNullOrEmpty(headline)) UI.Text(body, headline, TextStyle.Hero, ColorRole.OnImage);
            if (!string.IsNullOrEmpty(sub)) UI.Text(body, sub, TextStyle.BodyL, ColorRole.OnImage);
            if (actions != null) { var a = UI.H(body, "Actions", 12, UI.Pad(0, 8)); var ag = a.GetComponent<HorizontalLayoutGroup>(); ag.childForceExpandWidth = false;UI.Size(a, -1, 72); actions(a); }
            return frame;
        }
    }

    /// <summary>Floating glass pill of icon buttons, anchored to the wrist or dropped in the hub.</summary>
    public static class HandMenu
    {
        public struct Item { public string icon, label; public Action onClick; public Item(string i, string l, Action c) { icon = i; label = l; onClick = c; } }

        public static RectTransform Create(Transform parent, Item[] items)
        {
            var row = UI.H(parent, "HandMenu", 8, new RectOffset(14, 14, 0, 0), TextAnchor.MiddleCenter);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(row, -1, 84);
            UI.Bg(row, ColorRole.Glass, 48); UI.Border(row, ColorRole.GlassEdge, 48, 2);
            foreach (var it in items)
            {
                var b = UI.Img(row, "Item:" + it.label, ColorRole.GlassStrong, Shapes.Pill, Image.Type.Sliced, true); UI.Size(b.rectTransform, 60, 60); b.rectTransform.sizeDelta = new Vector2(60, 60);
                UI.Icon(b.rectTransform, it.icon, ColorRole.OnGlass, 26).rectTransform.anchoredPosition = Vector2.zero;
                var p = b.gameObject.AddComponent<Pressable>(); p.onClick = it.onClick; p.hoverScale = 1.1f;
            }
            return row;
        }
    }

    /// <summary>Name tag that floats above a person's head: glass pill, avatar, name.</summary>
    public static class Nameplate
    {
        public static RectTransform Create(Transform parent, string name, bool here = true)
        {
            var row = UI.H(parent, "Nameplate:" + name, 10, new RectOffset(8, 22, 0, 0), TextAnchor.MiddleCenter);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(row, -1, 56);
            UI.Bg(row, ColorRole.Glass, 48); UI.Border(row, ColorRole.GlassEdge, 48, 2);
            Avatars.Create(row, name, 40, here, true);
            UI.Text(row, name, TextStyle.Label, ColorRole.OnGlass, TextAlignmentOptions.Left, false);
            return row;
        }

        /// <summary>Create a small world-space plate above a transform (head), at ReturnSpatial.NameplateOffset.</summary>
        public static SpatialPanel Attach(Transform head, string name)
        {
            var p = SpatialPanel.Create("Nameplate", 320, 72, head);
            p.transform.localPosition = new Vector3(0, ReturnSpatial.NameplateOffset, 0);
            p.transform.localScale = Vector3.one * 0.0016f;
            var n = Create(p.rect, name); UI.Anchor(n, new Vector2(0.5f, 0.5f), Vector2.zero);
            p.gameObject.AddComponent<Billboard>();
            return p;
        }
    }

    public class Billboard : MonoBehaviour
    {
        void LateUpdate() { var c = Camera.main; if (c != null) transform.rotation = Quaternion.LookRotation(transform.position - c.transform.position); }
    }

    /// <summary>The arched painted window inside a UI panel. Click for a glimpse (white-out pulse); "inside" is headset only.</summary>
    public static class PortalWindow
    {
        static Sprite _arch;
        public static Sprite Arch()
        {
            if (_arch != null) return _arch;
            const int w = 256, h = 342;
            var t = new Texture2D(w, h, TextureFormat.RGBA32, false) { hideFlags = HideFlags.HideAndDontSave, wrapMode = TextureWrapMode.Clamp };
            float r = w / 2f;
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    float d;
                    float cy = h - r; // circle center (y up)
                    if (y >= cy) d = new Vector2(x + 0.5f - r, y + 0.5f - cy).magnitude - r; else d = Mathf.Abs(x + 0.5f - r) - r;
                    t.SetPixel(x, y, new Color32(255, 255, 255, (byte)(Mathf.Clamp01(0.5f - d) * 255)));
                }
            t.Apply();
            return _arch = Sprite.Create(t, new Rect(0, 0, w, h), Vector2.one * 0.5f, 1);
        }

        public static RectTransform Create(Transform parent, Texture image, float w, float h, Action onClick, string label = null)
        {
            var win = UI.Box(parent, "PortalWindow", w, h); UI.Size(win, w, h);
            var clip = UI.Box(win, "Clip"); UI.Stretch(clip);
            var m = clip.gameObject.AddComponent<Mask>(); var mi = clip.gameObject.AddComponent<Image>(); mi.sprite = Arch(); mi.type = Image.Type.Simple; m.showMaskGraphic = false;
            var ph = UI.Photo(clip, "Image", image); UI.Stretch(ph.rectTransform);
            var flash = UI.Img(clip, "Flash", ColorRole.OnImage, Shapes.White); UI.Stretch(flash.rectTransform); flash.color = new Color(1, 1, 1, 0); flash.GetComponent<ThemedGraphic>().enabled = false;
            var ring = UI.Img(win, "Edge", ColorRole.GlassEdge, Arch(), Image.Type.Simple); UI.Stretch(ring.rectTransform); ring.color = new Color(1, 1, 1, 0.0f);
            var hit = UI.Img(win, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform);
            var bob = win.gameObject.AddComponent<Bob>(); bob.amplitude = ReturnSpatial.PortalBob * 1000f * 0.5f;
            var pr = win.gameObject.AddComponent<Pressable>(); pr.hoverScale = 1.03f;
            pr.onClick = () => { win.gameObject.AddComponent<FlashPulse>().Run(flash, ReturnMotion.Enter * 0.6f); onClick?.Invoke(); };
            return win;
        }
    }

    public class Bob : MonoBehaviour
    {
        public float amplitude = 10f; Vector2 _base; bool _init;
        void Update()
        {
            var rt = (RectTransform)transform;
            if (!_init) { _base = rt.anchoredPosition; _init = true; }
            // 2cm over 6s; layout groups own position, so bob via the child offset when free
            if (GetComponentInParent<LayoutGroup>() == null) rt.anchoredPosition = _base + Vector2.up * Mathf.Sin(Time.unscaledTime * Mathf.PI * 2f / 6f) * amplitude;
        }
    }

    public class FlashPulse : MonoBehaviour
    {
        Image _img; float _t, _dur;
        public void Run(Image img, float dur) { _img = img; _dur = dur; _t = 0; }
        void Update()
        {
            if (_img == null) { Destroy(this); return; }
            _t += Time.unscaledDeltaTime; float k = Mathf.Clamp01(_t / _dur);
            _img.color = new Color(1, 1, 1, Mathf.Sin(k * Mathf.PI) * 0.85f);
            if (k >= 1f) Destroy(this);
        }
    }
}
