using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

/// <summary>
/// Visitor input for the guide bot, via XRI 3.6 input action references (not
/// hard-coded buttons): A/primaryButton = next, B/secondaryButton = repeat,
/// right trigger while the ray hovers a mapped element = ask_about, grip on
/// the bot = more, and a 6 s gaze dwell on an undiscussed, non-focus element
/// = linger. Everything is ignored while the bot is busy.
/// </summary>
public sealed class SketchScapeGuideInput : MonoBehaviour
{
    [SerializeField] private SketchScapeGuideBot bot;
    [SerializeField] private InputActionReference nextAction;
    [SerializeField] private InputActionReference repeatAction;
    [SerializeField] private InputActionReference activateAction;
    [SerializeField] private InputActionReference gripAction;
    [SerializeField] private XRRayInteractor rightRayInteractor;
    [SerializeField] private Camera gazeCamera;
    [SerializeField] private float gazeDwellSeconds = 6f;
    [SerializeField] private float gazePollIntervalSeconds = 0.2f;
    [SerializeField] private float gazeMaxDistance = 10f;

    private readonly HashSet<string> lingeredElementIds = new HashSet<string>();
    private string gazeElementId = "";
    private float gazeTimer;
    private float gazePollClock;

    /// <summary>Editor-time wiring hook (SketchScapeOfflineExperienceBuilder); Awake()
    /// also falls back to a scene search so this still works if left unset.</summary>
    public void Configure(SketchScapeGuideBot guideBot)
    {
        bot = guideBot;
    }

    private void Awake()
    {
        if (bot == null)
        {
            bot = FindAnyObjectByType<SketchScapeGuideBot>();
        }
        if (gazeCamera == null)
        {
            gazeCamera = Camera.main;
        }
    }

    private void OnEnable()
    {
        Subscribe(nextAction, OnNext);
        Subscribe(repeatAction, OnRepeat);
        Subscribe(activateAction, OnActivate);
        Subscribe(gripAction, OnGrip);
    }

    private void OnDisable()
    {
        Unsubscribe(nextAction, OnNext);
        Unsubscribe(repeatAction, OnRepeat);
        Unsubscribe(activateAction, OnActivate);
        Unsubscribe(gripAction, OnGrip);
    }

    private void Update()
    {
        if (bot == null || bot.Busy || gazeCamera == null)
        {
            return;
        }
        gazePollClock += Time.deltaTime;
        if (gazePollClock < gazePollIntervalSeconds)
        {
            return;
        }
        gazePollClock = 0f;
        UpdateGazeDwell();
    }

    private void UpdateGazeDwell()
    {
        string hoveredElementId = "";
        if (Physics.Raycast(gazeCamera.transform.position, gazeCamera.transform.forward, out var hit, gazeMaxDistance)
            && bot.ObjectMap.TryGetElementId(hit.collider.gameObject, out var elementId))
        {
            hoveredElementId = elementId;
        }

        if (hoveredElementId != gazeElementId)
        {
            gazeElementId = hoveredElementId;
            gazeTimer = 0f;
            return;
        }
        if (string.IsNullOrEmpty(gazeElementId) || lingeredElementIds.Contains(gazeElementId) || IsCurrentFocus(gazeElementId))
        {
            return;
        }

        gazeTimer += gazePollIntervalSeconds;
        if (gazeTimer >= gazeDwellSeconds)
        {
            lingeredElementIds.Add(gazeElementId);
            bot.SendEvent("linger", gazeElementId);
        }
    }

    private bool IsCurrentFocus(string elementId)
    {
        return bot.StepsById.TryGetValue(bot.CurrentStepId, out var step)
            && System.Array.IndexOf(step.focus_element_ids, elementId) >= 0;
    }

    private void OnNext(InputAction.CallbackContext _)
    {
        if (bot != null && !bot.Busy)
        {
            bot.SendEvent("next");
        }
    }

    private void OnRepeat(InputAction.CallbackContext _)
    {
        if (bot != null && !bot.Busy)
        {
            bot.SendEvent("repeat");
        }
    }

    private void OnActivate(InputAction.CallbackContext _)
    {
        if (bot == null || bot.Busy || rightRayInteractor == null)
        {
            return;
        }
        if (rightRayInteractor.TryGetCurrent3DRaycastHit(out var hit)
            && bot.ObjectMap.TryGetElementId(hit.collider.gameObject, out var elementId))
        {
            bot.SendEvent("ask_about", elementId);
        }
    }

    private void OnGrip(InputAction.CallbackContext _)
    {
        if (bot == null || bot.Busy || rightRayInteractor == null)
        {
            return;
        }
        // "Grip on the bot": only fires when the same ray is currently over the bot itself.
        if (rightRayInteractor.TryGetCurrent3DRaycastHit(out var hit) && hit.collider.gameObject == bot.gameObject)
        {
            bot.SendEvent("more");
        }
    }

    private static void Subscribe(InputActionReference reference, System.Action<InputAction.CallbackContext> handler)
    {
        if (reference != null && reference.action != null)
        {
            reference.action.performed += handler;
            reference.action.Enable();
        }
    }

    private static void Unsubscribe(InputActionReference reference, System.Action<InputAction.CallbackContext> handler)
    {
        if (reference != null && reference.action != null)
        {
            reference.action.performed -= handler;
        }
    }
}
