using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Runtime compiler entrypoint for a published SketchScape experience. The
/// backend resolves catalog assets and validates the blueprint; this component
/// applies the resulting scene through the existing safe loader/registry path.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(SketchSceneLoader))]
public sealed class SketchScapeExperienceCompiler : MonoBehaviour
{
    [SerializeField] private string apiBaseUrl = "http://127.0.0.1:8000";
    [SerializeField] private string projectId;
    [SerializeField] private bool compileOnStart;
    [SerializeField] private float requestTimeoutSeconds = 15f;

    private SketchSceneLoader loader;
    private bool compiling;

    public string ProjectId => projectId;
    public bool IsCompiling => compiling;

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
    }

    private void Start()
    {
        if (compileOnStart && !string.IsNullOrWhiteSpace(projectId))
        {
            CompilePublishedExperience();
        }
    }

    public void ConfigureProject(string value)
    {
        projectId = value == null ? string.Empty : value.Trim();
    }

    [ContextMenu("Compile Published Experience")]
    public void CompilePublishedExperience()
    {
        if (!compiling)
        {
            StartCoroutine(CompileRoutine());
        }
    }

    private IEnumerator CompileRoutine()
    {
        loader = loader != null ? loader : GetComponent<SketchSceneLoader>();
        if (string.IsNullOrWhiteSpace(projectId))
        {
            loader.ReportStatus("Choose a SketchScape project before compiling.");
            yield break;
        }

        compiling = true;
        loader.ReportStatus("Compiling published experience...");
        string escapedProjectId = UnityWebRequest.EscapeURL(projectId.Trim());
        string endpoint = apiBaseUrl.TrimEnd('/') + "/v1/projects/" + escapedProjectId + "/compiled-scene";
        using (var request = UnityWebRequest.Get(endpoint))
        {
            request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                loader.LoadSceneFromJson(request.downloadHandler.text);
            }
            else
            {
                string detail = string.IsNullOrWhiteSpace(request.downloadHandler.text)
                    ? request.error
                    : request.downloadHandler.text;
                loader.ReportStatus("Experience compile failed — " + request.error);
                Debug.LogWarning("SketchScapeExperienceCompiler: " + detail, this);
            }
        }
        compiling = false;
    }
}
