using System;
using UnityEngine;

/// <summary>
/// Renderer-neutral boundary for real SAM3D PLY artifacts.
/// A Gaussian-splat package is intentionally not hard-coded into SketchScape.
/// Add a component with a public LoadPly(string url) method to this GameObject;
/// the bridge will invoke it only for .ply URLs.
/// </summary>
public class GaussianSplatBridge : MonoBehaviour
{
    [SerializeField] private MonoBehaviour rendererAdapter;

    public bool TryLoad(string assetUrl)
    {
        if (string.IsNullOrWhiteSpace(assetUrl) || !assetUrl.EndsWith(".ply", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (rendererAdapter == null)
        {
            Debug.LogWarning("GaussianSplatBridge: PLY received, but no renderer adapter is installed. Keeping semantic fallback.");
            return false;
        }
        rendererAdapter.SendMessage("LoadPly", assetUrl, SendMessageOptions.DontRequireReceiver);
        return true;
    }
}
