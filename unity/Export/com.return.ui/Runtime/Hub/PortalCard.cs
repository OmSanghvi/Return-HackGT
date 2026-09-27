using System;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>One room on the ring: the doorway into it (always clear; the ring only ever holds ready worlds), and a small glass
    /// label above the lintel with the room's title and who's in it. The label billboards (yaw only) to face whoever is looking,
    /// so its text never reads reversed from behind.</summary>
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
            c.portal = RoomPortal.Create(anchor.transform, room, new Vector3(0, ReturnSpatial.PortalHeight / 2f, 0)); // bottom rests on the floor
            c.portal.SetPresentation(0f, 1f); // clear window: the ring only ever holds rooms that are ready to enter
            c.portal.Activated += _ => onActivate(room, c.portal);
            c.label = SpatialPanel.Create("Label", 620, 200, anchor.transform);
            c.label.transform.localPosition = new Vector3(0, ReturnSpatial.PortalHeight + 0.25f, 0); c.label.transform.localScale = Vector3.one * 0.003f;
            c.Refresh(store, true);
            return c;
        }

        void LateUpdate() { RoomPortal.FaceYaw(label.transform, Camera.main != null ? Camera.main.transform : null); }

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
            var title = UI.Text(col, room.title, TextStyle.H1, ColorRole.OnGlass, TextAlignmentOptions.Center); // Hanken SemiBold: less crowded than the display face
            title.fontSize = 44; title.characterSpacing = 2; title.overflowMode = TextOverflowModes.Ellipsis; title.maxVisibleLines = 1;
            var names = string.Join(", ", room.members.Select(m => m.name.Split(' ')[0]));
            var who = UI.Text(col, names, TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Center); who.fontSize = 24; who.characterSpacing = 1;
        }
    }
}
