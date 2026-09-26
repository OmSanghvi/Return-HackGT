using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// A soft blob shadow just above the ground under every prop that plausibly rests on it. Skips the floor/ground/sky
    /// itself and anything with a huge footprint (that's terrain, not a prop). One shared fan mesh with the falloff baked
    /// into vertex alpha and one shared material, so every shadow in a world is cheap and batches on Quest.
    /// </summary>
    public static class ContactShadow
    {
        /// <summary>Anything with a footprint bigger than this reads as ground/water, not a prop resting on it.</summary>
        const float MaxFootprintSqm = 40f;
        const float MaxRadius = 1.2f;
        const float Padding = 1.15f; // a little bigger than the prop's own footprint so the blob reads under it, not just at its center

        static Mesh _mesh;
        static Material _material;

        public static void Build(Transform root, Bounds worldBounds)
        {
            // snapshot first: the loop adds shadow objects under the same root, which a lazy walk would visit (and shadow) forever
            foreach (var r in System.Linq.Enumerable.ToList(WorldSceneRoot.PropRenderers(root)))
            {
                if (Skip(root, r)) continue;
                var b = r.bounds;
                float radius = Radius(b.size);
                if (radius <= 0f) continue;

                var go = new GameObject("ContactShadow");
                go.transform.SetParent(root, false);
                go.transform.position = new Vector3(b.center.x, b.min.y + 0.01f, b.center.z);
                go.transform.rotation = Quaternion.identity; // mesh is already flat in the XZ plane, y up
                go.transform.localScale = new Vector3(radius, 1f, radius);
                go.AddComponent<MeshFilter>().sharedMesh = BuildMesh();
                var mr = go.AddComponent<MeshRenderer>();
                mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                mr.receiveShadows = false;
                mr.sharedMaterial = SharedMaterial();
            }
        }

        /// <summary>Blob radius from a prop's world-space footprint. Pure so it can be unit tested without a scene.
        /// Capped: a contact shadow grounds where a prop meets the floor, so a tree or house gets a blob at its base, not its canopy.</summary>
        public static float Radius(Vector3 footprintSize) => Mathf.Min(Mathf.Max(footprintSize.x, footprintSize.z) * 0.5f * Padding, MaxRadius);

        static bool Skip(Transform worldRoot, Renderer r)
        {
            var size = r.bounds.size;
            if (size.x * size.z > MaxFootprintSqm) return true;
            for (var t = r.transform; t != null && t != worldRoot; t = t.parent)
            {
                var n = t.name.ToLowerInvariant();
                if (n.Contains("floor") || n.Contains("ground") || n.Contains("sky") || n.Contains("dome") || n.Contains("contactshadow")) return true;
            }
            return false;
        }

        /// <summary>Unit-radius fan: opaque-ish alpha at the center, transparent at the rim, baked into vertex color so
        /// the shader needs no texture lookup.</summary>
        static Mesh BuildMesh()
        {
            if (_mesh != null) return _mesh;
            const int seg = 16;
            var verts = new Vector3[seg + 1];
            var colors = new Color[seg + 1];
            var tris = new int[seg * 3];
            verts[0] = Vector3.zero; colors[0] = new Color(1f, 1f, 1f, 0.55f);
            for (var i = 0; i < seg; i++)
            {
                float a = i / (float)seg * Mathf.PI * 2f;
                verts[i + 1] = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a));
                colors[i + 1] = new Color(1f, 1f, 1f, 0f);
            }
            for (var i = 0; i < seg; i++)
            {
                int b = i + 1, c = (i + 1) % seg + 1;
                tris[i * 3] = 0; tris[i * 3 + 1] = b; tris[i * 3 + 2] = c;
            }
            _mesh = new Mesh { name = "ContactShadowBlob", hideFlags = HideFlags.HideAndDontSave, vertices = verts, colors = colors, triangles = tris };
            _mesh.RecalculateBounds();
            return _mesh;
        }

        static Material SharedMaterial()
        {
            if (_material != null) return _material;
            _material = WorldShaders.Create(WorldShaders.ContactShadow, "ContactShadow");
            if (_material.HasProperty("_Color")) _material.SetColor("_Color", new Color(0f, 0f, 0f, 0.35f));
            return _material;
        }
    }
}
