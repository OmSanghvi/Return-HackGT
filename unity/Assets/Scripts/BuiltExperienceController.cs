using UnityEngine;

/// <summary>
/// Runtime-only owner for an authored experience. The final player contains no
/// NemoClaw, MCP, reconstruction, or authoring-backend dependency.
/// </summary>
[DisallowMultipleComponent]
public sealed class BuiltExperienceController : MonoBehaviour
{
    [SerializeField] private string projectId;
    [SerializeField] private int blueprintRevision;
    [SerializeField] private string experienceMode = "vr";

    public string ProjectId => projectId;
    public int BlueprintRevision => blueprintRevision;
    public string ExperienceMode => experienceMode;

    public void Configure(string sourceProjectId, int sourceRevision, string mode)
    {
        projectId = sourceProjectId;
        blueprintRevision = sourceRevision;
        experienceMode = string.IsNullOrWhiteSpace(mode) ? "vr" : mode;
    }

    private void Awake()
    {
        Application.targetFrameRate = 72;
        QualitySettings.vSyncCount = 0;
    }
}
