using System.Collections.Generic;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// A cheap ring of rolling hills beyond a floor's own radius, so there's always land under the horizon instead of a
    /// gap that shows the drop-off. One procedural annulus mesh (angular x radial grid), height layered from two Perlin
    /// frequencies sampled around the ring, rising from 0 at the inner edge to a peak partway across and staying up to
    /// the outer edge so nothing beyond it dips below the skyline. No collider, no shadow casting, one mesh + material.
    /// </summary>
    public static class HillsRing
    {
        const int AngularSegments = 96, RadialSegments = 6;

        /// <summary>Builds the ring as a child of parent, at parent's local origin/height. color is blended into the
        /// mesh's single material; seed picks the noise offsets so different callers (hub vs. each world) don't repeat
        /// the same silhouette.</summary>
        public static GameObject Build(Transform parent, float innerRadius, float outerRadius, float maxHeight, Color color, int seed)
        {
            var go = new GameObject("HillsRing");
            go.transform.SetParent(parent, false);
            var mesh = BuildMesh(innerRadius, outerRadius, maxHeight, seed);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mat = LitMaterial(color);
            var mr = go.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;
            mr.sharedMaterial = mat;
            var cleanup = go.AddComponent<Cleanup>(); cleanup.mesh = mesh; cleanup.mat = mat;
            return go;
        }

        static Mesh BuildMesh(float innerRadius, float outerRadius, float maxHeight, int seed)
        {
            var rng = new System.Random(seed);
            float offA = (float)rng.NextDouble() * 100f, offB = (float)rng.NextDouble() * 100f;
            int rings = RadialSegments + 1;
            var verts = new Vector3[rings * AngularSegments];
            var uvs = new Vector2[verts.Length];
            for (int ri = 0; ri < rings; ri++)
            {
                float t = ri / (float)RadialSegments; // 0 at inner edge, 1 at outer edge
                float radius = Mathf.Lerp(innerRadius, outerRadius, t);
                float rise = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(t / 0.4f)); // up by ~40% across the ring, stays up the rest of the way
                for (int ai = 0; ai < AngularSegments; ai++)
                {
                    float rad = ai / (float)AngularSegments * Mathf.PI * 2f;
                    float n = Mathf.PerlinNoise(offA + Mathf.Cos(rad) * 1.5f + 10f, offA + Mathf.Sin(rad) * 1.5f + 10f) * 0.65f
                            + Mathf.PerlinNoise(offB + Mathf.Cos(rad) * 4f + 20f, offB + Mathf.Sin(rad) * 4f + 20f) * 0.35f;
                    float height = n * maxHeight * rise;
                    int idx = ri * AngularSegments + ai;
                    verts[idx] = new Vector3(radius * Mathf.Sin(rad), height, radius * Mathf.Cos(rad));
                    uvs[idx] = new Vector2(ai / (float)AngularSegments, t);
                }
            }
            var tris = new List<int>((rings - 1) * AngularSegments * 6);
            for (int ri = 0; ri < rings - 1; ri++)
                for (int ai = 0; ai < AngularSegments; ai++)
                {
                    int a = ri * AngularSegments + ai, b = ri * AngularSegments + (ai + 1) % AngularSegments;
                    int c = (ri + 1) * AngularSegments + ai, d = (ri + 1) * AngularSegments + (ai + 1) % AngularSegments;
                    tris.Add(a); tris.Add(c); tris.Add(b);
                    tris.Add(b); tris.Add(c); tris.Add(d);
                }
            var mesh = new Mesh { name = "HillsRing", hideFlags = HideFlags.HideAndDontSave };
            mesh.vertices = verts;
            mesh.uv = uvs;
            mesh.triangles = tris.ToArray();
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        /// <summary>URP Lit so fog and the sun shade the hills naturally; Shader.Find can come back null in a device build
        /// that never referenced the shader elsewhere, so this falls back to the package's own Flat (already in the build
        /// via its template material) rather than throwing.</summary>
        public static Material LitMaterial(Color color)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Universal Render Pipeline/Simple Lit");
            if (shader != null)
            {
                var mat = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
                if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
                if (mat.HasProperty("_Smoothness")) mat.SetFloat("_Smoothness", 0.08f);
                if (mat.HasProperty("_Cull")) mat.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Off); // winding isn't worth chasing for a distant hill silhouette
                return mat;
            }
            var flat = ReturnShaders.Create(ReturnShaders.Flat);
            flat.SetColor("_Color", color);
            return flat;
        }

        /// <summary>Frees this instance's own mesh/material (the URP Lit/Flat material is per-call, not shared, since
        /// callers pass their own color) when the ring is destroyed with its world or the hub.</summary>
        class Cleanup : MonoBehaviour
        {
            public Mesh mesh; public Material mat;
            void OnDestroy() { if (mesh != null) Object.Destroy(mesh); if (mat != null) Object.Destroy(mat); }
        }
    }
}
