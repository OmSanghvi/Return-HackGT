using System;
using UnityEngine;

/// <summary>
/// Stable, public identity and explicit capability list for one scene object.
/// This exposes no arbitrary component or reflection access.
/// </summary>
[DisallowMultipleComponent]
public sealed class NamedSceneInteractive : MonoBehaviour
{
    [SerializeField] private string interactiveId;
    [SerializeField] private string semanticType;
    [SerializeField] private string[] allowedActions = Array.Empty<string>();

    public string InteractiveId => interactiveId;
    public string SemanticType => semanticType;
    public string[] AllowedActions => (string[])allowedActions.Clone();

    public void Configure(string id, string type, string[] actions)
    {
        interactiveId = id == null ? string.Empty : id.Trim();
        semanticType = type == null ? string.Empty : type.Trim();
        allowedActions = actions == null ? Array.Empty<string>() : (string[])actions.Clone();
        name = string.IsNullOrWhiteSpace(interactiveId) ? name : interactiveId;
    }

    public bool Allows(string action)
    {
        return Array.IndexOf(allowedActions, action) >= 0;
    }

    private void OnEnable()
    {
        FindAnyObjectByType<SceneInteractionController>()?.Register(this);
    }

    private void OnDisable()
    {
        FindAnyObjectByType<SceneInteractionController>()?.Unregister(this);
    }
}
