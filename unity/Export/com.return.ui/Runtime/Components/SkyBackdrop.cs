using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>A large painted sky window behind the UI. Crossfades between scenes through mist, drifts on its own, parallaxes with the viewer.</summary>
    [ExecuteAlways]
    public class SkyBackdrop : MonoBehaviour, IBackdrop
    {
        static readonly int Main = Shader.PropertyToID("_MainTex"), Depth = Shader.PropertyToID("_DepthTex"), TexB = Shader.PropertyToID("_TexB"), DepthB = Shader.PropertyToID("_DepthB"),
            AspA = Shader.PropertyToID("_AspA"), AspB = Shader.PropertyToID("_AspB"), Size = Shader.PropertyToID("_Size"), Mix = Shader.PropertyToID("_Mix"), Mist = Shader.PropertyToID("_Mist"),
            Zoom = Shader.PropertyToID("_Zoom"), Pointer = Shader.PropertyToID("_Pointer"), Fog = Shader.PropertyToID("_Fog"), Alpha = Shader.PropertyToID("_Alpha"), Arch = Shader.PropertyToID("_Arch"),
            Radius = Shader.PropertyToID("_Radius");

        public Vector2 size = new Vector2(12f, 6.75f);
        public float distance = 5f;
        public bool followCamera = true;

        Material _m; Renderer _r;
        SceneKey _cur = (SceneKey)(-1); SceneKey _next;
        float _mix, _mist, _mistTarget, _fade = -1;
        Transform _cam;

        public SceneKey Current => _cur;

        static Shader FindShader() => Shader.Find("Return/SkyParallax");

        void OnEnable() { Ensure(); }

        void Ensure()
        {
            if (_r != null) return;
            var mf = this.GetOrAdd<MeshFilter>();
            _r = this.GetOrAdd<MeshRenderer>();
            mf.sharedMesh = Quad();
            _m = new Material(FindShader()) { hideFlags = HideFlags.HideAndDontSave };
            _r.sharedMaterial = _m; _r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; _r.receiveShadows = false;
            transform.localScale = new Vector3(size.x, size.y, 1);
            _m.SetVector(Size, new Vector4(size.x, size.y, 0, 0));
            _m.SetFloat(Radius, 0); _m.SetFloat(Arch, 0); _m.SetFloat(Alpha, 1);
        }

        static Mesh _quad;
        public static Mesh Quad()
        {
            if (_quad != null) return _quad;
            _quad = new Mesh { name = "ReturnQuad", hideFlags = HideFlags.HideAndDontSave };
            _quad.vertices = new[] { new Vector3(-.5f, -.5f), new Vector3(.5f, -.5f), new Vector3(-.5f, .5f), new Vector3(.5f, .5f) };
            _quad.uv = new[] { new Vector2(0, 0), new Vector2(1, 0), new Vector2(0, 1), new Vector2(1, 1) };
            _quad.triangles = new[] { 0, 2, 1, 2, 3, 1 };
            _quad.bounds = new Bounds(Vector3.zero, new Vector3(1, 1, 0.1f));
            return _quad;
        }

        /// <summary>Show a scene. Crossfades through mist unless instant.</summary>
        public void Set(SceneKey scene, bool instant = false)
        {
            Ensure();
            if (scene == _cur && _fade < 0) return;
            if (_cur == (SceneKey)(-1) || instant) { Apply(scene); return; }
            _next = scene; _fade = 0;
            _m.SetTexture(TexB, UIAssets.Sky(scene)); _m.SetTexture(DepthB, UIAssets.Depth(scene));
            var t = UIAssets.Sky(scene); _m.SetFloat(AspB, t ? (float)t.width / t.height : 1.777f);
        }

        void Apply(SceneKey s)
        {
            _cur = s; _fade = -1; _mix = 0;
            var t = UIAssets.Sky(s);
            _m.SetTexture(Main, t); _m.SetTexture(Depth, UIAssets.Depth(s));
            _m.SetFloat(AspA, t ? (float)t.width / t.height : 1.777f);
            _m.SetFloat(Mix, 0);
        }

        /// <summary>Complete any running crossfade and mist move immediately.</summary>
        public void Finish() { Ensure(); if (_fade >= 0) Apply(_next); _mist = _mistTarget; }

        /// <summary>0 = clear, 1 = full fog. Used while a room is building.</summary>
        public void SetMist(float m) { _mistTarget = Mathf.Clamp01(m); }
        public void SetFog(Color c) { Ensure(); _m.SetColor(Fog, c); }

        void LateUpdate() { Refresh(); }

        /// <summary>Advance fades and parallax. Runs every LateUpdate; call manually in edit mode.</summary>
        public void Refresh()
        {
            Ensure();
            if (_fade >= 0)
            {
                _fade += Application.isPlaying ? Time.unscaledDeltaTime / 1.1f : 1f;
                _mix = Mathf.Clamp01(_fade);
                _m.SetFloat(Mix, _mix);
                if (_fade >= 1f) Apply(_next);
            }
            _mist = Mathf.Lerp(_mist, _mistTarget, Application.isPlaying ? 1f - Mathf.Exp(-3f * Time.unscaledDeltaTime) : 1f);
            _m.SetFloat(Mist, _mist);
            var fog = ThemeManager.Current == ReturnTheme.Dusk ? new Color32(10, 15, 31, 255) : new Color32(237, 234, 228, 255);
            _m.SetColor(Fog, fog);

            if (_cam == null && Camera.main != null) _cam = Camera.main.transform;
            if (_cam != null && followCamera)
            {
                // Sit straight ahead of the viewer at their yaw so the window is always in front; parallax from head offset.
                var fwd = _cam.forward; fwd.y = 0; if (fwd.sqrMagnitude < 0.01f) fwd = Vector3.forward; fwd.Normalize();
                if (Application.isPlaying) { _yaw = Mathf.LerpAngle(_yaw, Mathf.Atan2(fwd.x, fwd.z) * Mathf.Rad2Deg, 1f - Mathf.Exp(-2f * Time.unscaledDeltaTime)); }
                else _yaw = Mathf.Atan2(fwd.x, fwd.z) * Mathf.Rad2Deg;
                var dir = Quaternion.Euler(0, _yaw, 0) * Vector3.forward;
                transform.position = new Vector3(_cam.position.x, _cam.position.y, _cam.position.z) + dir * distance;
                transform.rotation = Quaternion.LookRotation(dir);
                var local = Quaternion.Inverse(transform.rotation) * (_cam.position - transform.position);
                _m.SetVector(Pointer, new Vector4(Mathf.Clamp(-local.x * 0.25f, -0.5f, 0.5f), Mathf.Clamp(-local.y * 0.25f, -0.5f, 0.5f), 0, 0));
            }
        }
        float _yaw;

        void OnDestroy() { if (_m != null) DestroyImmediate(_m); }
    }
}
