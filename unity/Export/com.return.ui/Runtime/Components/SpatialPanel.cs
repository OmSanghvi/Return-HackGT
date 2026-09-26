using Return.Design;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>A world-space UGUI canvas sized in dp (1 dp = 1 mm at scale 0.001). Default panel 1024x640dp at 1.2m.</summary>
    public class SpatialPanel : MonoBehaviour
    {
        public Canvas canvas;
        public RectTransform rect;
        public const float MetersPerDp = 0.001f;
        /// <summary>Raised for every new panel. XR glue subscribes to add a TrackedDeviceGraphicRaycaster without the package depending on XR.</summary>
        public static event System.Action<SpatialPanel> Created;

        public static SpatialPanel Create(string name, float wDp = ReturnSpatial.PanelWidthDp, float hDp = ReturnSpatial.PanelHeightDp, Transform parent = null)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Canvas), typeof(GraphicRaycaster));
            if (parent != null) go.transform.SetParent(parent, false);
            var p = go.AddComponent<SpatialPanel>();
            p.rect = (RectTransform)go.transform;
            p.rect.sizeDelta = new Vector2(wDp, hDp);
            p.rect.localScale = Vector3.one * MetersPerDp;
            p.canvas = go.GetComponent<Canvas>();
            p.canvas.renderMode = RenderMode.WorldSpace;
            p.canvas.additionalShaderChannels |= AdditionalCanvasShaderChannels.TexCoord1 | AdditionalCanvasShaderChannels.Normal | AdditionalCanvasShaderChannels.Tangent;
            p.canvas.overrideSorting = false;
            var scaler = go.AddComponent<CanvasScaler>(); scaler.dynamicPixelsPerUnit = 2f; scaler.referencePixelsPerUnit = 100;
            Created?.Invoke(p);
            return p;
        }

        /// <summary>Place in front of a viewer at the default ray distance, facing them.</summary>
        public void PlaceInFront(Transform viewer, float distance = ReturnSpatial.PanelDistanceRay, float heightOffset = -0.05f)
        {
            var fwd = viewer.forward; fwd.y = 0; if (fwd.sqrMagnitude < 0.01f) fwd = Vector3.forward; fwd.Normalize();
            transform.position = viewer.position + fwd * distance + Vector3.up * heightOffset;
            transform.rotation = Quaternion.LookRotation(fwd);
        }

        /// <summary>Resolve the camera for event-camera duties. Screen-space ray input can also set this.</summary>
        public void SetEventCamera(Camera c) { canvas.worldCamera = c; }
    }
}
