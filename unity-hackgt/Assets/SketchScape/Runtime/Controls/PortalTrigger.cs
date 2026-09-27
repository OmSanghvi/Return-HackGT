using System.Collections;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Walk-through doorway trigger. When the player's head enters the local-space doorway box it fades the
/// screen (via OVRScreenFade when present) and loads <see cref="targetScene"/>.
/// </summary>
public sealed class PortalTrigger : MonoBehaviour
{
    [Tooltip("Scene name to load when the head enters the doorway. Empty = disabled.")]
    public string targetScene = "";

    [Tooltip("Local-space doorway box: x = width, y = height from this object's origin upward, z = depth centred on the origin.")]
    public Vector3 size = new Vector3(1.4f, 2.3f, 0.6f);

    [Tooltip("Seconds after enable before the portal can fire, so a player arriving through a portal is not bounced straight back.")]
    public float armDelay = 2.5f;

    [Tooltip("Fade-out duration (seconds) before the scene load.")]
    public float fadeSeconds = 0.5f;

    private OVRCameraRig _rig;
    private float _enabledAt;
    private bool _firing;

    private void OnEnable()
    {
        _enabledAt = Time.unscaledTime;
        _firing = false;
    }

    private void Update()
    {
        if (_firing) return;
        if (string.IsNullOrEmpty(targetScene)) return;
        if (Time.unscaledTime - _enabledAt < armDelay) return;

        Transform head = FindHead();
        if (head == null) return;

        Vector3 p = transform.InverseTransformPoint(head.position);
        bool inside = Mathf.Abs(p.x) < size.x * 0.5f
                   && p.y > 0.1f
                   && p.y < size.y
                   && Mathf.Abs(p.z) < size.z * 0.5f;
        if (inside)
        {
            Fire();
        }
    }

    private Transform FindHead()
    {
        if (_rig == null)
        {
            _rig = FindAnyObjectByType<OVRCameraRig>();
        }
        if (_rig != null && _rig.centerEyeAnchor != null)
        {
            return _rig.centerEyeAnchor;
        }
        Camera cam = Camera.main;
        return cam != null ? cam.transform : null;
    }

    private void Fire()
    {
        if (_firing) return;
        _firing = true;

        Debug.Log("PortalTrigger: -> " + targetScene);

        OVRScreenFade fade = OVRScreenFade.instance;
        if (fade != null)
        {
            fade.fadeTime = fadeSeconds;
            fade.FadeOut();
        }

        StartCoroutine(LoadAfterDelay(fadeSeconds));
    }

    private IEnumerator LoadAfterDelay(float seconds)
    {
        if (seconds > 0f)
        {
            yield return new WaitForSecondsRealtime(seconds);
        }
        SceneManager.LoadScene(targetScene, LoadSceneMode.Single);
    }

    private void OnDrawGizmosSelected()
    {
        Gizmos.color = Color.cyan;
        Gizmos.matrix = transform.localToWorldMatrix;
        Gizmos.DrawWireCube(new Vector3(0f, size.y * 0.5f, 0f), size);
        Gizmos.matrix = Matrix4x4.identity;
    }
}
