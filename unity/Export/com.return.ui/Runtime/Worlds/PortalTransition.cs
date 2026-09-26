using System.Threading.Tasks;
using Return.Design;
using UnityEngine;
using UnityEngine.Rendering;

namespace Return.UI
{
    /// <summary>
    /// Step through a portal instead of a plain cut: the chosen portal bumps up, the XR Origin (not the camera, so tracking
    /// survives) glides ~1m into or out of the arch, and a comfort vignette tightens then releases across the move.
    /// WorldSession calls EnterStep/ExitStep around its existing fade/load; this file owns only the glide and vignette.
    /// </summary>
    public class PortalTransition
    {
        const float GlideDistance = 1f;
        const float MaxVignette = 0.55f;
        public float glideSeconds = 1.1f;

        Material _vignetteMat;
        Vector3 _rigStart;
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

        async Task Glide(Transform rig, Vector3 from, Vector3 to, RoomPortal bloomPortal)
        {
            var baseScale = bloomPortal != null ? bloomPortal.transform.localScale : Vector3.one;
            float t = 0;
            while (t < glideSeconds)
            {
                t += Time.unscaledDeltaTime;
                float x = Mathf.Clamp01(t / glideSeconds);
                float e = EaseInOut(x);
                float bump = Mathf.Sin(x * Mathf.PI); // rises then falls across the whole glide: comfort in, comfort out
                if (rig != null) rig.position = Vector3.Lerp(from, to, e);
                if (bloomPortal != null) bloomPortal.transform.localScale = baseScale * (1f + 0.15f * bump);
                SetVignette(bump * MaxVignette);
                await Task.Yield();
            }
            if (rig != null) rig.position = to;
            if (bloomPortal != null) bloomPortal.transform.localScale = baseScale;
            SetVignette(0f);
        }

        /// <summary>Glide the rig ~1m into the portal's arch. Call before hiding the hub / loading the world.</summary>
        public Task EnterStep(RoomPortal portal, Transform head)
        {
            ReturnAudio.Play(ReturnAudio.WhooshIn, 0.45f);
            var rig = head != null ? head.root : null;
            _rigStart = rig != null ? rig.position : Vector3.zero;
            return Glide(rig, _rigStart, _rigStart + FlatForward(head) * GlideDistance, portal);
        }

        /// <summary>Glide the rig ~1m back out, restoring the position it had before EnterStep. Call after the hub is shown again.</summary>
        public Task ExitStep(Transform head)
        {
            ReturnAudio.Play(ReturnAudio.WhooshOut, 0.45f);
            var rig = head != null ? head.root : null;
            var current = rig != null ? rig.position : Vector3.zero;
            return Glide(rig, current, _rigStart, null);
        }
    }
}
