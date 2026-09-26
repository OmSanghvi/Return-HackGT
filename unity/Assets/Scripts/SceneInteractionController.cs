using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Registry and policy boundary for named scene interactions. Runtime requests
/// go through the backend; MCP/editor actions use the same bounded local policy.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(SketchSceneLoader))]
public sealed class SceneInteractionController : MonoBehaviour
{
    public const string ScaleBy = "scale_by";
    public const string TranslateBy = "translate_by";
    public const string RotateBy = "rotate_by";

    [SerializeField] private string apiBaseUrl = "http://127.0.0.1:8000";
    [SerializeField] private float requestTimeoutSeconds = 10f;
    [Tooltip("Contributor this session acts for. When set, the backend only accepts edits to objects the social manifest attributes to them.")]
    [SerializeField] private string activeContributorId;

    private readonly Dictionary<string, NamedSceneInteractive> interactives = new Dictionary<string, NamedSceneInteractive>();
    private SketchSceneLoader loader;
    private bool requestInFlight;

    public bool RequestInFlight => requestInFlight;
    public string ActiveContributorId => activeContributorId;

    public void SetActiveContributor(string contributorId)
    {
        activeContributorId = contributorId == null ? string.Empty : contributorId.Trim();
    }

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
        RebuildRegistry();
    }

    public void Register(NamedSceneInteractive interactive)
    {
        if (interactive == null || string.IsNullOrWhiteSpace(interactive.InteractiveId))
        {
            return;
        }
        interactives[interactive.InteractiveId] = interactive;
    }

    public void Unregister(NamedSceneInteractive interactive)
    {
        if (interactive == null || string.IsNullOrWhiteSpace(interactive.InteractiveId))
        {
            return;
        }
        if (interactives.TryGetValue(interactive.InteractiveId, out var registered) && registered == interactive)
        {
            interactives.Remove(interactive.InteractiveId);
        }
    }

    [ContextMenu("Rebuild Named Interactive Registry")]
    public void RebuildRegistry()
    {
        interactives.Clear();
        foreach (var interactive in FindObjectsByType<NamedSceneInteractive>())
        {
            Register(interactive);
        }
    }

    public bool TryExecuteLocalAction(string targetId, string action, Vector3 value, out string error)
    {
        error = null;
        if (!interactives.TryGetValue(targetId ?? string.Empty, out var interactive) || interactive == null)
        {
            error = "Unknown named interactive: " + targetId;
            return false;
        }

        if (!interactive.Allows(action))
        {
            error = action + " is not enabled for " + targetId + ".";
            return false;
        }

        Transform target = interactive.transform;
        switch (action)
        {
            case ScaleBy:
                if (!Within(value, 0.25f, 4f))
                {
                    error = "scale_by values must be between 0.25 and 4.";
                    return false;
                }
                Vector3 scale = Vector3.Scale(target.localScale, value);
                if (!Within(scale, 0.05f, 20f))
                {
                    error = "Resulting scale must remain between 0.05 and 20.";
                    return false;
                }
                target.localScale = scale;
                return true;
            case TranslateBy:
                if (!Within(value, -10f, 10f))
                {
                    error = "translate_by values must be between -10 and 10.";
                    return false;
                }
                Vector3 position = target.position + value;
                if (!Within(position, -100f, 100f))
                {
                    error = "Resulting position must remain within scene bounds.";
                    return false;
                }
                target.position = position;
                return true;
            case RotateBy:
                if (!Within(value, -360f, 360f))
                {
                    error = "rotate_by values must be between -360 and 360.";
                    return false;
                }
                target.Rotate(value, Space.Self);
                return true;
            default:
                error = "Action is not allowlisted: " + action;
                return false;
        }
    }

    public void RequestBackendAction(string targetId, string action, Vector3 value)
    {
        if (!requestInFlight)
        {
            StartCoroutine(RequestBackendActionRoutine(targetId, action, value));
        }
    }

    public string GetRegistryJson()
    {
        RebuildRegistry();
        var entries = new List<InteractiveDescriptor>();
        foreach (var pair in interactives)
        {
            if (pair.Value != null)
            {
                entries.Add(new InteractiveDescriptor
                {
                    id = pair.Key,
                    name = pair.Value.name,
                    type = pair.Value.SemanticType,
                    actions = pair.Value.AllowedActions
                });
            }
        }
        entries.Sort((left, right) => string.CompareOrdinal(left.id, right.id));
        return JsonUtility.ToJson(new InteractiveRegistry { interactives = entries.ToArray() }, true);
    }

    private IEnumerator RequestBackendActionRoutine(string targetId, string action, Vector3 value)
    {
        requestInFlight = true;
        var payload = new SceneActionPayload
        {
            target_id = targetId,
            action = action,
            value = new[] { value.x, value.y, value.z },
            contributor_id = activeContributorId ?? string.Empty
        };
        byte[] body = System.Text.Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload));
        string endpoint = apiBaseUrl.TrimEnd('/') + "/v1/scene/actions";

        using (var request = new UnityWebRequest(endpoint, UnityWebRequest.kHttpVerbPOST))
        {
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                loader.ApplySceneUpdate(request.downloadHandler.text);
            }
            else
            {
                loader.ReportStatus("Safe action failed — " + request.error);
                Debug.LogWarning("SceneInteractionController: " + request.downloadHandler.text);
            }
        }
        requestInFlight = false;
    }

    private static bool Within(Vector3 value, float minimum, float maximum)
    {
        return value.x >= minimum && value.x <= maximum
            && value.y >= minimum && value.y <= maximum
            && value.z >= minimum && value.z <= maximum;
    }

    [Serializable]
    private sealed class SceneActionPayload
    {
        public string target_id;
        public string action;
        public float[] value;
        public string contributor_id;
    }

    [Serializable]
    private sealed class InteractiveDescriptor
    {
        public string id;
        public string name;
        public string type;
        public string[] actions;
    }

    [Serializable]
    private sealed class InteractiveRegistry
    {
        public InteractiveDescriptor[] interactives;
    }
}
