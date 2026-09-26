using System;
using System.Threading.Tasks;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>Placeholder world so the enter/exit loop is demonstrable: the room's painting as a panorama, a fogged floor, and a note. Replace with a real loader.</summary>
    public class StubWorldLoader : IWorldLoader
    {
        public float loadSeconds = 1.0f;
        GameObject _root;

        public GameObject Root => _root;

        public async Task LoadAsync(Room room, Transform head, Action<float> progress)
        {
            Build(room, head);
            float t = 0;
            while (t < loadSeconds) { t += Time.unscaledDeltaTime; progress?.Invoke(Mathf.Clamp01(t / loadSeconds)); await Task.Yield(); }
            progress?.Invoke(1f);
        }

        /// <summary>Synchronous build (edit-mode tools and tests).</summary>
        public GameObject Build(Room room, Transform head)
        {
            if (_root != null) UnityEngine.Object.DestroyImmediate(_root);
            _root = new GameObject("World:" + room.title);
            var yaw = head != null ? head.eulerAngles.y : 0f;
            _root.transform.rotation = Quaternion.Euler(0, yaw, 0);
            HubEnvironment.Build(_root.transform, head, room.scene, UIAssets.IsDusk(room.scene), 200f);

            var note = SpatialPanel.Create("WorldNote", 640, 300, _root.transform);
            note.transform.localPosition = new Vector3(0, 1.5f, 2.2f);
            note.transform.localRotation = Quaternion.identity;
            note.transform.localScale = Vector3.one * 0.0016f;
            var col = UI.V(note.rect, "Note", 12, UI.Pad(32), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 36); UI.Border(col, ColorRole.GlassEdge, 36, 2);
            UI.Text(col, room.title, TextStyle.DisplayM, ColorRole.OnGlass, TextAlignmentOptions.Center).fontSize = 44;
            UI.Text(col, "A stand-in for the real world. Plug a loader into IWorldLoader (scene, splat or download).", TextStyle.Body, ColorRole.OnGlass, TextAlignmentOptions.Center);
            UI.Text(col, "Open the hand menu to go back to the hub.", TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Center);
            return _root;
        }

        public Task UnloadAsync()
        {
            if (_root != null) UnityEngine.Object.Destroy(_root);
            _root = null;
            return Task.CompletedTask;
        }
    }
}
