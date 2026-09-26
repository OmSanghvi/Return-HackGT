using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Unity's public, token-free client for SketchScape's asynchronous API.
/// Attach this to the same GameObject as SketchSceneLoader. It works against
/// PIPELINE_MODE=mock, so the full upload/poll/portal UX can be tested without
/// starting a GPU or contacting AWS.
/// </summary>
[RequireComponent(typeof(SketchSceneLoader))]
public class SketchScapeReconstructionClient : MonoBehaviour
{
    [Header("SketchScape API")]
    [SerializeField] private string apiBaseUrl = "http://127.0.0.1:8000";
    [SerializeField] private float requestTimeoutSeconds = 15f;
    [SerializeField] private float pollSeconds = 1.5f;
    [SerializeField] private float maximumWaitSeconds = 90f;

    [Header("Input")]
    [SerializeField] private Texture2D inputTexture;
    [SerializeField, TextArea] private string subjectHint = "tree";

    [Header("Demo UI")]
    [SerializeField] private bool showDebugUi = true;

    private SketchSceneLoader loader;
    private bool isSubmitting;
    private string inputFilename = "sketch.png";
    private string inputContentType = "image/png";

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
        loader.ConfigureApiBaseUrl(apiBaseUrl);
    }

    public void SubmitConfiguredSketch()
    {
        if (!isSubmitting)
        {
            StartCoroutine(CreateAndPollJob());
        }
    }

    /// <summary>
    /// Lets a desktop demo submit an arbitrary PNG/JPEG/WebP without placing
    /// it in Resources. A native system file picker is intentionally not
    /// bundled, so this takes a user-selected absolute path from the small
    /// companion component or from a UI button.
    /// </summary>
    public bool SetInputFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            loader.ReportStatus("Photo file was not found.");
            return false;
        }

        string extension = Path.GetExtension(path).ToLowerInvariant();
        inputContentType = extension == ".jpg" || extension == ".jpeg" ? "image/jpeg"
            : extension == ".png" ? "image/png"
            : extension == ".webp" ? "image/webp"
            : null;
        if (inputContentType == null)
        {
            loader.ReportStatus("Use a PNG, JPEG, or WebP image.");
            return false;
        }

        byte[] bytes;
        try
        {
            bytes = File.ReadAllBytes(path);
        }
        catch (Exception error)
        {
            loader.ReportStatus("Could not read photo — " + error.Message);
            return false;
        }

        var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
        if (!ImageConversion.LoadImage(texture, bytes, false))
        {
            Destroy(texture);
            loader.ReportStatus("That file is not a readable image.");
            return false;
        }
        if (inputTexture != null && inputTexture != texture && inputTexture.name == "SketchScape Runtime Input")
        {
            Destroy(inputTexture);
        }
        texture.name = "SketchScape Runtime Input";
        inputTexture = texture;
        inputFilename = Path.GetFileName(path);
        loader.ReportStatus("Photo ready: " + inputFilename);
        return true;
    }

    private IEnumerator CreateAndPollJob()
    {
        if (inputTexture == null)
        {
            inputTexture = Resources.Load<Texture2D>("hackgttest");
        }
        if (inputTexture == null || !inputTexture.isReadable)
        {
            loader.ReportStatus("Choose a readable sketch texture first.");
            yield break;
        }

        isSubmitting = true;
        loader.ReportStatus("Sending sketch to SketchScape...");
        var form = new WWWForm();
        form.AddBinaryData("image", EncodeInput(), inputFilename, inputContentType);
        if (!string.IsNullOrWhiteSpace(subjectHint))
        {
            form.AddField("subject_hint", subjectHint.Trim());
        }

        ReconstructionCreateResponse created = null;
        using (var request = UnityWebRequest.Post(Endpoint("/v1/reconstructions"), form))
        {
            request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                created = JsonUtility.FromJson<ReconstructionCreateResponse>(request.downloadHandler.text);
            }
            else
            {
                loader.ReportStatus("Upload failed — " + request.error);
            }
        }

        if (created == null || string.IsNullOrWhiteSpace(created.poll_url))
        {
            isSubmitting = false;
            yield break;
        }

        yield return StartCoroutine(PollJob(created.poll_url));
        isSubmitting = false;
    }

    private byte[] EncodeInput()
    {
        // Loaded runtime images are normalized to PNG; this keeps Unity's
        // input readable even when an OS decoder produced another format.
        inputFilename = Path.GetFileNameWithoutExtension(inputFilename) + ".png";
        inputContentType = "image/png";
        return inputTexture.EncodeToPNG();
    }

    private IEnumerator PollJob(string pollUrl)
    {
        float elapsed = 0f;
        while (elapsed < maximumWaitSeconds)
        {
            loader.ReportStatus("Building world... " + Mathf.CeilToInt(maximumWaitSeconds - elapsed) + "s");
            using (var request = UnityWebRequest.Get(Endpoint(pollUrl)))
            {
                request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    loader.ReportStatus("Job check failed — " + request.error);
                    yield break;
                }

                var job = JsonUtility.FromJson<ReconstructionJobResponse>(request.downloadHandler.text);
                if (job == null)
                {
                    loader.ReportStatus("Job response was invalid.");
                    yield break;
                }

                if (job.status == "complete")
                {
                    if (job.scene == null || job.scene.objects == null)
                    {
                        loader.ReportStatus("The completed job had no scene.");
                        yield break;
                    }
                    loader.ReportStatus("World ready — opening portal...");
                    // SketchSceneLoader accepts the complete-job envelope and
                    // reads its nested scene object.
                    loader.LoadSceneFromJson(request.downloadHandler.text);
                    yield break;
                }
                if (job.status == "mask_review")
                {
                    loader.ReportStatus("Pick one centred object or supply a mask.");
                    yield break;
                }
                if (job.status == "failed")
                {
                    loader.ReportStatus("Reconstruction failed — " + (string.IsNullOrEmpty(job.error) ? "try a clearer photo." : job.error));
                    yield break;
                }
            }
            yield return new WaitForSeconds(pollSeconds);
            elapsed += pollSeconds;
        }
        loader.ReportStatus("Timed out. Use the local showcase scene or try again.");
    }

    private string Endpoint(string path)
    {
        if (Uri.TryCreate(path, UriKind.Absolute, out var absolute))
        {
            return absolute.AbsoluteUri;
        }
        return apiBaseUrl.TrimEnd('/') + "/" + path.TrimStart('/');
    }

    private void OnGUI()
    {
        if (!showDebugUi)
        {
            return;
        }
        GUILayout.BeginArea(new Rect(24f, 242f, 430f, 112f), GUI.skin.box);
        GUILayout.Label("RECONSTRUCT OBJECT");
        subjectHint = GUILayout.TextField(subjectHint, 100);
        GUI.enabled = !isSubmitting;
        if (GUILayout.Button(isSubmitting ? "Building..." : "Reconstruct sketch"))
        {
            SubmitConfiguredSketch();
        }
        GUI.enabled = true;
        GUILayout.Label("Mock mode is free; real GPU results may need a splat renderer.");
        GUILayout.EndArea();
    }

    [Serializable]
    private class ReconstructionCreateResponse
    {
        public string job_id;
        public string status;
        public string poll_url;
    }

    [Serializable]
    private class ReconstructionJobResponse
    {
        public string status;
        public string error;
        public SketchSceneDocument scene;
    }
}
