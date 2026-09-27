#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;
using UnityEngine.XR;

/// <summary>
/// Editor-only desktop camera for checking rooms without a headset: hold the
/// right mouse button to look around, WASD to move, Q/E to go down/up, Shift to
/// go faster; left-click drag picks up room objects (DesktopPickup). Added
/// automatically to the main camera whenever no XR headset is active, in any
/// scene; it is compiled out of player builds.
///
/// Ported from the team's unity/ project (unity/Assets/Scripts/DesktopCameraLook.cs).
/// HackGTUnity rooms use Meta's OVRCameraRig, which rewrites the center-eye pose
/// every frame from OVRManager's head-pose offsets when no headset is present,
/// so under that rig the pose goes through those offsets (what Meta's own
/// OVRHeadsetEmulator does) instead of the camera transform, and the emulator is
/// switched off while these controls run. The camera starts at standing eye
/// height, because without a headset it would sit on the floor.
/// </summary>
[DisallowMultipleComponent]
public sealed class DesktopCameraLook : MonoBehaviour
{
    [SerializeField] private float lookSensitivity = 0.15f;
    [SerializeField] private float moveSpeed = 2f;
    [SerializeField] private float fastMultiplier = 3f;
    [SerializeField] private float standingEyeHeight = 1.6f;

    private float yaw;
    private float pitch;
    private bool looking;
    private Vector3 position;
    private OVRCameraRig rig;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Install()
    {
        AttachToMainCamera();
        SceneManager.sceneLoaded += (_, _) => AttachToMainCamera();
    }

    private static void AttachToMainCamera()
    {
        if (XRSettings.isDeviceActive)
        {
            return; // A real headset drives the camera.
        }
        var camera = Camera.main;
        if (camera != null && camera.GetComponent<DesktopCameraLook>() == null)
        {
            camera.gameObject.AddComponent<DesktopCameraLook>();
            camera.gameObject.AddComponent<DesktopPickup>();
        }
    }

    private void OnEnable()
    {
        rig = GetComponentInParent<OVRCameraRig>();
        if (rig != null)
        {
            var emulator = rig.GetComponent<OVRHeadsetEmulator>();
            if (emulator != null)
            {
                emulator.enabled = false; // These controls replace it; both would write the same offsets.
            }
        }

        Vector3 angles = transform.eulerAngles;
        yaw = angles.y;
        pitch = angles.x > 180f ? angles.x - 360f : angles.x;
        position = transform.position;
        Transform space = transform.parent;
        if (rig != null && space != null)
        {
            Vector3 local = space.InverseTransformPoint(position);
            if (local.y < 0.5f)
            {
                local.y = standingEyeHeight;
                position = space.TransformPoint(local);
            }
        }
        Apply();
    }

    private void OnDisable()
    {
        SetLooking(false);
    }

    private void Update()
    {
        var mouse = Mouse.current;
        var keyboard = Keyboard.current;
        if (mouse == null || keyboard == null)
        {
            return;
        }

        SetLooking(mouse.rightButton.isPressed);
        if (looking)
        {
            Vector2 delta = mouse.delta.ReadValue() * lookSensitivity;
            yaw += delta.x;
            pitch = Mathf.Clamp(pitch - delta.y, -85f, 85f);
        }

        Vector3 input = Vector3.zero;
        if (keyboard.wKey.isPressed) input.z += 1f;
        if (keyboard.sKey.isPressed) input.z -= 1f;
        if (keyboard.dKey.isPressed) input.x += 1f;
        if (keyboard.aKey.isPressed) input.x -= 1f;
        if (keyboard.eKey.isPressed) input.y += 1f;
        if (keyboard.qKey.isPressed) input.y -= 1f;
        if (input != Vector3.zero)
        {
            float speed = moveSpeed * (keyboard.leftShiftKey.isPressed ? fastMultiplier : 1f);
            Vector3 flatForward = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
            Vector3 flatRight = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
            Vector3 move = flatForward * input.z + flatRight * input.x + Vector3.up * input.y;
            position += move.normalized * speed * Time.deltaTime;
        }

        // Every frame, so nothing else (a reset head pose) moves the view away.
        Apply();
    }

    private void Apply()
    {
        Quaternion rotation = Quaternion.Euler(pitch, yaw, 0f);
        Transform space = transform.parent;
        var manager = OVRManager.instance;
        if (rig != null && manager != null && space != null)
        {
            // OVRCameraRig sets the eye's local rotation to Euler(-x, -y, z) of the
            // rotation offset and its local position to the translation offset.
            Vector3 local = (Quaternion.Inverse(space.rotation) * rotation).eulerAngles;
            manager.headPoseRelativeOffsetRotation = new Vector3(-local.x, -local.y, local.z);
            manager.headPoseRelativeOffsetTranslation = space.InverseTransformPoint(position);
        }
        transform.SetPositionAndRotation(position, rotation);
    }

    private void SetLooking(bool value)
    {
        if (looking == value)
        {
            return;
        }
        looking = value;
        Cursor.lockState = value ? CursorLockMode.Locked : CursorLockMode.None;
        Cursor.visible = !value;
    }
}
#endif
