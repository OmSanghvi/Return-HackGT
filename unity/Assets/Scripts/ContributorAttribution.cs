using UnityEngine;

/// <summary>
/// Who contributed this object, from the compiled scene's social manifest
/// (shared/social-manifest.schema.json). Attribution is shown diegetically as a
/// glowing base ring in the contributor's color, never as a name tag or panel.
/// </summary>
[DisallowMultipleComponent]
public sealed class ContributorAttribution : MonoBehaviour
{
    [SerializeField] private string contributionId;
    [SerializeField] private string contributorId;
    [SerializeField] private string contributorDisplayName;
    [SerializeField] private string sourceType;
    [SerializeField] private Color attributionColor = Color.white;
    [SerializeField] private string stagingCueId;

    public string ContributionId => contributionId;
    public string ContributorId => contributorId;
    public string ContributorDisplayName => contributorDisplayName;
    public string SourceType => sourceType;
    public Color AttributionColor => attributionColor;
    public string StagingCueId => stagingCueId;
    /// <summary>The base ring marking this object's place (null until Start).</summary>
    public Transform Ring { get; private set; }

    public void Configure(string contribution, string contributor, string displayName, string source, string colorHex, string cueId)
    {
        contributionId = contribution;
        contributorId = contributor;
        contributorDisplayName = displayName;
        sourceType = source;
        attributionColor = ColorUtility.TryParseHtmlString(colorHex, out var parsed) ? parsed : Color.white;
        stagingCueId = cueId;
    }

    private void Start()
    {
        CreateBaseRing();
    }

    private void CreateBaseRing()
    {
        var collider = GetComponent<Collider>();
        Bounds bounds = collider != null ? collider.bounds : new Bounds(transform.position, Vector3.one * 0.5f);
        // Include child geometry such as a sketch card's stand, so the ring sits on the floor.
        foreach (var childRenderer in GetComponentsInChildren<Renderer>())
        {
            bounds.Encapsulate(childRenderer.bounds);
        }
        float diameter = Mathf.Max(bounds.size.x, bounds.size.z) * 1.25f + 0.1f;

        var ring = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        ring.name = "Attribution Ring";
        SketchCard.DestroyCollider(ring);
        // Never below the floor (y = 0), even when an object is partly sunk into it.
        ring.transform.position = new Vector3(bounds.center.x, Mathf.Max(bounds.min.y, 0f) + 0.005f, bounds.center.z);
        ring.transform.localScale = new Vector3(diameter, 0.005f, diameter);
        ring.transform.SetParent(transform, true);
        Ring = ring.transform;

        var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        var material = new Material(shader) { color = attributionColor };
        material.EnableKeyword("_EMISSION");
        if (material.HasProperty("_EmissionColor")) material.SetColor("_EmissionColor", attributionColor * 0.35f);
        if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", 0.2f);
        ring.GetComponent<Renderer>().sharedMaterial = material;
    }
}
