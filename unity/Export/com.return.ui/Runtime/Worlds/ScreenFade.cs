using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering;

namespace Return.UI
{
    /// <summary>A quad glued to the camera that fades the view to a color. Never a cut: white-out for day worlds, deep blue for dusk.</summary>
    public class ScreenFade : MonoBehaviour
    {
        Material _m; float _alpha; Color _color = Color.white;
        static readonly int ColorId = Shader.PropertyToID("_Color");

        public float Alpha => _alpha;

        public static ScreenFade Attach(Transform camera)
        {
            var go = new GameObject("ReturnScreenFade"); go.transform.SetParent(camera, false);
            go.transform.localPosition = new Vector3(0, 0, 0.3f);
            go.transform.localScale = new Vector3(4, 4, 1);
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>(); r.shadowCastingMode = ShadowCastingMode.Off; r.receiveShadows = false;
            var f = go.AddComponent<ScreenFade>();
            f._m = new Material(Shader.Find("Return/Flat")) { hideFlags = HideFlags.HideAndDontSave };
            f._m.SetFloat("_ZTest", (float)CompareFunction.Always);
            r.sharedMaterial = f._m; r.enabled = false;
            return f;
        }

        public void SetColor(Color c) { _color = c; Apply(); }

        public void SetAlpha(float a) { _alpha = Mathf.Clamp01(a); Apply(); }

        void Apply() { _m.SetColor(ColorId, new Color(_color.r, _color.g, _color.b, _alpha)); GetComponent<Renderer>().enabled = _alpha > 0.001f; }

        public async Task FadeTo(float target, float seconds)
        {
            float from = _alpha, t = 0;
            if (seconds <= 0.0001f) { SetAlpha(target); return; }
            while (t < seconds) { t += Time.unscaledDeltaTime; SetAlpha(Mathf.Lerp(from, target, Mathf.SmoothStep(0, 1, t / seconds))); await Task.Yield(); }
            SetAlpha(target);
        }

        void OnDestroy() { if (_m != null) Destroy(_m); }
    }
}
