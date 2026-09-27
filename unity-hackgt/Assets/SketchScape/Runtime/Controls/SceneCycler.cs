using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Cycles through the scenes in Build Settings so one APK can hold several rooms.
/// Press either thumbstick (click it in) on the Touch controllers to load the next room;
/// on a keyboard (Editor / desktop) press Tab. Installs itself on startup, survives loads.
/// </summary>
[DisallowMultipleComponent]
public sealed class SceneCycler : MonoBehaviour
{
    const float Cooldown = 1.5f;
    float _nextAllowed;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Install()
    {
        if (FindAnyObjectByType<SceneCycler>() != null) return;
        var go = new GameObject("Scene Cycler");
        DontDestroyOnLoad(go);
        go.AddComponent<SceneCycler>();
    }

    void Update()
    {
        if (Time.unscaledTime < _nextAllowed) return;
        bool pressed = false;
        try
        {
            pressed = OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick) ||
                      OVRInput.GetDown(OVRInput.Button.SecondaryThumbstick);
        }
        catch { /* no OVR runtime */ }
        if (!pressed && Input.GetKeyDown(KeyCode.Tab)) pressed = true;
        if (!pressed) return;

        int count = SceneManager.sceneCountInBuildSettings;
        if (count < 2) return;
        int next = (SceneManager.GetActiveScene().buildIndex + 1) % count;
        _nextAllowed = Time.unscaledTime + Cooldown;
        Debug.Log("SceneCycler: loading scene " + next + "/" + count);
        SceneManager.LoadScene(next, LoadSceneMode.Single);
    }
}
