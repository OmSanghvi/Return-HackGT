#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;
using UnityEngine.XR;

/// <summary>
/// Editor-only desktop camera for checking scenes without a headset: hold the
/// right mouse button to look around, WASD to move, Q/E to go down/up, Shift to
/// go faster; left-click drag picks up small objects (DesktopPickup). Added
/// automatically to the main camera whenever no XR headset is
/// active, in any scene; it is compiled out of player builds.
/// </summary>
[DisallowMultipleComponent]
public sealed class DesktopCameraLook : MonoBehaviour
{
    [SerializeField] private float lookSensitivity = 0.15f;
    [SerializeField] private float moveSpeed = 2f;
    [SerializeField] private float fastMultiplier = 3f;

    private float yaw;
    private float pitch;
    private bool looking;

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
        Vector3 angles = transform.eulerAngles;
        yaw = angles.y;
        pitch = angles.x > 180f ? angles.x - 360f : angles.x;
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
            transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
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
            transform.position += move.normalized * speed * Time.deltaTime;
        }
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
