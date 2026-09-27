using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The "way home" doorway: a full-size portal spawned ~3 m behind the arrival spot in every world, showing the
    /// hub's own sky. It is just a RoomPortal (same look, same shader, same 3D frame) pointed at the viewer's arrival
    /// position, so RoomPortal.Created already makes the XR assembly wire it up exactly like a ring portal
    /// (hover/select interactable, haptics) with no XR-specific code in this file. Activating it calls back into
    /// WorldSession, which runs the same ExitAsync as the wrist menu's Hub item.
    /// </summary>
    public static class HomePortal
    {
        const float Distance = 3.0f;
        static readonly Room HubRoom = new Room { id = "home", title = "Hub", scene = SceneKey.Meadow }; // the daylight hub's own sky (HubEnvironment.DefaultScene(false))

        /// <summary>Spawned as a sibling of head (not under the world root), so it survives whatever the loader does to the
        /// world and never gets swept up by the XR interactable pass that walks the world's own renderers.</summary>
        public static RoomPortal Spawn(Transform head, System.Action onActivate)
        {
            if (head == null) return null;
            var anchor = new GameObject("HomePortal");
            var flat = new Vector3(head.position.x, 0f, head.position.z);
            var yaw = head.eulerAngles.y;
            anchor.transform.SetPositionAndRotation(flat, Quaternion.Euler(0f, yaw, 0f));

            var portal = RoomPortal.Create(anchor.transform, HubRoom, new Vector3(0, ReturnSpatial.PortalHeight / 2f, -Distance)); // bottom on the floor
            portal.transform.localRotation = Quaternion.LookRotation(Vector3.back);
            portal.SetPresentation(0f, 1f);
            portal.Activated += _ => onActivate();

            // parented to the anchor, not the portal: the portal's own transform is scaled by width/height (see
            // RoomPortal), which would distort a child's local position, and the anchor is already floor-referenced
            // the same way PortalCard's anchor is.
            var label = SpatialPanel.Create("Label", 420, 140, anchor.transform);
            label.transform.localPosition = new Vector3(0, ReturnSpatial.PortalHeight + 0.15f, -Distance);
            label.transform.localScale = Vector3.one * 0.0026f;
            var col = UI.V(label.rect, "Col", 0, UI.Pad(10), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 24); UI.Border(col, ColorRole.GlassEdge, 24, 2);
            var title = UI.Text(col, "Back to hub", TextStyle.H1, ColorRole.OnGlass, TextAlignmentOptions.Center);
            title.fontSize = 40; title.characterSpacing = 2;
            label.gameObject.AddComponent<HomeLabelFace>().head = head;
            return portal;
        }

        /// <summary>Yaw-billboards the "Back to hub" label toward whoever spawned it, same convention as PortalCard's label.</summary>
        class HomeLabelFace : MonoBehaviour
        {
            public Transform head;
            void LateUpdate() => RoomPortal.FaceYaw(transform, head);
        }

        public static void Despawn(RoomPortal portal)
        {
            if (portal == null) return;
            Object.Destroy(portal.transform.parent != null ? portal.transform.parent.gameObject : portal.gameObject);
        }
    }
}
