using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public struct Who { public string name; public bool here; public Who(string n, bool h = false) { name = n; here = h; } }

    public static class Avatars
    {
        public static string Initials(string n)
        {
            if (string.IsNullOrWhiteSpace(n)) return "?";
            var parts = n.Trim().Split(new[] { ' ' }, System.StringSplitOptions.RemoveEmptyEntries);
            var s = ""; foreach (var p in parts) s += char.ToUpperInvariant(p[0]);
            return s.Length > 2 ? s.Substring(0, 2) : s;
        }

        /// <summary>Round initials chip. The connective color (aurora) is only for people.</summary>
        public static RectTransform Create(Transform parent, string name, float size = 44, bool here = false, bool onImage = false)
        {
            var bg = UI.Img(parent, "Avatar", onImage ? ColorRole.GlassStrong : ColorRole.AuroraSoft, Shapes.Pill, Image.Type.Sliced);
            UI.Size(bg.rectTransform, size, size); bg.rectTransform.sizeDelta = new Vector2(size, size);
            var t = UI.Text(bg.rectTransform, Initials(name), TextStyle.Label, onImage ? ColorRole.Ink : ColorRole.Aurora, TextAlignmentOptions.Center, false);
            t.fontSize = Mathf.Max(12, size * 0.36f); UI.Stretch(t.rectTransform);
            if (here) UI.Border(bg.rectTransform, ColorRole.Aurora, 48, 3);
            else UI.Border(bg.rectTransform, onImage ? ColorRole.OnImage : ColorRole.Surface100, 48, 2);
            return bg.rectTransform;
        }
    }

    /// <summary>Overlapping avatars, "+N", and an optional "N here now" label.</summary>
    public static class PresenceStack
    {
        public static RectTransform Create(Transform parent, Who[] people, int max = 4, float size = 44, bool showLabel = false, bool onImage = false)
        {
            var row = UI.H(parent, "PresenceStack", -size * 0.28f, null, TextAnchor.MiddleLeft);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;g.childControlWidth = false;
            int shown = Mathf.Min(max, people.Length), here = 0;
            foreach (var p in people) if (p.here) here++;
            for (int i = 0; i < shown; i++) Avatars.Create(row, people[i].name, size, people[i].here, onImage);
            if (people.Length > shown)
            {
                var more = UI.Img(row, "More", ColorRole.Surface300, Shapes.Pill, Image.Type.Sliced);
                UI.Size(more.rectTransform, size, size); more.rectTransform.sizeDelta = new Vector2(size, size);
                var t = UI.Text(more.rectTransform, "+" + (people.Length - shown), TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Center, false); UI.Stretch(t.rectTransform);
            }
            if (showLabel && here > 0)
            {
                var sp = UI.Spacer(row, size * 0.28f + 12);
                UI.Text(row, here + " here now", TextStyle.Caption, onImage ? ColorRole.OnImage : ColorRole.Aurora, TextAlignmentOptions.Left, false);
            }
            return row;
        }
    }
}
