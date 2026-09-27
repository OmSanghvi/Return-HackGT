using System.Collections;
using Oculus.Interaction;
using Oculus.Interaction.Locomotion;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.XR;

/// <summary>
/// Headset comfort for SketchScape rooms, installed automatically on the scene's
/// OVRCameraRig (no RoomKit step needed):
///
/// Head collision - thumbstick movement already stops at room objects (the
/// Interaction SDK's character capsule), but walking or leaning in the real
/// room moves the head straight through them. Each frame, after tracking has
/// moved the head, a small sphere at the eyes is tested against the room's
/// colliders and the rig is pushed back out along the floor, so the view never
/// ends up inside an object. Objects being held are ignored, as are triggers
/// and the rig's own colliders.
///
/// Smooth turning - the comprehensive rig ships with 45-degree snap turns;
/// the thumbstick turns smoothly instead.
/// </summary>
[DisallowMultipleComponent]
[DefaultExecutionOrder(10000)]
public sealed class HeadCollisionGuard : MonoBehaviour
{
    [SerializeField] private float headRadius = 0.15f;
    [SerializeField] private float smoothTurnDegreesPerSecond = 90f;

    private readonly Collider[] overlaps = new Collider[16];
    private OVRCameraRig rig;
    private SphereCollider probe;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Install()
    {
        AttachToRig();
        SceneManager.sceneLoaded += (_, _) => AttachToRig();
    }

    private static void AttachToRig()
    {
        var found = FindAnyObjectByType<OVRCameraRig>();
        if (found != null && found.GetComponent<HeadCollisionGuard>() == null)
        {
            found.gameObject.AddComponent<HeadCollisionGuard>();
        }
    }

    private void Awake()
    {
        rig = GetComponent<OVRCameraRig>();
        // ComputePenetration needs a collider shape; a trigger touches nothing else.
        var probeGo = new GameObject("Head Collision Probe");
        probeGo.transform.SetParent(transform, false);
        probe = probeGo.AddComponent<SphereCollider>();
        probe.isTrigger = true;
        probe.radius = headRadius;
    }

    private IEnumerator Start()
    {
        // TurningSetting applies its style once it has started; override it after that.
        yield return null;
        foreach (var turning in GetComponentsInChildren<TurningSetting>(true))
        {
            turning.RotationSmoothVelocity.Value = smoothTurnDegreesPerSecond;
            turning.ControllerTurn.Value = TurningSetting.RotationStyle.Smooth;
        }
    }

    private void LateUpdate()
    {
        // Without a headset the Editor's desktop camera flies freely on purpose.
        if (!XRSettings.isDeviceActive || rig == null || rig.centerEyeAnchor == null)
        {
            return;
        }

        Vector3 head = rig.centerEyeAnchor.position;
        probe.transform.position = head;
        int count = Physics.OverlapSphereNonAlloc(head, headRadius, overlaps, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore);
        Vector3 push = Vector3.zero;
        for (int i = 0; i < count; i++)
        {
            Collider other = overlaps[i];
            if (other.transform.IsChildOf(transform) || IsHeld(other))
            {
                continue;
            }
            if (Physics.ComputePenetration(probe, head, Quaternion.identity,
                    other, other.transform.position, other.transform.rotation,
                    out Vector3 direction, out float distance))
            {
                push += direction * distance;
            }
        }

        // Only along the floor: pushing the view up or down is disorienting.
        push.y = 0f;
        if (push.sqrMagnitude > 1e-6f)
        {
            transform.position += push;
        }
    }

    private static bool IsHeld(Collider other)
    {
        var grabbable = other.GetComponentInParent<Grabbable>();
        return grabbable != null && grabbable.SelectingPointsCount > 0;
    }
}
