using UnityEngine;

/// <summary>
/// Headset-only render settings for splat-heavy rooms: fixed foveated rendering
/// (dynamic, up to the chosen level), so the edge of the view is shaded at lower
/// resolution, where Gaussian splats' overdraw costs the most. MSAA is set per
/// platform in Quality Settings instead (Android uses a level without MSAA),
/// because the eye textures take it when XR starts. Does nothing in the Editor.
/// </summary>
[DisallowMultipleComponent]
public sealed class QuestPerformance : MonoBehaviour
{
    [SerializeField] private OVRManager.FoveatedRenderingLevel foveation = OVRManager.FoveatedRenderingLevel.High;
    [SerializeField] private bool dynamicFoveation = true;

    private void Start()
    {
        if (Application.isEditor || Application.platform != RuntimePlatform.Android)
        {
            return;
        }
        OVRManager.foveatedRenderingLevel = foveation;
        OVRManager.useDynamicFoveatedRendering = dynamicFoveation;
        Debug.Log($"QuestPerformance: foveation {OVRManager.foveatedRenderingLevel} (dynamic {OVRManager.useDynamicFoveatedRendering}), MSAA {QualitySettings.antiAliasing}x");
    }
}
