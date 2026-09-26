using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The hub's sky: a star dome, the painted sky as a curved panorama behind the portals, and still water underfoot.
    /// Parallax comes from the viewer's head offset. Used for the hub and, with a different painting, for stub worlds
    /// (extras off there: no water/fireflies/motes/lanterns, just the plain fogged floor, so stub worlds stay cheap).
    /// </summary>
    public class HubEnvironment : MonoBehaviour
    {
        static readonly int Main = Shader.PropertyToID("_MainTex"), Depth = Shader.PropertyToID("_DepthTex"), AspA = Shader.PropertyToID("_AspA"), Size = Shader.PropertyToID("_Size"),
            Pointer = Shader.PropertyToID("_Pointer"), Fog = Shader.PropertyToID("_Fog"), Top = Shader.PropertyToID("_Top"), Bottom = Shader.PropertyToID("_Bottom"), Color_ = Shader.PropertyToID("_Color");

        Transform _head; Vector3 _headHome;
        Material _pano, _dome, _floor;
        bool _extras;

        /// <summary>Build under parent. arcDegrees is how wide the painting spans (behind the portal ring); the dome covers the rest.
        /// extras adds the still-water floor, fireflies, motes and lanterns, and toggles the hub ambience loop with this object's enabled state; leave false for stub worlds.</summary>
        public static HubEnvironment Build(Transform parent, Transform head, SceneKey scene, bool dusk, float arcDegrees = 150f, bool extras = false)
        {
            var go = new GameObject("Environment"); go.transform.SetParent(parent, false);
            var env = go.AddComponent<HubEnvironment>(); env._head = head; env._headHome = head != null ? head.position : new Vector3(0, 1.6f, 0); env._extras = extras;
            var pal = ReturnColors.Get(dusk ? ReturnTheme.Dusk : ReturnTheme.Day);

            // star dome
            var dome = GameObject.CreatePrimitive(PrimitiveType.Sphere); dome.name = "Dome"; Object.Destroy(dome.GetComponent<Collider>());
            dome.transform.SetParent(go.transform, false); dome.transform.localScale = Vector3.one * 60f;
            env._dome = ReturnShaders.Create(ReturnShaders.SkyGradient);
            env._dome.SetColor(Top, dusk ? Color.Lerp((Color)ReturnColorsDusk.Canvas, (Color)ReturnColorsDusk.SkyTop, 0.35f) : (Color)pal.SkyTop);
            env._dome.SetColor(Bottom, dusk ? Color.Lerp((Color)ReturnColorsDusk.SkyBottom, (Color)ReturnColorsDusk.Canvas, 0.45f) : (Color)pal.SkyBottom);
            env._dome.SetFloat("_Stars", dusk ? 1f : 0f);
            dome.GetComponent<MeshRenderer>().sharedMaterial = env._dome;

            // painted panorama, centered forward (+Z), 9 m out
            const float radius = 9f, height = 12.4f, y0 = -3.4f;
            var pano = new GameObject("Panorama"); pano.transform.SetParent(go.transform, false);
            pano.AddComponent<MeshFilter>().sharedMesh = CurvedMesh.Build(radius, arcDegrees, y0, y0 + height, 48);
            var pr = pano.AddComponent<MeshRenderer>(); pr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            var tex = UIAssets.Sky(scene);
            env._pano = ReturnShaders.Create(ReturnShaders.SkyParallax); env._pano.renderQueue = 2000;
            env._pano.SetTexture(Main, tex); env._pano.SetTexture(Depth, UIAssets.Depth(scene));
            float arc = 2f * Mathf.PI * radius * arcDegrees / 360f;
            env._pano.SetFloat("_Edge", 0.14f); env._pano.SetFloat(AspA, (float)tex.width / tex.height); env._pano.SetVector(Size, new Vector4(arc, height, 0, 0));
            env._pano.SetColor(Fog, dusk ? (Color)ReturnColorsDusk.Canvas : (Color)ReturnColorsDay.Canvas);
            pr.sharedMaterial = env._pano;

            if (extras)
            {
                // still water instead of the fogged disc: reflects the sky, ripples where controllers point or dip in
                WaterFloor.Create(go.transform);
                Fireflies.Create(go.transform);
                Motes.Create(go.transform);
                Lanterns.Create(go.transform);
            }
            else
            {
                // fogged floor: a soft disc that melts the panorama's bottom edge into the dome
                var floor = new GameObject("Floor"); floor.transform.SetParent(go.transform, false);
                floor.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
                floor.transform.localRotation = Quaternion.Euler(90, 0, 0); floor.transform.localPosition = new Vector3(0, -0.02f, 0); floor.transform.localScale = new Vector3(26, 26, 1);
                env._floor = ReturnShaders.Create(ReturnShaders.Flat);
                var fc = dusk ? (Color)ReturnColorsDusk.SkyBottom : (Color)pal.SkyBottom; fc.a = 0.35f;
                env._floor.SetColor(Color_, fc); env._floor.SetFloat("_Radial", 1);
                floor.AddComponent<MeshRenderer>().sharedMaterial = env._floor;
            }
            return env;
        }

        // hub ambience follows this object's active state, which HubController drives by toggling the hub root (HubVisible):
        // on for the real hub (extras true), left alone for stub worlds so their HubEnvironment doesn't fight the hub's own.
        void OnEnable() { if (_extras) ReturnAudio.Ambience(true, 2f); }
        void OnDisable() { if (_extras) ReturnAudio.Ambience(false, 1.2f); }

        void LateUpdate()
        {
            if (_head == null || _pano == null) return;
            var d = _head.position - _headHome;
            _pano.SetVector(Pointer, new Vector4(Mathf.Clamp(-d.x * 0.25f, -0.5f, 0.5f), Mathf.Clamp(-d.y * 0.25f, -0.5f, 0.5f), 0, 0));
        }

        void OnDestroy() { foreach (var m in new[] { _pano, _dome, _floor }) if (m != null) Destroy(m); }
    }

    public static class CurvedMesh
    {
        /// <summary>A vertical strip of a cylinder around the origin, viewed from inside, centered on +Z. UV 0..1 across the arc.</summary>
        public static Mesh Build(float radius, float arcDeg, float y0, float y1, int segments)
        {
            var v = new Vector3[(segments + 1) * 2]; var uv = new Vector2[v.Length]; var tri = new int[segments * 6];
            for (int i = 0; i <= segments; i++)
            {
                float u = i / (float)segments, a = Mathf.Lerp(-arcDeg / 2f, arcDeg / 2f, u) * Mathf.Deg2Rad;
                var p = new Vector3(Mathf.Sin(a) * radius, 0, Mathf.Cos(a) * radius);
                v[i * 2] = new Vector3(p.x, y0, p.z); v[i * 2 + 1] = new Vector3(p.x, y1, p.z);
                uv[i * 2] = new Vector2(1f - u, 0); uv[i * 2 + 1] = new Vector2(1f - u, 1); // +x is to the right when facing +z, so u runs opposite to a
            }
            for (int i = 0; i < segments; i++)
            {
                int b = i * 2, t = i * 6;
                tri[t] = b; tri[t + 1] = b + 1; tri[t + 2] = b + 2; tri[t + 3] = b + 1; tri[t + 4] = b + 3; tri[t + 5] = b + 2;
            }
            var m = new Mesh { name = "ReturnCurved", hideFlags = HideFlags.HideAndDontSave, vertices = v, uv = uv, triangles = tri };
            m.RecalculateBounds();
            return m;
        }
    }
}
