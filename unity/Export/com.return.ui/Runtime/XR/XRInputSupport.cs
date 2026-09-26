using Return.UI;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.UI;

namespace Return.UI.XR
{
    /// <summary>
    /// Makes the XR Interaction Toolkit drive the Return UI without the package depending on XR:
    /// every SpatialPanel gets a TrackedDeviceGraphicRaycaster (ray, poke and pinch click glass buttons),
    /// every RoomPortal gets an XRSimpleInteractable (hover ripples and brightens it at the hit point, select activates it).
    /// A poke/near-far interactor works the same way: XRI routes its hover and poke-select through the same events.
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
    }
}
