using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Diegetic highlight for the elements a guide turn calls out: an emissive
/// rim on mesh objects (MaterialPropertyBlock, no material instance leak --
/// same convention as ContributorAttribution's ring), or, for Gaussian
/// splats with no MeshRenderer, a spotlight cone from the bot plus a soft
/// floor ring under the object's bounds. At most 4 at once (skill 4).
/// </summary>
public sealed class SketchScapeGuideHighlighter : MonoBehaviour
{
    private const int MaxHighlighted = 4;
    private static readonly int EmissionColorId = Shader.PropertyToID("_EmissionColor");

    [SerializeField] private Color highlightColor = new Color(1f, 0.92f, 0.6f);
    [SerializeField] private float spotlightRange = 4f;
    [SerializeField] private float spotlightAngle = 20f;

    private readonly List<(Renderer renderer, MaterialPropertyBlock original)> litRenderers =
        new List<(Renderer, MaterialPropertyBlock)>();
    private readonly List<GameObject> spawnedFallbacks = new List<GameObject>();

    public void Highlight(IEnumerable<string> elementIds, SketchScapeGuideObjectMap map, Transform bot)
    {
        ClearAll();
        int count = 0;
        foreach (string elementId in elementIds)
        {
            if (count >= MaxHighlighted)
            {
                break;
            }
            if (!map.TryGet(elementId, out var target))
            {
                continue;
            }
            var renderer = target.GetComponentInChildren<Renderer>();
            if (renderer != null)
            {
                HighlightRenderer(renderer);
            }
            else
            {
                SpawnFallback(target, bot);
            }
            count++;
        }
    }

    public void ClearAll()
    {
        foreach (var (renderer, _) in litRenderers)
        {
            if (renderer != null)
            {
                renderer.SetPropertyBlock(null);
            }
        }
        litRenderers.Clear();

        foreach (var go in spawnedFallbacks)
        {
            if (go != null)
            {
                Destroy(go);
            }
        }
        spawnedFallbacks.Clear();
    }

    private void HighlightRenderer(Renderer renderer)
    {
        var block = new MaterialPropertyBlock();
        renderer.GetPropertyBlock(block);
        block.SetColor(EmissionColorId, highlightColor * 1.5f);
        renderer.SetPropertyBlock(block);
        litRenderers.Add((renderer, block));
    }

    private void SpawnFallback(GameObject target, Transform bot)
    {
        Bounds bounds = new Bounds(target.transform.position, Vector3.one * 0.3f);
        foreach (var childRenderer in target.GetComponentsInChildren<Renderer>())
        {
            bounds.Encapsulate(childRenderer.bounds);
        }
        foreach (var collider in target.GetComponentsInChildren<Collider>())
        {
            bounds.Encapsulate(collider.bounds);
        }

        var lightObject = new GameObject("Guide Highlight Spotlight");
        lightObject.transform.SetParent(bot != null ? bot : transform, false);
        lightObject.transform.position = bot != null ? bot.position : bounds.center + Vector3.up * 2f;
        lightObject.transform.LookAt(bounds.center);
        var spot = lightObject.AddComponent<Light>();
        spot.type = LightType.Spot;
        spot.color = highlightColor;
        spot.intensity = 3f;
        spot.range = spotlightRange;
        spot.spotAngle = spotlightAngle;
        spawnedFallbacks.Add(lightObject);

        var ring = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        ring.name = "Guide Highlight Ring";
        Destroy(ring.GetComponent<Collider>());
        float diameter = Mathf.Max(bounds.size.x, bounds.size.z) * 1.3f + 0.1f;
        ring.transform.position = new Vector3(bounds.center.x, Mathf.Max(bounds.min.y, 0f) + 0.01f, bounds.center.z);
        ring.transform.localScale = new Vector3(diameter, 0.005f, diameter);
        Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        var material = new Material(shader) { color = highlightColor };
        material.EnableKeyword("_EMISSION");
        if (material.HasProperty(EmissionColorId))
        {
            material.SetColor(EmissionColorId, highlightColor);
        }
        ring.GetComponent<Renderer>().material = material;
        spawnedFallbacks.Add(ring);
    }
}
