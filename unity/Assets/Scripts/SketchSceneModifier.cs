using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

[RequireComponent(typeof(SketchSceneLoader))]
public class SketchSceneModifier : MonoBehaviour
{
    [SerializeField] private string backendUrl = "http://127.0.0.1:8000/modify-scene";
    [SerializeField] private string instruction = "Make the tree twice as tall.";
    [SerializeField] private float requestTimeoutSeconds = 5f;

    private SketchSceneLoader loader;
    private bool isSubmitting;

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.T) && !isSubmitting)
        {
            StartCoroutine(SubmitInstruction());
        }
    }

    public void SubmitConfiguredInstruction()
    {
        if (!isSubmitting)
        {
            StartCoroutine(SubmitInstruction());
        }
    }

    private void OnGUI()
    {
        GUILayout.BeginArea(new Rect(24f, 126f, 430f, 100f), GUI.skin.box);
        GUILayout.Label("LIVE EDIT  (T to send)");
        instruction = GUILayout.TextField(instruction, 160);
        GUI.enabled = !isSubmitting;
        if (GUILayout.Button(isSubmitting ? "Applying..." : "Apply instruction"))
        {
            SubmitConfiguredInstruction();
        }
        GUI.enabled = true;
        GUILayout.EndArea();
    }

    private IEnumerator SubmitInstruction()
    {
        if (isSubmitting || string.IsNullOrWhiteSpace(instruction))
        {
            yield break;
        }

        isSubmitting = true;
        loader.ReportStatus("Applying scene edit...");

        var payload = new ModifierPayload { instruction = instruction };
        var body = Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload));

        using (var request = new UnityWebRequest(backendUrl, UnityWebRequest.kHttpVerbPOST))
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
                loader.ReportStatus("Edit failed — " + request.error);
                Debug.LogWarning("SketchSceneModifier: " + request.error);
            }
        }

        isSubmitting = false;
    }

    [System.Serializable]
    private class ModifierPayload
    {
        public string instruction;
    }
}