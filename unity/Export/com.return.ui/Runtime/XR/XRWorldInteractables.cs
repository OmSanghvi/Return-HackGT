using Return.Data;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit.Interactables;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

namespace Return.UI.XR
{
    /// <summary>
    /// A consistent physical pass over every world's props, run once WorldSession.WorldEntered fires: anything small
    /// enough to hold (WorldSession.IsHoldable, same rule everywhere so if one cup is grabbable every cup is) gets a
    /// Rigidbody, a convex collider and an XRGrabInteractable; everything bigger gets a static collider from its
    /// bounds so a grabbed prop can rest on a table instead of falling through it. Light haptic on hover, stronger on
    /// grab, and a tick on collision above a speed threshold while held (same amplitudes XRInputSupport uses for
    /// portals, same held/release shape XRLanternGrab uses for lanterns).
    /// </summary>
    static class XRWorldInteractables
    {
        const float CollisionSpeedThreshold = 0.6f; // m/s of relative speed before a held prop's bump ticks the controller

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void Init() { WorldSession.WorldEntered -= OnWorldEntered; WorldSession.WorldEntered += OnWorldEntered; }

        static void OnWorldEntered(Room room, Transform head)
        {
            var root = FindWorldRoot(room);
            if (root == null) return; // stub worlds have nothing authored worth making interactable
            foreach (var r in root.GetComponentsInChildren<MeshRenderer>(true))
                Setup(r);
        }

        /// <summary>WorldSceneRoot for scene-based worlds, or StubWorldLoader's "World:&lt;title&gt;" GameObject for the
        /// placeholder. Neither IWorldLoader nor WorldSceneRoot expose a root reference to this assembly, so this looks
        /// for what's already there instead of asking the loader for it.</summary>
        static Transform FindWorldRoot(Room room)
        {
            var wsr = Object.FindFirstObjectByType<WorldSceneRoot>();
            if (wsr != null) return wsr.transform;
            var stub = GameObject.Find("World:" + room.title);
            return stub != null ? stub.transform : null;
        }

        static void Setup(MeshRenderer r)
        {
            if (r == null || r.GetComponent<Rigidbody>() != null) return; // already handled (e.g. a Lantern under here, unlikely but cheap to check)
            if (r.GetComponentInParent<HubEnvironment>() != null) return; // sky dome / panorama / floor / water / lanterns: not props
            var n = r.gameObject.name.ToLowerInvariant();
            if (n.Contains("floor") || n.Contains("sky") || n.Contains("dome")) return; // belt-and-suspenders name check

            var mesh = r.GetComponent<MeshFilter>()?.sharedMesh;
            if (mesh == null) return;
            var go = r.gameObject;

            if (WorldSession.IsHoldable(r.bounds.size))
            {
                var col = go.GetComponent<Collider>();
                if (col == null) { var mc = go.AddComponent<MeshCollider>(); mc.convex = true; col = mc; }
                var rb = go.AddComponent<Rigidbody>();
                var grab = go.AddComponent<XRGrabInteractable>();
                grab.colliders.Add(col);
                grab.throwOnDetach = true;
                grab.hoverEntered.AddListener(a => Haptic(a.interactorObject, 0.08f, 0.02f));
                grab.selectEntered.AddListener(a => Haptic(a.interactorObject, 0.4f, 0.08f));
                go.AddComponent<HeldCollisionHaptics>().grab = grab;
            }
            else
            {
                if (go.GetComponent<Collider>() == null)
                {
                    var box = go.AddComponent<BoxCollider>();
                    box.center = go.transform.InverseTransformPoint(r.bounds.center);
                    box.size = Vector3.Scale(r.bounds.size, Invert(go.transform.lossyScale));
                }
                // ponytail: full physics hands (tracked hands stopping at the table edge instead of clipping through)
                // are skipped here; this pass only gives props colliders for XRGrabInteractable + Rigidbody to rest on.
                // Add hand-stopping colliders on the hand skeleton if the demo ends up using hand tracking instead of controllers.
            }
        }

        static Vector3 Invert(Vector3 v) => new Vector3(v.x != 0 ? 1f / v.x : 1f, v.y != 0 ? 1f / v.y : 1f, v.z != 0 ? 1f / v.z : 1f);

        static void Haptic(IXRInteractor interactor, float amplitude, float duration)
            => (interactor as XRBaseInputInteractor)?.SendHapticImpulse(amplitude, duration);

        /// <summary>While held, a tick above CollisionSpeedThreshold (a prop knocking a table or another prop) reaches
        /// whichever controller is holding it, the same haptic shape as a grab.</summary>
        class HeldCollisionHaptics : MonoBehaviour
        {
            public XRGrabInteractable grab;
            void OnCollisionEnter(Collision c)
            {
                if (grab == null || grab.firstInteractorSelecting == null) return; // only while held
                if (c.relativeVelocity.magnitude < CollisionSpeedThreshold) return;
                Haptic(grab.firstInteractorSelecting, 0.3f, 0.05f);
            }
        }
    }
}
