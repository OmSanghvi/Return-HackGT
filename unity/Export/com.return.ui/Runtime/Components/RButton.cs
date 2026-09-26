using System;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public enum BtnVariant { Primary, Secondary, Ghost, Danger, Light, Glass, Text }
    public enum BtnSize { Sm, Md, Lg }

    /// <summary>Port of the web Button. Min hit target 48dp.</summary>
    public class RButton : MonoBehaviour
    {
        public Pressable press;
        public TextMeshProUGUI label;
        public RectTransform icon;
        Image _leadIcon;
        bool _loading; string _iconName;

        public static RButton Create(Transform parent, string text, BtnVariant variant = BtnVariant.Secondary, BtnSize size = BtnSize.Md,
            string icon = null, string iconAfter = null, bool arrow = false, bool fullWidth = false, Action onClick = null)
        {
            float h = size == BtnSize.Sm ? 48 : size == BtnSize.Md ? 56 : 64;
            var rt = UI.H(parent, "Button:" + text, 10, new RectOffset(size == BtnSize.Sm ? 20 : 28, arrow ? 8 : (size == BtnSize.Sm ? 20 : 28), 0, 0), TextAnchor.MiddleCenter);
            UI.Size(rt, -1, h, fullWidth ? 1 : -1);
            var hg = rt.GetComponent<HorizontalLayoutGroup>(); hg.childForceExpandWidth = false; hg.childForceExpandHeight = false;
            var b = rt.gameObject.AddComponent<RButton>();

            ColorRole bg, fg, edge = ColorRole.Line; bool border = false, fill = true;
            switch (variant)
            {
                case BtnVariant.Primary: bg = ColorRole.Action; fg = ColorRole.OnAction; break;
                case BtnVariant.Danger: bg = ColorRole.Danger; fg = ColorRole.OnImage; break;
                case BtnVariant.Light: bg = ColorRole.OnImage; fg = ColorRole.OnLight; break;
                case BtnVariant.Glass: bg = ColorRole.Glass; fg = ColorRole.OnGlass; edge = ColorRole.GlassEdge; border = true; break;
                case BtnVariant.Secondary: bg = ColorRole.Surface200; fg = ColorRole.Ink; edge = ColorRole.LineStrong; border = true; break;
                case BtnVariant.Ghost: bg = ColorRole.Surface300; fg = ColorRole.Ink; fill = false; break;
                default: bg = ColorRole.Surface300; fg = ColorRole.Sky; fill = false; break;
            }
            int radius = 48;
            if (fill) UI.Bg(rt, bg, radius); else { var g = UI.Bg(rt, ColorRole.Surface300, radius); g.color = new Color(0, 0, 0, 0); b.hoverFill = g; b.hoverFillRole = ColorRole.Surface300; g.GetComponent<ThemedGraphic>().enabled = false; }
            if (border) UI.Border(rt, edge, radius, 2);
            // the whole button is the hit target
            var hit = UI.Img(rt, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false;
            UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);

            float isz = size == BtnSize.Sm ? 18 : 22;
            b._iconName = icon;
            if (icon != null) { b._leadIcon = UI.Icon(rt, icon, fg, isz); b.icon = b._leadIcon.rectTransform; }
            b.label = UI.Text(rt, text, TextStyle.Label, fg, TextAlignmentOptions.Center, false);
            if (size == BtnSize.Sm) b.label.fontSize = 16;
            if (size == BtnSize.Lg) b.label.fontSize = 20;
            if (iconAfter != null) UI.Icon(rt, iconAfter, fg, isz);
            if (arrow)
            {
                var dot = UI.Img(rt, "Dot", variant == BtnVariant.Primary ? ColorRole.OnAction : ColorRole.Action, Shapes.Pill, Image.Type.Sliced);
                UI.Size(dot.rectTransform, h - 16, h - 16);
                var ai = UI.Icon(dot.rectTransform, "arrowRight", variant == BtnVariant.Primary ? ColorRole.Action : ColorRole.OnAction, 20);
                UI.Anchor(ai.rectTransform, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(20, 20));
                ai.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            }

            b.press = rt.gameObject.AddComponent<Pressable>();
            b.press.onClick = onClick;
            return b;
        }

        Image hoverFill; ColorRole hoverFillRole;

        void Update()
        {
            if (hoverFill != null && press != null)
            {
                var c = ThemedGraphic.Resolve(ThemeManager.Palette, hoverFillRole);
                hoverFill.color = Color.Lerp(hoverFill.color, press.Hover && press.interactable ? (Color)c : new Color(c.r / 255f, c.g / 255f, c.b / 255f, 0), 0.35f);
            }
        }

        public bool Interactable { get => press.interactable; set => press.interactable = value; }
        public void SetText(string t) { label.text = t; }

        /// <summary>Swap the lead icon for a spinner while busy.</summary>
        public void SetLoading(bool on)
        {
            if (_loading == on) return; _loading = on; press.interactable = !on;
            if (_leadIcon == null)
            {
                if (!on) return;
                var s = UI.Icon(transform, "spinner", ColorRole.OnAction, 20); s.transform.SetAsFirstSibling();
                s.gameObject.name = "Spinner"; s.gameObject.AddComponent<Spin>(); _leadIcon = s; _iconName = null; return;
            }
            _leadIcon.sprite = UIAssets.Icon(on ? "spinner" : _iconName);
            var sp = _leadIcon.GetComponent<Spin>();
            if (on && sp == null) _leadIcon.gameObject.AddComponent<Spin>();
            if (!on && sp != null) { Destroy(sp); _leadIcon.transform.localRotation = Quaternion.identity; }
        }

        public void SetVisible(bool v) => gameObject.SetActive(v);
    }
}
