using System;
using System.Collections;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Unity's client for the guide runtime (Build Plan step 32):
/// `/v1/rooms/{project_id}/guide/*`. Same UnityWebRequest + apiBaseUrl +
/// X-SketchScape-Dev-User pattern as SketchScapeReconstructionClient and
/// SceneInteractionController. Never holds a model key -- the backend is the
/// only thing that talks to Muse (Hard Rule 4).
/// </summary>
public sealed class SketchScapeGuideClient : MonoBehaviour
{
    [Header("SketchScape API")]
    [SerializeField] private string apiBaseUrl = "http://127.0.0.1:8000";
    [SerializeField] private float requestTimeoutSeconds = 15f;
    [Tooltip("Sent as X-SketchScape-Dev-User when no AccountSwitcher (step 22) exists yet.")]
    [SerializeField] private string defaultAccount = "dev-user";

    public string SessionId { get; private set; }
    public int TurnSeq { get; private set; }

    private GuideEvent lastEvent;
    private string lastClientTurnId;

    public IEnumerator GetTour(string projectId, Action<GuideTourResponse> onComplete, Action<string> onError)
    {
        string url = apiBaseUrl.TrimEnd('/') + "/v1/rooms/" + projectId + "/guide/tour";
        using (var request = UnityWebRequest.Get(url))
        {
            ConfigureRequest(request);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                onError?.Invoke(request.error);
                yield break;
            }
            var tour = JsonUtility.FromJson<GuideTourResponse>(request.downloadHandler.text);
            if (tour == null)
            {
                onError?.Invoke("Guide tour response was invalid.");
                yield break;
            }
            onComplete?.Invoke(tour);
        }
    }

    public IEnumerator StartSession(string projectId, Action<GuideSessionResponse> onComplete, Action<string> onError)
    {
        string url = apiBaseUrl.TrimEnd('/') + "/v1/rooms/" + projectId + "/guide/sessions";
        using (var request = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
        {
            request.uploadHandler = new UploadHandlerRaw(Array.Empty<byte>());
            ConfigureRequest(request);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                onError?.Invoke(request.error);
                yield break;
            }
            var session = JsonUtility.FromJson<GuideSessionResponse>(request.downloadHandler.text);
            if (session == null)
            {
                onError?.Invoke("Guide session response was invalid.");
                yield break;
            }
            SessionId = session.session_id;
            TurnSeq = 1; // turn 0 (the scripted start turn) is already recorded server-side.
            onComplete?.Invoke(session);
        }
    }

    /// <summary>
    /// Sends one turn event. On success advances TurnSeq. On a 409 (another
    /// turn for this session won a race, or we drifted), resyncs TurnSeq to
    /// the server's turn_count and hands the caller its last known turn
    /// instead, per the skill: "On 409, applies the returned turn and sets
    /// turnSeq to the server's value."
    /// </summary>
    public IEnumerator SendTurn(string projectId, GuideEvent evt, Action<GuideTurnResponse> onComplete, Action<string> onError)
    {
        if (string.IsNullOrEmpty(SessionId))
        {
            onError?.Invoke("SendTurn called before StartSession.");
            yield break;
        }

        string clientTurnId = ReferenceEquals(evt, lastEvent) && lastClientTurnId != null
            ? lastClientTurnId
            : Guid.NewGuid().ToString("N");
        lastEvent = evt;
        lastClientTurnId = clientTurnId;

        var body = new GuideTurnRequestBody { client_turn_id = clientTurnId, turn_seq = TurnSeq, @event = evt };
        byte[] payload = Encoding.UTF8.GetBytes(JsonUtility.ToJson(body));
        string url = apiBaseUrl.TrimEnd('/') + "/v1/rooms/" + projectId + "/guide/sessions/" + SessionId + "/turns";

        using (var request = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
        {
            request.uploadHandler = new UploadHandlerRaw(payload);
            ConfigureRequest(request);
            yield return request.SendWebRequest();

            if (request.responseCode == 409)
            {
                var conflict = JsonUtility.FromJson<GuideTurnConflict>(request.downloadHandler.text);
                if (conflict != null)
                {
                    TurnSeq = conflict.turn_count;
                    if (!string.IsNullOrEmpty(conflict.last_turn?.step_id))
                    {
                        onComplete?.Invoke(conflict.last_turn);
                        yield break;
                    }
                }
                onError?.Invoke("Guide session resynced; retry the next event.");
                yield break;
            }

            if (request.result != UnityWebRequest.Result.Success)
            {
                onError?.Invoke(request.error);
                yield break;
            }

            var turn = JsonUtility.FromJson<GuideTurnResponse>(request.downloadHandler.text);
            if (turn == null)
            {
                onError?.Invoke("Guide turn response was invalid.");
                yield break;
            }
            TurnSeq++;
            onComplete?.Invoke(turn);
        }
    }

    private void ConfigureRequest(UnityWebRequest request)
    {
        request.downloadHandler = new DownloadHandlerBuffer();
        request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("X-SketchScape-Dev-User", ResolveAccount());
    }

    // Reflection, not a compile-time reference: AccountSwitcher (Build Plan
    // step 22) doesn't exist in this checkout yet. Once it lands, this picks
    // it up with no code change here.
    private string ResolveAccount()
    {
        Type switcherType = Type.GetType("AccountSwitcher");
        if (switcherType != null)
        {
            PropertyInfo current = switcherType.GetProperty("Current", BindingFlags.Public | BindingFlags.Static);
            if (current != null && current.GetValue(null) is string account && !string.IsNullOrWhiteSpace(account))
            {
                return account;
            }
        }
        return defaultAccount;
    }
}
