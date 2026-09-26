using System;
using System.Collections.Generic;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Thin progress track. Fill grows with Value 0..1.</summary>
    public class Bar : MonoBehaviour
    {
        RectTransform _fill; Image _fillImg;
        public static Bar Create(Transform parent, ColorRole fill = ColorRole.Sun, float h = 8)
        {
            var rt = UI.Box(parent, "Bar", -1, h); UI.Size(rt, -1, h, 1);
            var b = rt.gameObject.AddComponent<Bar>();
            UI.Bg(rt, ColorRole.Surface300, 48);
            b._fillImg = UI.Img(rt, "Fill", fill, Shapes.Pill, Image.Type.Sliced);
            b._fill = b._fillImg.rectTransform;
            b._fill.anchorMin = Vector2.zero; b._fill.anchorMax = new Vector2(0, 1); b._fill.pivot = new Vector2(0, 0.5f);
            b._fill.offsetMin = b._fill.offsetMax = Vector2.zero;
            UI.Overlay(b._fill);
            return b;
        }
        public void Set(float v, ColorRole? role = null)
        {
            _fill.anchorMax = new Vector2(Mathf.Clamp01(v), 1); _fill.offsetMin = _fill.offsetMax = Vector2.zero;
            if (role.HasValue) UI.SetRole(_fillImg, role.Value);
        }
    }

    public static class Eyebrow
    {
        /// <summary>Glass pill with an optional bold badge, e.g. [Ready] Built from 15 photos.</summary>
        public static RectTransform Create(Transform parent, string badge, string text)
        {
            var holder = UI.H(parent, "EyebrowRow", 0, null, TextAnchor.MiddleLeft); UI.Size(holder, -1, 40);
            var row = UI.H(holder, "Eyebrow", 10, new RectOffset(16, 18, 0, 0), TextAnchor.MiddleCenter);
            UI.Size(row, -1, 40);
            UI.Bg(row, ColorRole.Glass, 48); UI.Border(row, ColorRole.GlassEdge, 48, 2);
            if (!string.IsNullOrEmpty(badge)) { var b = UI.Text(row, badge, TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Left, false); b.font = UIAssets.Font(FontFace.SemiBold); }
            UI.Text(row, text, TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Left, false);
            return row;
        }
    }

    public static class Stepper
    {
        public static readonly string[] RoomSteps = { "Name and invite", "Add your photos", "Wait for everyone" };

        public static RectTransform Create(Transform parent, int current, string[] steps = null, bool onImage = false)
        {
            steps = steps ?? RoomSteps;
            var row = UI.H(parent, "Stepper", 22, null, TextAnchor.MiddleLeft);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;
            UI.Size(row, -1, 32);
            for (int i = 0; i < steps.Length; i++)
            {
                var item = UI.H(row, "Step" + i, 10, null, TextAnchor.MiddleLeft);
                var ig = item.GetComponent<HorizontalLayoutGroup>(); ig.childForceExpandWidth = false;
                bool done = i < current, now = i == current;
                var dot = UI.Img(item, "Dot", done ? ColorRole.Success : now ? ColorRole.Action : ColorRole.Surface300, Shapes.Pill, Image.Type.Sliced);
                UI.Size(dot.rectTransform, 30, 30); dot.rectTransform.sizeDelta = new Vector2(30, 30);
                if (done) UI.Icon(dot.rectTransform, "check", ColorRole.OnImage, 16);
                else { var n = UI.Text(dot.rectTransform, (i + 1).ToString(), TextStyle.Caption, now ? ColorRole.OnAction : ColorRole.InkMuted, TextAlignmentOptions.Center, false); UI.Stretch(n.rectTransform); }
                UI.Text(item, steps[i], TextStyle.Caption, now ? (onImage ? ColorRole.OnImage : ColorRole.Ink) : (onImage ? ColorRole.OnImage : ColorRole.InkMuted), TextAlignmentOptions.Left, false);
            }
            return row;
        }
    }

    public struct NavItem { public string label; public bool active; public Action onClick; public NavItem(string l, Action c, bool a = false) { label = l; onClick = c; active = a; } }

    /// <summary>Floating glass pill: brand, items, CTA slot.</summary>
    public static class GlassNav
    {
        public static RectTransform Create(Transform parent, NavItem[] items, Action<Transform> cta = null, bool plain = false, bool withBrand = true)
        {
            var row = UI.H(parent, "GlassNav", 8, new RectOffset(28, 12, 0, 0), TextAnchor.MiddleLeft);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;
            UI.Size(row, -1, 68);
            if (plain) { UI.Bg(row, ColorRole.Surface200, 48); UI.Border(row, ColorRole.Line, 48, 2); }
            else { UI.Bg(row, ColorRole.Glass, 48); UI.Border(row, ColorRole.GlassEdge, 48, 2); }
            var ink = plain ? ColorRole.Ink : ColorRole.OnGlass;
            if (withBrand)
            {
                var logo = UI.Img(row, "Brand", ColorRole.Ink, UIAssets.Logo(plain ? "return-lockup-ink" : "return-lockup-ink"));
                logo.preserveAspect = true; UI.Size(logo.rectTransform, 110, 28); logo.rectTransform.sizeDelta = new Vector2(110, 28);
                logo.color = Color.white; logo.GetComponent<ThemedGraphic>().enabled = false;
                UI.Spacer(row, 16);
            }
            foreach (var it in items)
            {
                var b = UI.H(row, "Nav:" + it.label, 0, new RectOffset(18, 18, 0, 0), TextAnchor.MiddleCenter);
                UI.Size(b, -1, 48);
                var bg = UI.Bg(b, it.active ? ColorRole.Surface300 : ColorRole.Surface300, 48);
                if (!it.active) { bg.GetComponent<ThemedGraphic>().enabled = false; bg.color = new Color(0, 0, 0, 0); }
                var hit = UI.Img(b, "Hit", ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);
                var t = UI.Text(b, it.label, TextStyle.Label, ink, TextAlignmentOptions.Center, false);
                if (it.active) t.font = UIAssets.Font(FontFace.SemiBold);
                b.gameObject.AddComponent<Pressable>().onClick = it.onClick;
            }
            UI.Spacer(row, 0, 0, true);
            cta?.Invoke(row);
            return row;
        }
    }

    /// <summary>Modal card over a dim scrim inside a panel. One at a time.</summary>
    public class Sheet : MonoBehaviour
    {
        public RectTransform content;
        public static Sheet Show(RectTransform panelRoot, float width = 620)
        {
            var root = UI.Box(panelRoot, "Sheet"); UI.Stretch(root);
            root.gameObject.AddComponent<Canvas>().overrideSorting = true;
            root.GetComponent<Canvas>().sortingOrder = 50;
            root.gameObject.AddComponent<GraphicRaycaster>();
            var s = root.gameObject.AddComponent<Sheet>();
            var dim = UI.Img(root, "Dim", ColorRole.ImageScrimStrong, null, Image.Type.Simple, true); UI.Stretch(dim.rectTransform);
            dim.gameObject.AddComponent<Pressable>().hoverScale = 1f;
            dim.GetComponent<Pressable>().pressScale = 1f;
            dim.GetComponent<Pressable>().onClick = s.Close;
            var card = UI.V(root, "Card", 18, UI.Pad(32), TextAnchor.UpperLeft);
            card.anchorMin = card.anchorMax = card.pivot = new Vector2(0.5f, 0.5f);
            card.sizeDelta = new Vector2(width, 0); UI.Fit(card);
            UI.Bg(card, ColorRole.GlassStrong, 32); UI.Border(card, ColorRole.GlassEdge, 32, 2);
            // swallow clicks on the card itself
            var eat = UI.Img(card, "Eat", ColorRole.Ink, null, Image.Type.Simple, true); eat.color = new Color(0, 0, 0, 0); eat.GetComponent<ThemedGraphic>().enabled = false;
            UI.Stretch(eat.rectTransform); UI.Overlay(eat.rectTransform); eat.rectTransform.SetAsFirstSibling();
            s.content = card;
            return s;
        }
        public void Close() { Destroy(gameObject); }
    }

    /// <summary>Button that asks first: click reveals "text" with Yes/No inline.</summary>
    public static class ConfirmButton
    {
        public static RectTransform Create(Transform parent, string label, string confirmText, Action onConfirm, bool arrow = true)
        {
            var holder = UI.H(parent, "Confirm", 12, null, TextAnchor.MiddleRight);
            var g = holder.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(holder, -1, 56);
            RButton start = null; RectTransform ask = null;
            start = RButton.Create(holder, label, BtnVariant.Secondary, BtnSize.Md, arrow: arrow, onClick: () => { start.gameObject.SetActive(false); ask.gameObject.SetActive(true); });
            ask = UI.H(holder, "Ask", 12, null, TextAnchor.MiddleRight);
            var ag = ask.GetComponent<HorizontalLayoutGroup>(); ag.childForceExpandWidth = false;
            UI.Text(ask, confirmText, TextStyle.Caption, ColorRole.Ink, TextAlignmentOptions.Left, false);
            RButton.Create(ask, "Cancel", BtnVariant.Ghost, BtnSize.Sm, onClick: () => { ask.gameObject.SetActive(false); start.gameObject.SetActive(true); });
            RButton.Create(ask, "Yes, start", BtnVariant.Primary, BtnSize.Sm, onClick: () => onConfirm?.Invoke());
            ask.gameObject.SetActive(false);
            return holder;
        }
    }
}
