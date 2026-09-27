#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Editor-only stand-in for a controller grab: hold the left mouse button on a
/// SketchScapePickup to carry it in front of the camera, scroll to turn it,
/// release to let it go (it returns to its place). Installed with
/// DesktopCameraLook when no headset is active.
///
/// Ported from the team's unity/ project (unity/Assets/Scripts/DesktopPickup.cs);
/// the only change is that clicks ignore every collider in the camera's own rig,
/// since Meta's rig keeps its player capsule beside the camera, not above it.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(Camera))]
public sealed class DesktopPickup : MonoBehaviour
{
    [SerializeField] private float reach = 10f;
    [SerializeField] private float holdDistance = 0.7f;
    [SerializeField] private float scrollTurnDegrees = 0.15f;

    private Camera viewCamera;
    private SketchScapePickup carried;
    private Quaternion carriedRotation;

    private void Awake()
    {
        viewCamera = GetComponent<Camera>();
    }

    private void OnDisable()
    {
        Drop();
    }

    private void Update()
    {
        var mouse = Mouse.current;
        if (mouse == null)
        {
            return;
        }

        if (mouse.leftButton.wasPressedThisFrame)
        {
            TryPickUp(mouse);
        }
        else if (!mouse.leftButton.isPressed)
        {
            Drop();
        }

        if (carried != null)
        {
            float scroll = mouse.scroll.ReadValue().y;
            carriedRotation = Quaternion.AngleAxis(scroll * scrollTurnDegrees, Vector3.up) * carriedRotation;
            Transform target = carried.transform;
            Vector3 holdPoint = transform.position + transform.forward * holdDistance;
            target.SetPositionAndRotation(
                Vector3.Lerp(target.position, holdPoint, 1f - Mathf.Exp(-15f * Time.deltaTime)),
                transform.rotation * carriedRotation);
        }
    }

    private void TryPickUp(Mouse mouse)
    {
        // With the cursor locked (looking around) aim from the screen center.
        Vector2 aim = Cursor.lockState == CursorLockMode.Locked
            ? new Vector2(Screen.width / 2f, Screen.height / 2f)
            : mouse.position.ReadValue();
        SketchScapePickup pickup = FirstPickupAlong(viewCamera.ScreenPointToRay(aim));
        if (pickup == null || pickup.IsHeld)
        {
            return;
        }
        carried = pickup;
        carriedRotation = Quaternion.Inverse(transform.rotation) * pickup.transform.rotation;
        carried.BeginHold();
    }

    /// <summary>
    /// The first thing the ray hits, ignoring triggers and the camera's own rig
    /// (Meta's player capsule and hand colliders stay around the spawn point and
    /// would otherwise block clicks aimed across them).
    /// </summary>
    public SketchScapePickup FirstPickupAlong(Ray ray)
    {
        RaycastHit[] hits = Physics.RaycastAll(ray, reach, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore);
        System.Array.Sort(hits, (left, right) => left.distance.CompareTo(right.distance));
        foreach (var hit in hits)
        {
            if (hit.collider.transform.IsChildOf(transform.root))
            {
                continue;
            }
            return hit.collider.GetComponentInParent<SketchScapePickup>();
        }
        return null;
    }

    private void OnGUI()
    {
        // While looking around the cursor is hidden and clicks aim from the center.
        if (Cursor.lockState == CursorLockMode.Locked)
        {
            GUI.Box(new Rect(Screen.width / 2f - 3f, Screen.height / 2f - 3f, 6f, 6f), GUIContent.none);
        }
    }

    private void Drop()
    {
        if (carried == null)
        {
            return;
        }
        carried.EndHold();
        carried = null;
    }
}
#endif
