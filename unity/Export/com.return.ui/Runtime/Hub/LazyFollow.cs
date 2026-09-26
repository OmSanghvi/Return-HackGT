using UnityEngine;

namespace Return.UI
{
    /// <summary>Keeps a panel in front of the viewer with lag: it follows yaw and position but not head roll or pitch.</summary>
    public class LazyFollow : MonoBehaviour
    {
        public Transform head; public float distance = 0.7f, down = 0.42f, smooth = 4f;
        void LateUpdate()
        {
            if (head == null) return;
            var fwd = head.forward; fwd.y = 0; if (fwd.sqrMagnitude < 0.01f) return; fwd.Normalize();
            var target = head.position + fwd * distance + Vector3.down * down;
            float k = 1f - Mathf.Exp(-smooth * Time.unscaledDeltaTime);
            transform.position = Vector3.Lerp(transform.position, target, k);
            var want = Quaternion.LookRotation(fwd) * Quaternion.Euler(25, 0, 0);
            transform.rotation = Quaternion.Slerp(transform.rotation, want, k);
        }
    }
}
