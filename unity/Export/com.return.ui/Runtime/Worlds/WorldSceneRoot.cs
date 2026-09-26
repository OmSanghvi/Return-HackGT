using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The anchor of a room's world scene. Author (or let the agent author) everything as a child of this, in viewer space:
    /// +Z is the way the viewer faces on arrival, y = 0 is the floor, the viewer stands at the local origin.
    /// SceneWorldLoader moves this under the viewer when the scene loads, so a child at (0, 0, 1.5) appears 1.5 m ahead.
    /// </summary>
    public class WorldSceneRoot : MonoBehaviour
    {
        [Tooltip("Surround the world with the room's painted sky (the same dome + panorama the stub world uses). Turn off once the scene brings its own surroundings.")]
        public bool buildSky = true;

        /// <summary>Place the world under the viewer (floor at y = 0, facing the head's yaw) and build its sky.</summary>
        public void Arrive(Room room, Transform head)
        {
            var at = head != null ? head.position : Vector3.zero;
            transform.SetPositionAndRotation(new Vector3(at.x, 0f, at.z), Quaternion.Euler(0f, head != null ? head.eulerAngles.y : 0f, 0f));
            if (buildSky && room != null) HubEnvironment.Build(transform, head, room.scene, UIAssets.IsDusk(room.scene), 200f);
        }
    }
}
