using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The "way home" arch: a small glowing portal spawned ~1.8 m behind the arrival spot in every world, painted with
    /// the hub sky. It is just a RoomPortal (same look, same bob, same shader) sized down and pointed at the viewer's
    /// arrival position, so RoomPortal.Created already makes the XR assembly wire it up exactly like a ring portal
    /// (hover/select interactable, haptics) with no XR-specific code in this file. Activating it calls back into
    /// WorldSession, which runs the same ExitAsync as the wrist menu's Hub item.
    /// </summary>
    public static class HomePortal
    {
        const float Distance = 1.8f, Scale = 0.75f, Height = 1.1f;
        static readonly Room HubRoom = new Room { id = "home", title = "Hub", scene = SceneKey.Hub };

        /// <summary>Spawned as a sibling of head (not under the world root), so it survives whatever the loader does to the
        /// world and never gets swept up by the XR interactable pass that walks the world's own renderers.</summary>
        public static RoomPortal Spawn(Transform head, System.Action onActivate)
        {
            if (head == null) return null;
            var anchor = new GameObject("HomePortal");
            var flat = new Vector3(head.position.x, 0f, head.position.z);
            var yaw = head.eulerAngles.y;
            anchor.transform.SetPositionAndRotation(flat, Quaternion.Euler(0f, yaw, 0f));

            var portal = RoomPortal.Create(anchor.transform, HubRoom, new Vector3(0, Height, -Distance));
            portal.transform.localRotation = Quaternion.LookRotation(Vector3.back);
            portal.transform.localScale *= Scale;
            portal.SetPresentation(0f, 1f);
            portal.Activated += _ => onActivate();

            var label = SpatialPanel.Create("Label", 240, 90, portal.transform);
            label.transform.localPosition = new Vector3(0, 0.72f, 0);
            label.transform.localRotation = Quaternion.identity;
            label.transform.localScale = Vector3.one * 0.0018f;
            var col = UI.V(label.rect, "Col", 0, UI.Pad(10), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 20); UI.Border(col, ColorRole.GlassEdge, 20, 2);
            UI.Text(col, "Hub", TextStyle.Label, ColorRole.OnGlass, TextAlignmentOptions.Center);
            return portal;
        }

        public static void Despawn(RoomPortal portal)
        {
            if (portal == null) return;
            Object.Destroy(portal.transform.parent != null ? portal.transform.parent.gameObject : portal.gameObject);
        }
    }
}
