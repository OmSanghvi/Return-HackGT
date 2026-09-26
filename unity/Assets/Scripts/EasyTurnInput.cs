using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR.Interaction.Toolkit.Inputs;
#if UNITY_EDITOR
using UnityEditor;
#endif

/// <summary>
/// Makes thumbstick smooth turning forgiving. XRI's default "Turn" binding only
/// reacts inside the stick's exact left/right quarter (a Sector interaction that
/// also locks out if the stick passes through "up" first), and its turn provider
/// ignores diagonals. This replaces that binding's interactions with a processor
/// that keeps only the sideways part of the stick (after a small deadzone), so
/// any clear sideways push turns, faster the further it goes. Runtime-only
/// binding overrides: the XRI sample asset itself is untouched.
/// </summary>
[DisallowMultipleComponent]
public sealed class EasyTurnInput : MonoBehaviour
{
    private const string ProcessorName = "SketchScapeSidewaysOnly";
    private static readonly string[] LocomotionMaps = { "XRI Left Locomotion", "XRI Right Locomotion" };

#if UNITY_EDITOR
    [InitializeOnLoadMethod]
#endif
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
    private static void RegisterProcessor()
    {
        InputSystem.RegisterProcessor<SidewaysOnlyProcessor>(ProcessorName);
    }

    private void Start()
    {
        foreach (var manager in GetComponentsInChildren<InputActionManager>(true))
        {
            foreach (var asset in manager.actionAssets)
            {
                if (asset == null)
                {
                    continue;
                }
                foreach (string mapName in LocomotionMaps)
                {
                    var turn = asset.FindActionMap(mapName)?.FindAction("Turn");
                    if (turn == null)
                    {
                        continue;
                    }
                    for (int index = 0; index < turn.bindings.Count; index++)
                    {
                        if (turn.bindings[index].isComposite)
                        {
                            continue;
                        }
                        turn.ApplyBindingOverride(index, new InputBinding
                        {
                            overrideInteractions = string.Empty,
                            overrideProcessors = ProcessorName,
                        });
                    }
                }
            }
        }
    }
}

/// <summary>Keeps only the stick's sideways component, rescaled past a deadzone.</summary>
public sealed class SidewaysOnlyProcessor : InputProcessor<Vector2>
{
    // About 17° either side of straight up/down, so aiming a teleport (stick
    // forward) doesn't also turn.
    public float deadzone = 0.3f;

    public override Vector2 Process(Vector2 value, InputControl control)
    {
        float sideways = Mathf.Abs(value.x);
        if (sideways < deadzone)
        {
            return Vector2.zero;
        }
        return new Vector2(Mathf.Sign(value.x) * Mathf.InverseLerp(deadzone, 1f, sideways), 0f);
    }
}
