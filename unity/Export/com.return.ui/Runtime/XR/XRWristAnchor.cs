using UnityEngine;

namespace Return.UI.XR
{
    /// <summary>A transform that rides the left wrist: the left controller when it is active, otherwise the tracked left hand. The hub parents its hand menu here.</summary>
    public class XRWristAnchor : MonoBehaviour
    {
        public Transform controller, hand;

        void LateUpdate()
        {
            var src = controller != null && controller.gameObject.activeInHierarchy ? controller : hand != null && hand.gameObject.activeInHierarchy ? hand : null;
            if (src == null) return;
            transform.SetPositionAndRotation(src.position, src.rotation);
        }
    }
}
