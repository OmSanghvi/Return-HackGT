using System.Threading.Tasks;
using Return.Design;
using UnityEngine;
using UnityEngine.Rendering;

namespace Return.UI
{
    /// <summary>
    /// Step through a portal instead of a plain cut: the rig never moves. The chosen portal swells toward the viewer
    /// over ~1s, filling the view, with a comfort vignette rising alongside it, while the screen fades to opaque.
    /// WorldSession starts the fade partway through EnterStep, calls Restore right after the fade goes opaque (while the screen hides
    /// it), and ExitStep on the way back for the whoosh only. This file owns just the bloom and vignette.
    /// </summary>
    public class PortalTransition
    {
        const float FillDistance = 0.35f; // how close the swollen portal ends up in front of the head
        const float FillScale = 2.5f;     // grows to this multiple of its ring size so the window fills the view
        const float MaxVignette = 0.55f;
        public float bloomSeconds = 1.0f;

        Material _vignetteMat;
        Transform _portal;
        Vector3 _portalLocalPos, _portalLocalScale;
        static readonly int AmountId = Shader.PropertyToID("_Amount");

        public PortalTransition(Transform head)
        {
            var camGo = CameraTransform(head);
            if (camGo == null) return;
            var go = new GameObject("ReturnVignette"); go.transform.SetParent(camGo, false);
            go.transform.localPosition = new Vector3(0, 0, 0.29f); go.transform.localScale = new Vector3(5, 5, 1);
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>(); r.shadowCastingMode = ShadowCastingMode.Off; r.receiveShadows = false;
            _vignetteMat = ReturnShaders.Create(ReturnShaders.Vignette);
            _vignetteMat.SetFloat("_ZTest", (float)CompareFunction.Always);
            r.sharedMaterial = _vignetteMat;
            SetVignette(0f);
        }

        static Transform CameraTransform(Transform head) =>
            head == null ? null : head.GetComponent<Camera>() != null ? head : head.GetComponentInChildren<Camera>()?.transform ?? head;

        void SetVignette(float amount) { if (_vignetteMat != null) _vignetteMat.SetFloat(AmountId, amount); }

        static float EaseInOut(float x) => x < 0.5f ? 4f * x * x * x : 1f - Mathf.Pow(-2f * x + 2f, 3f) / 2f;

        static Vector3 FlatForward(Transform head)
        {
            var fwd = head != null ? head.forward : Vector3.forward; fwd.y = 0;
            if (fwd.sqrMagnitude < 0.01f) fwd = Vector3.forward;
            return fwd.normalized;
        }

        /// <summary>Bloom the chosen portal toward the head over bloomSeconds, vignette rising alongside it. No portal
        /// (null) just rises the vignette on the same clock. Call before hiding the hub / loading the world.</summary>
        public async Task EnterStep(RoomPortal portal, Transform head)
        {
            ReturnAudio.Play(ReturnAudio.WhooshIn, 0.45f);
            var portalTr = portal != null ? portal.transform : null;
            Vector3 fromPos = Vector3.zero, toPos = Vector3.zero, fromScale = Vector3.one, toScale = Vector3.one;
            if (portalTr != null)
            {
                _portal = portalTr; _portalLocalPos = portalTr.localPosition; _portalLocalScale = portalTr.localScale;
                fromPos = portalTr.position; fromScale = portalTr.localScale;
                var headPos = head != null ? head.position : Vector3.zero;
                var dir = fromPos - headPos; if (dir.sqrMagnitude < 0.0001f) dir = FlatForward(head); else dir.Normalize();
                toPos = headPos + dir * FillDistance;
                toScale = fromScale * FillScale;
            }
            float t = 0;
            while (t < bloomSeconds)
            {
                t += Time.unscaledDeltaTime;
                float e = EaseInOut(Mathf.Clamp01(t / bloomSeconds));
                if (portalTr != null) { portalTr.position = Vector3.Lerp(fromPos, toPos, e); portalTr.localScale = Vector3.Lerp(fromScale, toScale, e); }
                SetVignette(e * MaxVignette);
                await Task.Yield();
            }
            if (portalTr != null) { portalTr.position = toPos; portalTr.localScale = toScale; }
            SetVignette(MaxVignette);
        }

        /// <summary>Put the bloomed portal back where it lives on the ring. Call once the screen is opaque (right after
        /// the fade-to-1 completes), so the snap-back is hidden. Safe to call with nothing bloomed.</summary>
        public void Restore()
        {
            if (_portal != null) { _portal.localPosition = _portalLocalPos; _portal.localScale = _portalLocalScale; _portal = null; }
            SetVignette(0f);
        }

        /// <summary>No glide back: the rig never moved, so this is just the return whoosh and a clean vignette.</summary>
        public Task ExitStep(Transform head)
        {
            ReturnAudio.Play(ReturnAudio.WhooshOut, 0.45f);
            SetVignette(0f);
            return Task.CompletedTask;
        }
    }
}
