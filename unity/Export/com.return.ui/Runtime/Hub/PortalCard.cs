using System;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>One room on the ring: the painted arched window (always clear; the ring only ever holds ready worlds), and a small glass
    /// label under it with the room's title and who's in it.</summary>
    public class PortalCard : MonoBehaviour
    {
        public string roomId;
        public RoomPortal portal;
        public SpatialPanel label;
        string _sig;

        public static PortalCard Create(Transform ring, Room room, IRoomStore store, Action<Room, RoomPortal> onActivate)
        {
            var anchor = new GameObject("Portal:" + room.id); anchor.transform.SetParent(ring, false);
            var c = anchor.AddComponent<PortalCard>(); c.roomId = room.id;
            c.portal = RoomPortal.Create(anchor.transform, room, new Vector3(0, 1.35f, 0));
            c.portal.SetPresentation(0f, 1f); // clear window: the ring only ever holds rooms that are ready to enter
            c.portal.Activated += _ => onActivate(room, c.portal);
            c.label = SpatialPanel.Create("Label", 420, 180, anchor.transform);
            c.label.transform.localPosition = new Vector3(0, 0.52f, 0); c.label.transform.localScale = Vector3.one * 0.0021f;
            c.Refresh(store, true);
            return c;
        }

        static string Sig(Room r) => r.title + "|" + string.Join(",", r.members.Select(m => m.id + m.name));

        /// <summary>Rebuild the label only when its content changes.</summary>
        public void Refresh(IRoomStore store, bool force = false)
        {
            var room = store.Get(roomId); if (room == null) return;
            var sig = Sig(room);
            if (!force && sig == _sig) return;
            _sig = sig;
            foreach (Transform t in label.rect) Destroy(t.gameObject);
            var col = UI.V(label.rect, "Col", 6, new RectOffset(18, 18, 14, 14), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 32); UI.Border(col, ColorRole.GlassEdge, 32, 2);
            var title = UI.Text(col, room.title, TextStyle.Title, ColorRole.OnGlass, TextAlignmentOptions.Center); title.fontSize = 38; title.overflowMode = TextOverflowModes.Ellipsis; title.maxVisibleLines = 1;
            var names = string.Join(", ", room.members.Select(m => m.name.Split(' ')[0]));
            var who = UI.Text(col, names, TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Center); who.fontSize = 20;
        }
    }
}
