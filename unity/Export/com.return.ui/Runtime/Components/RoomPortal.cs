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
            Size = Shader.PropertyToID("_Size"), Arch = Shader.PropertyToID("_Arch"), Pointer = Shader.PropertyToID("_Pointer"), Fog = Shader.PropertyToID("_Fog"), Light = Shader.PropertyToID("_Light");

        public string roomId;
        /// <summary>Raised when the portal is pinched, poked, ray-clicked or mouse-clicked. The hub decides what that means for the room's state.</summary>
        public event Action<string> Activated;
        /// <summary>Raised for every new portal. XR glue subscribes to attach an interactable.</summary>
        public static event Action<RoomPortal> Created;
        public Collider Collider => GetComponent<Collider>();
        Material _m; Vector3 _base; float _phase; float _hover;

        public static RoomPortal Create(Transform parent, Room room, Vector3 localPosition)
        {
            var go = new GameObject("Portal:" + room.title);
            go.transform.SetParent(parent, false); go.transform.localPosition = localPosition;
            go.transform.localScale = new Vector3(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 1);
            var p = go.AddComponent<RoomPortal>(); p.roomId = room.id;
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>();
            p._m = new Material(Shader.Find("Return/SkyParallax")) { hideFlags = HideFlags.HideAndDontSave };
            var sky = UIAssets.Sky(room.scene);
            p._m.SetTexture(Main, sky); p._m.SetTexture(Depth, UIAssets.Depth(room.scene)); p._m.SetFloat(Asp, (float)sky.width / sky.height);
            p._m.SetVector(Size, new Vector4(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 0, 0)); p._m.SetFloat(Arch, 1);
            r.sharedMaterial = p._m;
            var col = go.GetComponent<BoxCollider>(); col.size = new Vector3(1, 1, 0.1f);
            p._base = go.transform.localPosition; p._phase = UnityEngine.Random.value * 6f;
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
        }

        /// <summary>Call while a ray or hand hovers to brighten the window.</summary>
        public void Hover() { _hover = 1f; }
        public void Activate() { Activated?.Invoke(roomId); }
        public void OnPointerClick(UnityEngine.EventSystems.PointerEventData e) { Activate(); }

        static readonly int MistId = Shader.PropertyToID("_Mist"), AlphaId = Shader.PropertyToID("_Alpha");
        /// <summary>How the window reads: mist 0 clear to 1 fogged, alpha 1 solid to 0 gone.</summary>
        public void SetPresentation(float mist, float alpha) { _m.SetFloat(MistId, mist); _m.SetFloat(AlphaId, alpha); }
        void OnDestroy() { if (_m != null) Destroy(_m); }
    }
}
