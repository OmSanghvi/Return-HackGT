// SketchScape FakeLetter — a stand-alone envelope on a little stand. Poking / pinching / ray-selecting
// the envelope (SharedPokeButton) unfolds a SharedLetterPage in front of the player's head with a
// fixed heading + body; pressing again folds it away. No network, no session: pure demo content.
// Built by FakeLetterKit in the Editor; at runtime this only reacts to the button.
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public sealed class FakeLetter : MonoBehaviour
    {
        public string letterId = "fake";
        public string heading = "";
        [TextArea] public string body = "";
        public SharedPokeButton button;
        public SharedLetterPage page;
        [Tooltip("Moved in front of the player's head when the page opens.")]
        public Transform pageRoot;
        [Tooltip("The page unfolds out of this transform.")]
        public Transform envelope;
        [Tooltip("Metres in front of the head (horizontal).")]
        public float distance = 0.75f;
        [Tooltip("World height of the page centre.")]
        public float height = 1.35f;

        void OnEnable()
        {
            if (button != null) button.Pressed += OnPressed;
        }

        void OnDisable()
        {
            if (button != null) button.Pressed -= OnPressed;
        }

        void OnPressed(SharedPokeButton _)
        {
            Toggle();
        }

        /// <summary>Open the page in front of the player, or fold it away if it is showing.</summary>
        public void Toggle()
        {
            if (page == null) return;
            if (page.Visible)
            {
                page.Hide();
                return;
            }

            Transform head = null;
            var rig = FindAnyObjectByType<OVRCameraRig>();
            if (rig != null) head = rig.centerEyeAnchor;
            if (head == null && Camera.main != null) head = Camera.main.transform;

            Vector3 headPos = head != null ? head.position : Vector3.zero;
            Vector3 forward = head != null ? head.forward : Vector3.forward;
            forward.y = 0f;
            forward = forward.sqrMagnitude > 1e-6f ? forward.normalized : Vector3.forward;

            if (pageRoot != null)
            {
                pageRoot.position = new Vector3(headPos.x + forward.x * distance, height, headPos.z + forward.z * distance);
                // The sheet is authored facing -Z, so looking along `forward` turns its face towards the head.
                pageRoot.rotation = Quaternion.LookRotation(forward, Vector3.up);
            }

            page.Show(letterId, heading, envelope);
            page.SetBody(body);
        }
    }
}
