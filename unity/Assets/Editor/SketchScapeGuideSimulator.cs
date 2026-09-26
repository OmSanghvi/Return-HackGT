using UnityEditor;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Tools/SketchScape/Guide/Simulate Tour: drives the guide bot in Play mode
/// with a keyboard, no headset needed, against whatever apiBaseUrl the scene's
/// SketchScapeGuideClient is configured for (point it at `uvicorn` in mock
/// mode to test offline). N = next, R = repeat, M = more, left-click an
/// object = ask_about.
/// </summary>
public static class SketchScapeGuideSimulator
{
    [MenuItem("Tools/SketchScape/Guide/Simulate Tour")]
    public static void SimulateTour()
    {
        if (!EditorApplication.isPlaying)
        {
            EditorApplication.playModeStateChanged -= OnPlayModeStateChanged;
            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
            EditorApplication.isPlaying = true;
        }
        else
        {
            AttachDriver();
        }
    }

    private static void OnPlayModeStateChanged(PlayModeStateChange change)
    {
        if (change != PlayModeStateChange.EnteredPlayMode)
        {
            return;
        }
        EditorApplication.playModeStateChanged -= OnPlayModeStateChanged;
        AttachDriver();
    }

    private static void AttachDriver()
    {
        var bot = Object.FindAnyObjectByType<SketchScapeGuideBot>();
        if (bot == null)
        {
            Debug.LogWarning("SketchScapeGuideSimulator: no SketchScapeGuideBot in the running scene.");
            return;
        }
        if (bot.GetComponent<SketchScapeGuideSimulatorDriver>() == null)
        {
            bot.gameObject.AddComponent<SketchScapeGuideSimulatorDriver>();
        }
    }

    /// <summary>Editor-only (this file's assembly is excluded from player builds),
    /// so this never ships in a build even though it's a MonoBehaviour.</summary>
    private sealed class SketchScapeGuideSimulatorDriver : MonoBehaviour
    {
        private SketchScapeGuideBot bot;

        private void Awake()
        {
            bot = GetComponent<SketchScapeGuideBot>();
        }

        private void Update()
        {
            if (bot == null || bot.Busy || Keyboard.current == null)
            {
                return;
            }
            if (Keyboard.current.nKey.wasPressedThisFrame)
            {
                bot.SendEvent("next");
            }
            else if (Keyboard.current.rKey.wasPressedThisFrame)
            {
                bot.SendEvent("repeat");
            }
            else if (Keyboard.current.mKey.wasPressedThisFrame)
            {
                bot.SendEvent("more");
            }
            else if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
            {
                TryAskAbout();
            }
        }

        private void TryAskAbout()
        {
            var camera = Camera.main;
            if (camera == null)
            {
                return;
            }
            Vector2 screenPoint = Mouse.current.position.ReadValue();
            Ray ray = camera.ScreenPointToRay(screenPoint);
            if (Physics.Raycast(ray, out var hit, 100f) && bot.ObjectMap.TryGetElementId(hit.collider.gameObject, out var elementId))
            {
                bot.SendEvent("ask_about", elementId);
            }
        }
    }
}
