using System;
using System.Collections.Generic;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Shared screen furniture: account nav, scroll body, padded sections, room helpers.</summary>
    public abstract class RoutedScreen : Screen, IRouted
    {
        public string Id { get; set; }
        protected Room Room => Id != null ? app.store.Get(Id) : null;
        protected Who[] People(Room r) => r.members.Select(m => new Who(m.name)).ToArray();

        /// <summary>Vertical scroll area filling the screen below `top`. Returns the content rect (a V layout that grows).</summary>
        protected RectTransform Scroll(float top, RectOffset pad, float spacing)
        {
            var sv = UI.Box(root, "Scroll"); UI.Stretch(sv, 0, 0, 0, top);
            var view = UI.Box(sv, "Viewport"); UI.Stretch(view); view.gameObject.AddComponent<RectMask2D>();
            var content = UI.V(view, "Content", spacing, pad);
            content.anchorMin = new Vector2(0, 1); content.anchorMax = new Vector2(1, 1); content.pivot = new Vector2(0.5f, 1); content.sizeDelta = Vector2.zero;
            UI.Fit(content);
            var sr = sv.gameObject.AddComponent<ScrollRect>();
            sr.viewport = view; sr.content = content; sr.horizontal = false; sr.vertical = true; sr.movementType = ScrollRect.MovementType.Elastic; sr.scrollSensitivity = 40;
            var bg = UI.Img(sv, "ScrollHit", ColorRole.Ink, null, Image.Type.Simple, true); bg.color = new Color(0, 0, 0, 0); bg.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(bg.rectTransform); bg.transform.SetAsFirstSibling();
            return content;
        }

        /// <summary>Top nav (glass pill). active = "rooms" highlights that item.</summary>
        protected RectTransform Nav(string active = null, bool showRooms = true)
        {
            var wrap = UI.Box(root, "NavWrap"); wrap.anchorMin = new Vector2(0, 1); wrap.anchorMax = new Vector2(1, 1); wrap.pivot = new Vector2(0.5f, 1);
            wrap.sizeDelta = new Vector2(-64, 68); wrap.anchoredPosition = new Vector2(0, -28);
            var items = showRooms ? new[] { new NavItem("Rooms", () => app.router.Go(Route.Dashboard), active == "rooms") } : new NavItem[0];
            var nav = GlassNav.Create(wrap, items, row =>
            {
                if (!app.store.SignedIn) return;
                var acct = UI.H(row, "Account", 10, new RectOffset(6, 18, 0, 0), TextAnchor.MiddleCenter);
                var g = acct.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(acct, -1, 52);
                UI.Bg(acct, ColorRole.GlassStrong, 48);
                Avatars.Create(acct, RoomLogic.Me.name, 40, false, false);
                UI.Text(acct, RoomLogic.Me.name.Split(' ')[0], TextStyle.Label, ColorRole.Ink, TextAlignmentOptions.Left, false);
                var hit = UI.Img(acct, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);
                acct.gameObject.AddComponent<Pressable>().onClick = ShowAccount;
            });
            UI.Stretch(nav);
            return wrap;
        }

        void ShowAccount()
        {
            var sheet = Sheet.Show(root, 420);
            var t = UI.Text(sheet.content, "Signed in as " + UI.Em(RoomLogic.Me.name.Split(' ')[0]), TextStyle.Title, ColorRole.Ink); t.fontSize = 32;
            UI.Text(sheet.content, RoomLogic.Me.email, TextStyle.Caption, ColorRole.InkMuted);
            bool dusk = ThemeManager.Current == ReturnTheme.Dusk;
            RButton.Create(sheet.content, dusk ? "Switch to Day" : "Switch to Dusk", BtnVariant.Secondary, BtnSize.Md, dusk ? "sun" : "moon", fullWidth: true,
                onClick: () => { ThemeManager.SetOverride(dusk ? ReturnTheme.Day : ReturnTheme.Dusk); sheet.Close(); });
            RButton.Create(sheet.content, "Sign out", BtnVariant.Ghost, BtnSize.Md, fullWidth: true, onClick: () => { sheet.Close(); app.store.SignOut(); app.router.Go(Route.Landing); });
        }

        protected static RectTransform Row(Transform p, float spacing = 12, float h = 56, TextAnchor a = TextAnchor.MiddleLeft)
        {
            var r = UI.H(p, "Row", spacing, null, a); var g = r.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(r, -1, h); return r;
        }

        /// <summary>Glass-strong container card.</summary>
        protected static RectTransform Card(Transform p, float pad = 32, float spacing = 16, int radius = 36)
        {
            var c = UI.V(p, "Card", spacing, UI.Pad((int)pad));
            UI.Bg(c, ColorRole.GlassStrong, radius); UI.Border(c, ColorRole.GlassEdge, radius, 2);
            return c;
        }

        protected static RectTransform Column(Transform p, float w, float spacing = 16)
        {
            var c = UI.V(p, "Column", spacing); UI.Size(c, w, -1); return c;
        }

        protected static string Sig(IEnumerable<Room> rooms) => string.Join("|", rooms.Select(r => r.id + r.phase + r.title + string.Join(",", r.members.Select(m => m.id + m.status + m.count))));
    }
}
