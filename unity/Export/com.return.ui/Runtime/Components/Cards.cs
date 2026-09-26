using System;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Clip children to a rounded rect (photos in cards, portals).</summary>
    public static class Clip
    {
        public static Image Rounded(RectTransform rt, int radius)
        {
            var mask = rt.GetOrAdd<Mask>();
            var img = rt.GetOrAdd<Image>();
            img.sprite = Shapes.Rounded(radius); img.type = Image.Type.Sliced; img.color = Color.white;
            mask.showMaskGraphic = false;
            return img;
        }
    }

    public static class RoomCard
    {
        public const float W = 372, H = 296;

        public static Texture CoverOf(Room r)
        {
            if (!string.IsNullOrEmpty(r.cover) && Enum.TryParse<SceneKey>(r.cover, out var k)) return UIAssets.Sky(k);
            return UIAssets.Sky(r.scene);
        }

        /// <summary>Photo card: status tag, manage button, title, meta, presence, optional action buttons. onManage null hides the menu button.</summary>
        public static RectTransform Create(Transform parent, Texture cover, string title, string meta, RoomStatus? status, string statusText,
            Who[] people, Action onOpen, Action onManage = null, Action<Transform> actions = null)
        {
            var card = UI.Box(parent, "RoomCard:" + title, W, H);
            UI.Size(card, W, H);
            var clip = UI.Box(card, "Clip"); UI.Stretch(clip); Clip.Rounded(clip, 32);
            var photo = UI.Photo(clip, "Photo", cover); UI.Stretch(photo.rectTransform);
            var scrim = UI.Img(clip, "Scrim", ColorRole.ImageScrimStrong, Shapes.GradientUp, Image.Type.Simple);
            var sr = scrim.rectTransform; sr.anchorMin = new Vector2(0, 0); sr.anchorMax = new Vector2(1, 0.7f); sr.offsetMin = sr.offsetMax = Vector2.zero;
            scrim.transform.localScale = new Vector3(1, -1, 1); // gradient: opaque at the bottom
            UI.Border(card, ColorRole.GlassEdge, 32, 2);

            var hit = UI.Img(card, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false;
            UI.Stretch(hit.rectTransform);
            var pr = card.gameObject.AddComponent<Pressable>(); pr.onClick = onOpen; pr.hoverScale = 1.025f;

            var top = UI.H(card, "Top", 8, UI.Pad(16, 16), TextAnchor.UpperLeft);
            UI.Stretch(top); top.offsetMin = new Vector2(0, H - 72); var tg = top.GetComponent<HorizontalLayoutGroup>(); tg.childForceExpandWidth = false;tg.childAlignment = TextAnchor.UpperLeft;
            top.offsetMax = Vector2.zero; top.sizeDelta = new Vector2(0, 72); top.anchorMin = new Vector2(0, 1); top.anchorMax = new Vector2(1, 1); top.pivot = new Vector2(0.5f, 1); top.anchoredPosition = Vector2.zero;
            if (status.HasValue) StatusTag.Create(top, status.Value, statusText, true);
            UI.Spacer(top, 0, 0, true);
            if (onManage != null)
            {
                var m = UI.Img(top, "Manage", ColorRole.Glass, Shapes.Pill, Image.Type.Sliced, true);
                UI.Size(m.rectTransform, 44, 44); m.rectTransform.sizeDelta = new Vector2(44, 44);
                UI.Icon(m.rectTransform, "more", ColorRole.OnGlass, 20).rectTransform.anchoredPosition = Vector2.zero;
                m.gameObject.AddComponent<Pressable>().onClick = onManage;
            }

            var foot = UI.V(card, "Foot", 4, new RectOffset(20, 20, 0, 18), TextAnchor.LowerLeft);
            foot.anchorMin = new Vector2(0, 0); foot.anchorMax = new Vector2(1, 0); foot.pivot = new Vector2(0.5f, 0); foot.anchoredPosition = Vector2.zero; foot.sizeDelta = new Vector2(0, 0); UI.Fit(foot);
            var row = UI.H(foot, "Row", 12, null, TextAnchor.LowerLeft);
            var rg = row.GetComponent<HorizontalLayoutGroup>(); rg.childForceExpandWidth = false; rg.childControlHeight = true; rg.childForceExpandHeight = false;
            var col = UI.V(row, "Col", 2); UI.Size(col, -1, -1, 1);
            var tt = UI.Text(col, title, TextStyle.Title, ColorRole.OnImage, TextAlignmentOptions.BottomLeft, true); tt.fontSize = 30; tt.overflowMode = TextOverflowModes.Ellipsis; tt.maxVisibleLines = 2;
            if (!string.IsNullOrEmpty(meta)) UI.Text(col, meta, TextStyle.Caption, ColorRole.OnImage, TextAlignmentOptions.BottomLeft, true);
            if (people != null && people.Length > 0) PresenceStack.Create(row, people, 3, 40, false, true);
            if (actions != null)
            {
                var ar = UI.H(foot, "Actions", 10, UI.Pad(0, 8), TextAnchor.MiddleLeft);
                var ag = ar.GetComponent<HorizontalLayoutGroup>(); ag.childForceExpandWidth = false;UI.Size(ar, -1, 64);
                actions(ar);
            }
            return card;
        }
    }

    public struct MemberRow
    {
        public string name, email, sentAgo; public MemberStatus status; public int count; public bool hasNote, isYou, isOwner, uploading;
    }

    public static class MemberList
    {
        static string Line(MemberRow m)
        {
            if (m.uploading) return "Adding photos";
            switch (m.status)
            {
                case MemberStatus.Done: return "Added " + m.count + " photo" + (m.count == 1 ? "" : "s") + (m.hasNote ? " and a note" : "");
                case MemberStatus.Joined: return "Joined, hasn't added photos yet";
                default: return "Invite sent" + (string.IsNullOrEmpty(m.sentAgo) ? "" : " " + m.sentAgo);
            }
        }

        static string IconFor(MemberRow m) => m.uploading ? "spinner" : m.status == MemberStatus.Done ? "check" : m.status == MemberStatus.Joined ? "clock" : "mail";

        public static RectTransform Create(Transform parent, MemberRow[] rows, Action<MemberRow> onResend = null)
        {
            var list = UI.V(parent, "MemberList", 4);
            foreach (var m in rows)
            {
                var row = UI.H(list, "Member:" + m.name, 14, new RectOffset(4, 4, 6, 6), TextAnchor.MiddleLeft);
                var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false; g.childControlHeight = true; g.childForceExpandHeight = false;
                UI.Size(row, -1, 68);
                Avatars.Create(row, m.name ?? m.email, 48);
                var col = UI.V(row, "Col", 2, null, TextAnchor.MiddleLeft); UI.Size(col, -1, -1, 1);
                UI.Text(col, (m.name ?? m.email) + (m.isYou ? " (you)" : ""), TextStyle.Label, ColorRole.Ink, TextAlignmentOptions.Left, false);
                var sub = UI.H(col, "Sub", 6, null, TextAnchor.MiddleLeft); var sg = sub.GetComponent<HorizontalLayoutGroup>(); sg.childForceExpandWidth = false;UI.Size(sub, -1, 22);
                var role = m.status == MemberStatus.Done ? ColorRole.Success : ColorRole.InkMuted;
                var ic = UI.Icon(sub, IconFor(m), role, 14); if (m.uploading) ic.gameObject.AddComponent<Spin>();
                UI.Text(sub, Line(m), TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Left, false);
                if (m.status == MemberStatus.Invited && onResend != null) { var mm = m; RButton.Create(row, "Resend", BtnVariant.Ghost, BtnSize.Sm, "refresh", onClick: () => onResend(mm)); }
                else if (m.isOwner) UI.Text(row, "Owner", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Right, false);
            }
            return list;
        }
    }
}
