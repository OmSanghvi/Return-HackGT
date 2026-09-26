using System;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The arched painted window for the VR hub: 0.9 x 1.2 m, floats on a ring, bobs 2 cm over 6 s. Pinch or click it to step in.
    /// Rig-agnostic: an XR interactor calls Enter(), or a mouse/PhysicsRaycaster click on the collider does.
    /// </summary>
    [RequireComponent(typeof(BoxCollider))]
    public class RoomPortal : MonoBehaviour, UnityEngine.EventSystems.IPointerClickHandler
    {
        static readonly int Main = Shader.PropertyToID("_MainTex"), Depth = Shader.PropertyToID("_DepthTex"), Asp = Shader.PropertyToID("_AspA"),
            Size = Shader.PropertyToID("_Size"), Arch = Shader.PropertyToID("_Arch"), Pointer = Shader.PropertyToID("_Pointer"), Fog = Shader.PropertyToID("_Fog"), Light = Shader.PropertyToID("_Light"),
            TouchUV = Shader.PropertyToID("_TouchUV"), TouchTime = Shader.PropertyToID("_TouchTime");

        public string roomId;
        /// <summary>Raised when the portal is pinched, poked, ray-clicked or mouse-clicked. The hub decides what that means for the room's state.</summary>
        public event Action<string> Activated;
        /// <summary>Raised for every new portal. XR glue subscribes to attach an interactable.</summary>
        public static event Action<RoomPortal> Created;
        /// <summary>Raised the first time any portal is hovered or touched. HubIntro uses this to dismiss the guided nudge for good.</summary>
        public static event Action AnyHoverOrTouch;
        public Collider Collider => GetComponent<Collider>();
        Material _m; Vector3 _base; float _phase; float _hover; float _lastTouchSfx = -10f;
        Transform _head; AudioSource _hum; float _humBoost;

        const float HeadLeanScale = 1.2f;   // local units are already divided by the portal's own size, so ~0.4 m of lean saturates the shift
        const float HeadWeight = 0.8f;      // mostly head-driven; a hand/mouse ray (desktop testing, no headset) nudges the rest
        const float BaseHumVolume = 0.05f;
        const float FacingBoost = 0.04f;    // small lift for the portal the head faces most directly
        const float DuckMultiplier = 0.15f; // hums nearly vanish while a room is being entered/occupied

        static bool _ducked;
        static int _facingFrame = -1;
        static RoomPortal _facingBest, _pendingFacingBest;
        static float _pendingFacingDot;

        /// <summary>Duck (or restore) every portal's hum at once. HubController calls this on EnteringRoom, and back on returning to the hub.</summary>
        public static void SetHumDucked(bool ducked) => _ducked = ducked;

        /// <summary>Maps a head (or pointer) position, already in the portal's local space, to the shader's -0.5..0.5 pointer range. Pure and testable.</summary>
        public static Vector2 HeadOffset(Vector3 localPosition, float leanScale) => new Vector2(
            Mathf.Clamp(-localPosition.x * leanScale, -0.5f, 0.5f),
            Mathf.Clamp(-localPosition.y * leanScale, -0.5f, 0.5f));

        /// <summary>1 when looking straight at the portal, 0 (or negative, clamped) facing away. Pure and testable.</summary>
        public static float FacingWeight(Vector3 headForward, Vector3 headToPortal) =>
            Mathf.Clamp01(Vector3.Dot(headForward.normalized, headToPortal.normalized));

        public static RoomPortal Create(Transform parent, Room room, Vector3 localPosition)
        {
            var go = new GameObject("Portal:" + room.title);
            go.transform.SetParent(parent, false); go.transform.localPosition = localPosition;
            go.transform.localScale = new Vector3(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 1);
            var p = go.AddComponent<RoomPortal>(); p.roomId = room.id;
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>();
            p._m = ReturnShaders.Create(ReturnShaders.SkyParallax);
            var sky = UIAssets.Sky(room.scene);
            p._m.SetTexture(Main, sky); p._m.SetTexture(Depth, UIAssets.Depth(room.scene)); p._m.SetFloat(Asp, (float)sky.width / sky.height);
            p._m.SetVector(Size, new Vector4(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 0, 0)); p._m.SetFloat(Arch, 1);
            r.sharedMaterial = p._m;
            var col = go.GetComponent<BoxCollider>(); col.size = new Vector3(1, 1, 0.1f);
            p._base = go.transform.localPosition; p._phase = UnityEngine.Random.value * 6f;
            p._hum = ReturnAudio.PortalHumSource(go.transform, room.scene, BaseHumVolume);
            Created?.Invoke(p);
            return p;
        }

        void Update()
        {
            float y = Mathf.Sin((Time.time + _phase) * Mathf.PI * 2f / 6f) * ReturnSpatial.PortalBob;
            transform.localPosition = _base + Vector3.up * y;
            _hover = Mathf.Lerp(_hover, 0, 1f - Mathf.Exp(-4f * Time.deltaTime));
            _m.SetFloat(Light, _hover * 0.5f);
            var fog = ThemeManager.Current == ReturnTheme.Dusk ? new Color32(10, 15, 31, 255) : new Color32(237, 234, 228, 255);
            _m.SetColor(Fog, fog);
            UpdateParallax();
            UpdateHum();
        }

        /// <summary>Head-driven 6DoF parallax: lean in to see behind the near sky layers. One Vector4 set per portal per frame.</summary>
        void UpdateParallax()
        {
            if (_head == null && Camera.main != null) _head = Camera.main.transform;
            if (_head == null) return;
            var headOffset = HeadOffset(transform.InverseTransformPoint(_head.position), HeadLeanScale);
            var pointerOffset = headOffset;
            if (HubPointers.Points.Count > 0)
            {
                var p = HubPointers.Points[0]; // only the first live pointer; portals do not need to average several
                var aim = transform.InverseTransformPoint(p.tip + p.forward * Vector3.Distance(p.tip, transform.position));
                pointerOffset = HeadOffset(aim, HeadLeanScale);
            }
            var blended = Vector2.Lerp(pointerOffset, headOffset, HeadWeight);
            _m.SetVector(Pointer, new Vector4(blended.x, blended.y, 0, 0));
        }

        /// <summary>Ducks with EnteringRoom, boosts a touch when the head faces this portal most directly, restores on return.</summary>
        void UpdateHum()
        {
            if (_hum == null || _head == null) return;
            if (_facingFrame != Time.frameCount)
            {
                _facingFrame = Time.frameCount; _facingBest = _pendingFacingBest;
                _pendingFacingBest = null; _pendingFacingDot = -2f;
            }
            float dot = FacingWeight(_head.forward, transform.position - _head.position);
            if (dot > _pendingFacingDot) { _pendingFacingDot = dot; _pendingFacingBest = this; }

            _humBoost = Mathf.Lerp(_humBoost, _facingBest == this ? FacingBoost : 0f, 1f - Mathf.Exp(-2f * Time.deltaTime));
            float target = (BaseHumVolume + _humBoost) * (_ducked ? DuckMultiplier : 1f) * ReturnAudio.MasterVolume;
            _hum.volume = Mathf.Lerp(_hum.volume, target, 1f - Mathf.Exp(-3f * Time.deltaTime));
        }

        /// <summary>Call while a ray or hand hovers to brighten the window.</summary>
        public void Hover() { _hover = 1f; AnyHoverOrTouch?.Invoke(); }

        /// <summary>Call with a world-space hit point (ray, poke or pinch) to brighten the window and ripple the sky from that point.</summary>
        public void Touch(Vector3 worldPoint)
        {
            _hover = 1f;
            var local = transform.InverseTransformPoint(worldPoint);
            _m.SetVector(TouchUV, new Vector4(local.x + 0.5f, local.y + 0.5f, 0, 0));
            _m.SetFloat(TouchTime, Time.time);
            AnyHoverOrTouch?.Invoke();
            if (Time.time - _lastTouchSfx > 0.15f) { _lastTouchSfx = Time.time; ReturnAudio.PlayAt(ReturnAudio.UiHover, transform.position, 0.18f); }
        }

        public void Activate() { Activated?.Invoke(roomId); }
        public void OnPointerClick(UnityEngine.EventSystems.PointerEventData e) { Activate(); }

        static readonly int MistId = Shader.PropertyToID("_Mist"), AlphaId = Shader.PropertyToID("_Alpha");
        /// <summary>How the window reads: mist 0 clear to 1 fogged, alpha 1 solid to 0 gone.</summary>
        public void SetPresentation(float mist, float alpha) { _m.SetFloat(MistId, mist); _m.SetFloat(AlphaId, alpha); }
        void OnDestroy() { if (_m != null) Destroy(_m); }
    }
}
