using Return.Design;
using Return.UI;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;
using UnityEngine.XR;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.Locomotion.Comfort;
using UnityEngine.XR.Interaction.Toolkit.Locomotion.Turning;
using UnityEngine.XR.Interaction.Toolkit.UI;

namespace Return.UI.XR
{
    /// <summary>
    /// Makes the XR Interaction Toolkit drive the Return UI without the package depending on XR:
    /// every SpatialPanel gets a TrackedDeviceGraphicRaycaster (ray, poke and pinch click glass buttons),
    /// every RoomPortal gets an XRSimpleInteractable (hover ripples and brightens it at the hit point, select activates it).
    /// A poke/near-far interactor works the same way: XRI routes its hover and poke-select through the same events.
    /// Also holds the runtime-only comfort/rig fixups that would otherwise need a scene rebuild (floor tracking, smooth
    /// turn, refresh rate, foveation) and the hold-to-exit shortcut back to the hub.
    /// </summary>
    static class XRInputSupport
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void Init()
        {
            SpatialPanel.Created -= OnPanel; SpatialPanel.Created += OnPanel;
            RoomPortal.Created -= OnPortal; RoomPortal.Created += OnPortal;
        }

        static void OnPanel(SpatialPanel p)
        {
            if (p.GetComponent<TrackedDeviceGraphicRaycaster>() == null) p.gameObject.AddComponent<TrackedDeviceGraphicRaycaster>();
        }

        static void OnPortal(RoomPortal portal)
        {
            var col = portal.GetComponent<Collider>();
            var it = portal.gameObject.AddComponent<XRSimpleInteractable>();
            it.colliders.Add(col);
            it.hoverEntered.AddListener(a =>
            {
                portal.Touch(TouchPoint(a.interactorObject, it));
                Haptic(a.interactorObject, 0.1f, 0.03f);
            });
            it.selectEntered.AddListener(a =>
            {
                portal.Activate();
                Haptic(a.interactorObject, 0.5f, 0.1f);
            });
        }

        static Vector3 TouchPoint(IXRInteractor interactor, XRSimpleInteractable interactable)
        {
            var attach = interactor?.GetAttachTransform(interactable);
            if (attach != null) return attach.position;
            return interactor != null ? interactor.transform.position : interactable.transform.position;
        }

        /// <summary>Not every interactor drives a physical controller (gaze, mock devices in tests), so this is best-effort.</summary>
        static void Haptic(IXRInteractor interactor, float amplitude, float duration)
            => (interactor as XRBaseInputInteractor)?.SendHapticImpulse(amplitude, duration);

        // ---- comfort / rig fixups, applied to whatever rig is already in the loaded scene -----------------------------
        // These run on every scene load (including additive world scenes, harmlessly) so ReturnHub.unity keeps working
        // without a rebuild; ReturnVRSceneBuilder sets the same values for a freshly-built scene.

        public const float TurnSpeedDegPerSec = 75f; // ReturnVRSceneBuilder uses the same constant for a fresh rig.
        const float DisplayRefreshHz = 72f; // 90 is the other option on Quest; 72 is the safer default for busy world scenes.

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void SetupRigComfort()
        {
            foreach (var origin in Object.FindObjectsByType<XROrigin>(FindObjectsSortMode.None))
                origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Floor;

            foreach (var turn in Object.FindObjectsByType<ContinuousTurnProvider>(FindObjectsSortMode.None))
            {
                turn.turnSpeed = TurnSpeedDegPerSec;
                WireVignette(turn);
            }

            // ControllerInputActionManager lives in the optional Starter Assets sample (Unity.XR.Interaction.Toolkit.Samples.StarterAssets),
            // not a package this asmdef can reference directly without breaking projects that haven't imported the sample.
            // ponytail: reflection instead of a hard reference; switch to a direct call if the sample becomes a required dependency.
            foreach (var mb in Object.FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None))
            {
                if (mb.GetType().Name != "ControllerInputActionManager") continue;
                var prop = mb.GetType().GetProperty("smoothTurnEnabled");
                if (prop != null && prop.PropertyType == typeof(bool)) prop.SetValue(mb, true);
            }

            SetupDisplayAndFoveation();
            EnsureExitHoldRunner();
        }

        static void WireVignette(ContinuousTurnProvider turn)
        {
            var vignette = Object.FindFirstObjectByType<TunnelingVignetteController>();
            if (vignette == null) return; // no comfort vignette in this rig; nothing to wire
            var list = vignette.locomotionVignetteProviders;
            foreach (var p in list) if (p.locomotionProvider == turn) return; // already wired
            list.Add(new LocomotionVignetteProvider { locomotionProvider = turn, enabled = true });
        }

        /// <summary>Quest-only: 72Hz display refresh and fixed foveated rendering (High, gaze off). No-op in the editor,
        /// where there is no headset display subsystem to request this on. Every call is guarded so a version mismatch
        /// in the installed XR packages just logs once instead of failing scene load.</summary>
        static bool _loggedDisplayFailure;
        static void SetupDisplayAndFoveation()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                var displays = new System.Collections.Generic.List<XRDisplaySubsystem>();
                SubsystemManager.GetSubsystems(displays);
                if (displays.Count == 0) return;
                var display = displays[0];
                if (!display.TryRequestDisplayRefreshRate(DisplayRefreshHz) && !_loggedDisplayFailure)
                { Debug.LogWarning("Return: could not request a " + DisplayRefreshHz + "Hz display refresh."); _loggedDisplayFailure = true; }
                // Leaving foveatedRenderingFlags at its default (no GazeAllowed) means fixed, not gaze-tracked, foveation.
                display.foveatedRenderingLevel = 1f; // full strength ("High")
            }
            catch (System.Exception e)
            {
                if (!_loggedDisplayFailure) { Debug.LogWarning("Return: display refresh/foveation setup failed: " + e.Message); _loggedDisplayFailure = true; }
            }
#endif
        }

        // ---- hold-to-exit: hold the secondary button (B/Y) ~0.8s to leave a world, same path as the wrist menu -----------

        const float ExitHoldSeconds = 0.8f;

        static void EnsureExitHoldRunner()
        {
            if (GameObject.Find("XRExitHold") != null) return;
            var go = new GameObject("XRExitHold");
            Object.DontDestroyOnLoad(go);
            go.AddComponent<ExitHoldRunner>();
        }

        class ExitHoldRunner : MonoBehaviour
        {
            float _t; SpatialPanel _ui; Image _fill;

            void Update()
            {
                var session = WorldSession.Active;
                bool inWorld = session != null && session.State == SessionState.InWorld;
                bool held = inWorld && SecondaryHeld();
                if (!held) { Cancel(); return; }

                _t += Time.unscaledDeltaTime;
                ShowProgress(Mathf.Clamp01(_t / ExitHoldSeconds));
                if (_t >= ExitHoldSeconds)
                {
                    Cancel();
                    session.RequestExit();
                }
            }

            static bool SecondaryHeld()
            {
                var devices = new System.Collections.Generic.List<InputDevice>();
                InputDevices.GetDevicesWithCharacteristics(InputDeviceCharacteristics.Controller, devices);
                foreach (var d in devices) if (d.TryGetFeatureValue(CommonUsages.secondaryButton, out bool b) && b) return true;
                // Editor / device simulator fallback so this is testable without a headset.
                return Application.isEditor && Keyboard.current != null && Keyboard.current.hKey.isPressed;
            }

            void ShowProgress(float t)
            {
                if (_ui == null)
                {
                    var head = Camera.main != null ? Camera.main.transform : null;
                    _ui = SpatialPanel.Create("ExitHoldRing", 140, 140);
                    if (head != null) _ui.PlaceInFront(head, 0.5f, 0.1f);
                    var bg = UI.Img(_ui.rect, "Bg", ColorRole.Glass, Shapes.Pill); UI.Stretch(bg.rectTransform); UI.Overlay(bg.rectTransform);
                    _fill = UI.Img(_ui.rect, "Fill", ColorRole.Sun, Shapes.Pill);
                    UI.Stretch(_fill.rectTransform); UI.Overlay(_fill.rectTransform);
                    _fill.type = Image.Type.Filled; _fill.fillMethod = Image.FillMethod.Radial360; _fill.fillOrigin = 2; _fill.fillClockwise = true;
                }
                if (_fill != null) _fill.fillAmount = t;
            }

            void Cancel()
            {
                _t = 0;
                if (_ui != null) { Destroy(_ui.gameObject); _ui = null; _fill = null; }
            }
        }
    }
}
