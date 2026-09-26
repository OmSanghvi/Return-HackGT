using System;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>One room on the ring: the painted arched window, and a small glass label under it (title, state, presence, invite buttons).</summary>
    public class PortalCard : MonoBehaviour
    {
        public string roomId;
        public RoomPortal portal;
        public SpatialPanel label;
        string _sig;
        Bar _bar;

        public static PortalCard Create(Transform ring, Room room, IRoomStore store, ScreenRouter router, Action<Room> onActivate)
        {
            var anchor = new GameObject("Portal:" + room.id); anchor.transform.SetParent(ring, false);
            var c = anchor.AddComponent<PortalCard>(); c.roomId = room.id;
            c.portal = RoomPortal.Create(anchor.transform, room, new Vector3(0, 1.35f, 0));
            c.portal.Activated += _ => { var r = store.Get(c.roomId); if (r != null) onActivate(r); };
            c.label = SpatialPanel.Create("Label", 420, 250, anchor.transform);
            c.label.transform.localPosition = new Vector3(0, 0.52f, 0); c.label.transform.localScale = Vector3.one * 0.0021f;
            c.Refresh(store, router, true);
            return c;
        }

        static string Sig(Room r) => r.phase + "|" + r.title + "|" + RoomLogic.Mine(r)?.status + "|" + string.Join(",", r.members.ConvertAll(m => m.id + m.status));

        /// <summary>Update the window every call (cheap); rebuild the label only when its content changes.</summary>
        public void Refresh(IRoomStore store, ScreenRouter router, bool force = false)
        {
            var room = store.Get(roomId); if (room == null) return;
            var pres = PortalPresentation.For(room);
            portal.SetPresentation(pres.mist, pres.alpha);
            if (_bar != null) _bar.Set(room.progress, ColorRole.Sun);
            var sig = Sig(room);
            if (!force && sig == _sig) return;
            _sig = sig;
            foreach (Transform t in label.rect) Destroy(t.gameObject);
            var col = UI.V(label.rect, "Col", 6, new RectOffset(18, 18, 14, 14), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 32); UI.Border(col, ColorRole.GlassEdge, 32, 2);
            var title = UI.Text(col, room.title, TextStyle.Title, ColorRole.OnGlass, TextAlignmentOptions.Center); title.fontSize = 38; title.overflowMode = TextOverflowModes.Ellipsis; title.maxVisibleLines = 1;
            var (st, txt, meta) = DashboardScreen.CardInfo(room);
            if (st.HasValue) { var slot = UI.H(col, "Tag", 0, null, TextAnchor.MiddleCenter); UI.Size(slot, -1, 34); StatusTag.Create(slot, st.Value, txt, true); }
            var cap = UI.Text(col, pres.kind == PortalKind.Ready ? pres.hint : meta, TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Center); cap.fontSize = 20;
            _bar = null;
            if (pres.kind == PortalKind.Building) { _bar = Bar.Create(col, ColorRole.Sun, 8); _bar.Set(room.progress); }
            if (pres.kind == PortalKind.Invited)
            {
                var row = UI.H(col, "Buttons", 10, null, TextAnchor.MiddleCenter); UI.Size(row, -1, 48);
                RButton.Create(row, "Join", BtnVariant.Light, BtnSize.Sm, onClick: () => { store.Join(roomId); router.Go(Route.RoomUpload, roomId); });
                RButton.Create(row, "Decline", BtnVariant.Glass, BtnSize.Sm, onClick: () => store.Decline(roomId));
            }
        }
    }
}
