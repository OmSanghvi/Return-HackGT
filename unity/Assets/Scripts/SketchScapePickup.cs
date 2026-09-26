using System.Collections;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit.Interactables;

/// <summary>
/// A room object anyone can pick up to look at (compiled scene object
/// `grabbable`). In the headset, grab it with either controller (XRI); in the
/// Editor without a headset, left-click it (see DesktopPickup).
///
/// When released it glides back to where it was picked up. Carrying things
/// around never changes the room: layout changes only happen through saved,
/// owner-checked edits (the room API), so nothing here talks to the backend.
/// </summary>
[DisallowMultipleComponent]
public sealed class SketchScapePickup : MonoBehaviour
{
    [SerializeField] private float returnSeconds = 0.6f;

    private Vector3 homePosition;
    private Quaternion homeRotation;
    private bool held;
    private Coroutine returning;
    private Transform detachedRing;

    public bool IsHeld => held;

    private void Awake()
    {
        if (GetComponent<Collider>() == null)
        {
            gameObject.AddComponent<BoxCollider>();
        }

        var body = GetComponent<Rigidbody>();
        if (body == null)
        {
            body = gameObject.AddComponent<Rigidbody>();
        }
        body.isKinematic = true;
        body.useGravity = false;

        var grab = GetComponent<XRGrabInteractable>();
        if (grab == null)
        {
            grab = gameObject.AddComponent<XRGrabInteractable>();
        }
        grab.movementType = XRBaseInteractable.MovementType.Kinematic;
        grab.throwOnDetach = false;
        grab.useDynamicAttach = true; // Hold it where the hand touched, not by its pivot.
        grab.selectEntered.AddListener(_ => BeginHold());
        grab.selectExited.AddListener(_ => EndHold());
    }

    public void BeginHold()
    {
        if (held)
        {
            return;
        }
        if (returning != null)
        {
            // Caught mid-return: keep the original home.
            StopCoroutine(returning);
            returning = null;
        }
        else
        {
            homePosition = transform.position;
            homeRotation = transform.rotation;
            // The contributor's ring marks the object's place; leave it there.
            var attribution = GetComponent<ContributorAttribution>();
            detachedRing = attribution != null ? attribution.Ring : null;
            if (detachedRing != null)
            {
                detachedRing.SetParent(transform.parent, true);
            }
        }
        held = true;
    }

    public void EndHold()
    {
        if (!held)
        {
            return;
        }
        held = false;
        returning = StartCoroutine(ReturnHome());
    }

    private IEnumerator ReturnHome()
    {
        Vector3 startPosition = transform.position;
        Quaternion startRotation = transform.rotation;
        for (float elapsed = 0f; elapsed < returnSeconds; elapsed += Time.deltaTime)
        {
            float t = Mathf.SmoothStep(0f, 1f, elapsed / returnSeconds);
            transform.SetPositionAndRotation(
                Vector3.Lerp(startPosition, homePosition, t),
                Quaternion.Slerp(startRotation, homeRotation, t));
            yield return null;
        }
        transform.SetPositionAndRotation(homePosition, homeRotation);
        if (detachedRing != null)
        {
            detachedRing.SetParent(transform, true);
            detachedRing = null;
        }
        returning = null;
    }
}
