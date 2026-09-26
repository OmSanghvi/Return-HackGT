using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Replaces HubEnvironment's fogged floor disc with still water that fakes a reflection of the dusk sky
    /// (Return/WaterFloor: fresnel, procedural glints, sin-wave wobble, no reflection camera or grab pass), plus a
    /// ring buffer of up to 8 expanding ripples. Ripples spawn where a pointer (see HubPointers) points at the
    /// floor with select held, or dips low, or spontaneously every few seconds.
    /// </summary>
    public class WaterFloor : MonoBehaviour
    {
        const int RippleCount = 8;
        const float Radius = 26f, ActiveRadius = 10f, TipHeight = 0.15f, PointThrottle = 0.4f, TipThrottle = 0.25f;

        static readonly int RipplesId = Shader.PropertyToID("_Ripples");

        Material _mat;
        readonly Vector4[] _ripples = new Vector4[RippleCount];
        int _cursor;
        float _nextSpontaneous;
        float[] _nextPointThrow, _nextTipThrow;

        public static WaterFloor Create(Transform parent)
        {
            var go = new GameObject("Floor"); go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            go.transform.localRotation = Quaternion.Euler(90, 0, 0); go.transform.localPosition = new Vector3(0, -0.02f, 0); go.transform.localScale = new Vector3(Radius, Radius, 1);
            var wf = go.AddComponent<WaterFloor>();
            wf._mat = new Material(Shader.Find("Return/WaterFloor")) { hideFlags = HideFlags.HideAndDontSave };
            wf._mat.SetColor("_Color", new Color(0.02f, 0.03f, 0.08f, 0.88f));
            wf._mat.SetColor("_Top", (Color)ReturnColorsDusk.SkyTop);
            wf._mat.SetColor("_Bottom", (Color)ReturnColorsDusk.SkyBottom);
            wf._mat.SetFloat("_Radial", 1);
            go.AddComponent<MeshRenderer>().sharedMaterial = wf._mat;
            for (int i = 0; i < RippleCount; i++) wf._ripples[i] = new Vector4(0, 0, 0, -100f); // start far in the past so they read as inactive
            wf._nextSpontaneous = Time.time + Random.Range(4f, 9f);
            return wf;
        }

        void Update()
        {
            var pts = HubPointers.Points;
            if (_nextPointThrow == null || _nextPointThrow.Length < pts.Count) { _nextPointThrow = new float[Mathf.Max(4, pts.Count)]; _nextTipThrow = new float[_nextPointThrow.Length]; }

            float floorY = transform.position.y;
            for (int i = 0; i < pts.Count; i++)
            {
                var p = pts[i];
                if (p.select)
                {
                    var hit = HubPointers.FloorHit(p, floorY);
                    if (hit.HasValue && Vector2.Distance(new Vector2(hit.Value.x, hit.Value.z), new Vector2(transform.position.x, transform.position.z)) < ActiveRadius && Time.time >= _nextPointThrow[i])
                    { Spawn(hit.Value); _nextPointThrow[i] = Time.time + PointThrottle; }
                }
                float tipAbove = p.tip.y - floorY;
                if (tipAbove < TipHeight && tipAbove > -0.3f && Time.time >= _nextTipThrow[i])
                { Spawn(new Vector3(p.tip.x, floorY, p.tip.z)); _nextTipThrow[i] = Time.time + TipThrottle; }
            }

            if (Time.time >= _nextSpontaneous)
            {
                var c = transform.position; var r = Random.insideUnitCircle * ActiveRadius;
                Spawn(new Vector3(c.x + r.x, floorY, c.z + r.y), quiet: true);
                _nextSpontaneous = Time.time + Random.Range(4f, 9f);
            }
        }

        void Spawn(Vector3 worldPos, bool quiet = false)
        {
            _ripples[_cursor] = new Vector4(worldPos.x, worldPos.z, 0, Time.time);
            _cursor = (_cursor + 1) % RippleCount;
            _mat.SetVectorArray(RipplesId, _ripples);
            if (!quiet) ReturnAudio.PlayAt(ReturnAudio.Ripple, worldPos, 0.25f);
            else if (Random.value < 0.5f) ReturnAudio.PlayAt(ReturnAudio.Ripple, worldPos, 0.12f); // spontaneous ripples are quieter and not every time
        }

        void OnDestroy() { if (_mat != null) Destroy(_mat); }
    }
}
