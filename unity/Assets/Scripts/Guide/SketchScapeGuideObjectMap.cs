using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Resolves a guide tour's element_id to a GameObject in the built scene.
/// "contribution"/"environment" elements resolve through NamedSceneInteractive
/// (the builder names objects item.id, and GuideTourElementView.object_id
/// carries that same id). "motif" elements (no object_id) resolve through
/// staging_cue_id -- ContributorAttribution already carries a staging cue id
/// per object (Build Plan step 6), so this registers those for free; step 6
/// components that aren't ContributorAttribution can add themselves with
/// RegisterMotif.
/// </summary>
public sealed class SketchScapeGuideObjectMap : MonoBehaviour
{
    private readonly Dictionary<string, GameObject> byObjectId = new Dictionary<string, GameObject>();
    private readonly Dictionary<string, GameObject> byStagingCue = new Dictionary<string, GameObject>();
    private readonly Dictionary<string, GameObject> byElementId = new Dictionary<string, GameObject>();
    private readonly Dictionary<GameObject, string> elementIdByObject = new Dictionary<GameObject, string>();

    private void Awake()
    {
        RebuildRegistry();
    }

    [ContextMenu("Rebuild Guide Object Registry")]
    public void RebuildRegistry()
    {
        byObjectId.Clear();
        byStagingCue.Clear();
        foreach (var interactive in FindObjectsByType<NamedSceneInteractive>(FindObjectsSortMode.None))
        {
            if (interactive != null && !string.IsNullOrWhiteSpace(interactive.InteractiveId))
            {
                byObjectId[interactive.InteractiveId] = interactive.gameObject;
            }
        }
        foreach (var attribution in FindObjectsByType<ContributorAttribution>(FindObjectsSortMode.None))
        {
            if (attribution != null && !string.IsNullOrWhiteSpace(attribution.StagingCueId))
            {
                byStagingCue[attribution.StagingCueId] = attribution.gameObject;
            }
        }
    }

    public void RegisterMotif(string stagingCueId, GameObject go)
    {
        if (!string.IsNullOrWhiteSpace(stagingCueId) && go != null)
        {
            byStagingCue[stagingCueId] = go;
        }
    }

    /// <summary>Resolves every element in a fetched tour to a GameObject, keyed by element_id.
    /// Elements with no matching object (stale, or missing step 6 motif) are skipped, not errors --
    /// the room must still work with a partially-stale tour (GuideTourResponse.stale_element_ids).</summary>
    public void ResolveTour(GuideTourResponse tour)
    {
        byElementId.Clear();
        elementIdByObject.Clear();
        if (tour?.elements == null)
        {
            return;
        }
        foreach (var element in tour.elements)
        {
            GameObject go = null;
            if (!string.IsNullOrEmpty(element.object_id))
            {
                byObjectId.TryGetValue(element.object_id, out go);
            }
            if (go == null && !string.IsNullOrEmpty(element.staging_cue_id))
            {
                byStagingCue.TryGetValue(element.staging_cue_id, out go);
            }
            if (go != null)
            {
                byElementId[element.element_id] = go;
                elementIdByObject[go] = element.element_id;
            }
        }
    }

    public bool TryGet(string elementId, out GameObject go)
    {
        go = null;
        return !string.IsNullOrEmpty(elementId) && byElementId.TryGetValue(elementId, out go) && go != null;
    }

    public bool TryGetElementId(GameObject go, out string elementId)
    {
        elementId = null;
        if (go == null)
        {
            return false;
        }
        // A hit collider is often a child (a placeholder body/handle); walk up
        // to the object that actually carries the mapping.
        for (Transform t = go.transform; t != null; t = t.parent)
        {
            if (elementIdByObject.TryGetValue(t.gameObject, out elementId))
            {
                return true;
            }
        }
        return false;
    }
}
