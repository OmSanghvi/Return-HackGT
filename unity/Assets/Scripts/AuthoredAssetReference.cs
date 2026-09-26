using UnityEngine;

/// <summary>
/// Build-time provenance for an imported reconstruction. The final authoring
/// pass must replace remote references with packaged renderer assets.
/// </summary>
[DisallowMultipleComponent]
public sealed class AuthoredAssetReference : MonoBehaviour
{
    [SerializeField] private string sourceUrl;
    [SerializeField] private string sourceKind;

    public string SourceUrl => sourceUrl;
    public string SourceKind => sourceKind;

    public void Configure(string url, string kind)
    {
        sourceUrl = url;
        sourceKind = kind;
    }
}
