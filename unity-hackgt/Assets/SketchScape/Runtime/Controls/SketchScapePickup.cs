using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// A room object anyone can pick up to look at. In the headset, Meta's grab
/// (the Grabbable / HandGrabInteractable RoomKit adds) carries it; in the
/// Editor without a headset, left-click it (see DesktopPickup).
///
/// When a desktop hold ends it glides back to where it was picked up. Carrying
/// things around never changes the room: layout changes only happen through
/// saved, owner-checked edits (the room API), so nothing here talks to the
/// backend.
///
/// Ported from the team's unity/ project (unity/Assets/Scripts/SketchScapePickup.cs)
/// without its XR Interaction Toolkit grab: HackGTUnity rooms use Meta's
/// Interaction SDK. The object's place markers (RoomKit's "Shared Tag" and
/// "Contact Shadow" children) stay behind while it is carried, as the team's
/// contributor ring does.
/// </summary>
[DisallowMultipleComponent]
public sealed class SketchScapePickup : MonoBehaviour
{
    private static readonly string[] PlaceMarkers = { "Shared Tag", "Contact Shadow" };

    [SerializeField] private float returnSeconds = 0.6f;

    private Vector3 homePosition;
    private Quaternion homeRotation;
    private bool held;
    private Coroutine returning;
    private readonly List<Transform> leftBehind = new List<Transform>();

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
            // The markers show the object's place; leave them there.
            foreach (Transform child in transform)
            {
                if (System.Array.IndexOf(PlaceMarkers, child.name) >= 0)
                {
                    leftBehind.Add(child);
                }
            }
            foreach (var marker in leftBehind)
            {
                marker.SetParent(transform.parent, true);
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
        foreach (var marker in leftBehind)
        {
            if (marker != null)
            {
                marker.SetParent(transform, true);
            }
        }
        leftBehind.Clear();
        returning = null;
    }
}
