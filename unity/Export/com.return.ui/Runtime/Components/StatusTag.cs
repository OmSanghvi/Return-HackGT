using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public enum RoomStatus { New, Invited, Waiting, Developing, Ready, Shared, Private, Failed }

    /// <summary>Icon plus word, never color alone.</summary>
    public static class StatusTag
    {
        public static string Word(RoomStatus s)
        {
            switch (s)
            {
                case RoomStatus.Developing: return "Building";
                case RoomStatus.Waiting: return "Waiting";
                case RoomStatus.Invited: return "Invitation";
                case RoomStatus.Ready: return "Ready";
                case RoomStatus.Shared: return "Shared";
                case RoomStatus.Private: return "Private";
                case RoomStatus.Failed: return "Couldn't build";
                default: return "New";
            }
        }

        static string IconFor(RoomStatus s)
        {
            switch (s)
            {
                case RoomStatus.Developing: return "spinner";
                case RoomStatus.Waiting: case RoomStatus.Shared: return "people";
                case RoomStatus.Invited: return "mail";
                case RoomStatus.Ready: return "check";
                case RoomStatus.Private: return "lock";
                case RoomStatus.Failed: return "alert";
                default: return "sun";
            }
        }

        static void Roles(RoomStatus s, out ColorRole bg, out ColorRole fg)
        {
            switch (s)
            {
                case RoomStatus.Developing: bg = ColorRole.SunSoft; fg = ColorRole.Sun; break;
                case RoomStatus.Waiting: case RoomStatus.Shared: bg = ColorRole.AuroraSoft; fg = ColorRole.Aurora; break;
                case RoomStatus.Invited: bg = ColorRole.BlossomSoft; fg = ColorRole.Blossom; break;
                case RoomStatus.Ready: bg = ColorRole.SuccessSoft; fg = ColorRole.Success; break;
                case RoomStatus.Failed: bg = ColorRole.DangerSoft; fg = ColorRole.Danger; break;
                case RoomStatus.Private: bg = ColorRole.Surface300; fg = ColorRole.InkMuted; break;
                default: bg = ColorRole.SkySoft; fg = ColorRole.Sky; break;
            }
        }

        public static RectTransform Create(Transform parent, RoomStatus status, string text = null, bool onImage = false)
        {
            Roles(status, out var bg, out var fg);
            if (onImage) { bg = ColorRole.Glass; fg = ColorRole.OnGlass; }
            var row = UI.H(parent, "StatusTag", 6, new RectOffset(12, 14, 0, 0), TextAnchor.MiddleCenter);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;
            UI.Size(row, -1, 34);
            UI.Bg(row, bg, 48);
            if (onImage) UI.Border(row, ColorRole.GlassEdge, 48, 2);
            var ic = UI.Icon(row, IconFor(status), fg, 16);
            if (status == RoomStatus.Developing) ic.gameObject.AddComponent<Spin>();
            var t = UI.Text(row, text ?? Word(status), TextStyle.Caption, fg, TextAlignmentOptions.Left, false);
            t.fontSize = 14; t.font = UIAssets.Font(FontFace.SemiBold);
            return row;
        }
    }
}
