using System;
using System.Collections.Generic;
using System.IO;
using GLTFast;
using UnityEngine;

public class GlbAssetLoader : MonoBehaviour
{
    private readonly List<GltfImport> activeImports = new List<GltfImport>();

    public async void LoadAndReplace(string assetReference, GameObject placeholder)
    {
        if (placeholder == null || string.IsNullOrWhiteSpace(assetReference))
        {
            return;
        }

        string uri = ResolveUri(assetReference);
        var placeholderRenderers = placeholder.GetComponentsInChildren<Renderer>(true);
        var import = new GltfImport();
        activeImports.Add(import);

        bool loaded = await import.Load(uri);
        if (!loaded)
        {
            Debug.LogWarning("GlbAssetLoader: could not load " + uri + ". Keeping placeholder.");
            activeImports.Remove(import);
            import.Dispose();
            return;
        }

        var modelRoot = new GameObject("GLB Model").transform;
        modelRoot.SetParent(placeholder.transform, false);

        bool instantiated = await import.InstantiateMainSceneAsync(modelRoot);
        if (!instantiated)
        {
            Destroy(modelRoot.gameObject);
            Debug.LogWarning("GlbAssetLoader: could not instantiate " + assetReference + ". Keeping placeholder.");
            activeImports.Remove(import);
            import.Dispose();
            return;
        }

        for (int i = 0; i < placeholderRenderers.Length; i++)
        {
            if (placeholderRenderers[i] != null)
            {
                placeholderRenderers[i].enabled = false;
            }
        }

        Debug.Log("GlbAssetLoader: replaced placeholder with " + assetReference);
    }

    private static string ResolveUri(string assetReference)
    {
        if (Uri.TryCreate(assetReference, UriKind.Absolute, out var absoluteUri))
        {
            return absoluteUri.AbsoluteUri;
        }

        string fullPath = Path.Combine(Application.streamingAssetsPath, assetReference);
        return new Uri(fullPath).AbsoluteUri;
    }
}