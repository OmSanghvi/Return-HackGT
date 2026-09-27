using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Photoreal trees around the hub, cheap enough for Quest: each is one camera-facing card (yaw only) textured with an
    /// impostor baked from a scanned Poly Haven tree (Tools > Return > Bake Tree Impostors, Editor/ReturnImpostorBaker.cs),
    /// so a 300k-triangle jacaranda costs two triangles. They stand between the portals and the HDRI's own treeline,
    /// deterministically scattered so a rebuild doesn't reshuffle the view. Backdrop only: no colliders, no shadows.
    /// ponytail: single-angle impostors; a tree you walk around shows the same face, fine past ~10 m. Bake 8 angles and
    /// pick by view direction if trees ever come closer.
    /// </summary>
    public static class DistantTrees
    {
        /// <summary>Impostor name under Resources/ReturnUI/Impostors and the scanned tree's real height in meters.</summary>
        static readonly (string name, float height)[] Species = { ("jacaranda", 9f), ("island-tree", 8f) };

        const int Count = 26;
        const float MinRadius = 11f, MaxRadius = 30f, ClearArcDeg = 115f, ClearRadius = 17f;

        public static void Create(Transform parent, int seed = 7)
        {
            var root = new GameObject("DistantTrees"); root.transform.SetParent(parent, false);
            var mats = new Material[Species.Length];
            for (int s = 0; s < Species.Length; s++)
            {
                var tex = Resources.Load<Texture2D>("ReturnUI/Impostors/" + Species[s].name);
                if (tex == null) { Debug.LogWarning("[Return] DistantTrees: missing impostor ReturnUI/Impostors/" + Species[s].name + ", run Tools > Return > Bake Tree Impostors."); continue; }
                mats[s] = WorldShaders.Create(WorldShaders.Photo, "Photo");
                mats[s].SetTexture("_MainTex", tex); mats[s].SetFloat("_Cutoff", 0.45f);
            }
            root.AddComponent<Owner>().mats = mats;

            var rng = new System.Random(seed);
            for (int i = 0; i < Count; i++)
            {
                int s = rng.Next(Species.Length);
                float angle = (float)(rng.NextDouble() * 360.0);
                float radius = MinRadius + (float)rng.NextDouble() * (MaxRadius - MinRadius);
                // keep the arc behind the portals clear up close so no tree crowds a doorway; farther out is fine
                if (Mathf.Abs(Mathf.DeltaAngle(0f, angle)) <= ClearArcDeg && radius < ClearRadius)
                    radius = ClearRadius + (float)rng.NextDouble() * (MaxRadius - ClearRadius);
                float scale = 0.8f + (float)rng.NextDouble() * 0.45f;
                if (mats[s] == null) continue;

                var tex = (Texture2D)mats[s].GetTexture("_MainTex");
                float h = Species[s].height * scale, w = h * tex.width / tex.height;
                float rad = angle * Mathf.Deg2Rad;
                var card = new GameObject("Tree"); card.transform.SetParent(root.transform, false);
                card.transform.localPosition = new Vector3(radius * Mathf.Sin(rad), h * 0.5f, radius * Mathf.Cos(rad));
                card.transform.localScale = new Vector3(rng.NextDouble() < 0.5 ? -w : w, h, 1f); // mirror half of them for variety
                card.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
                var r = card.AddComponent<MeshRenderer>(); r.sharedMaterial = mats[s];
                r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; r.receiveShadows = false;
            }
        }

        /// <summary>Turns every card toward the viewer (yaw only) once a frame, and frees the per-hub materials.</summary>
        class Owner : MonoBehaviour
        {
            public Material[] mats;
            void LateUpdate()
            {
                var cam = Camera.main; if (cam == null) return;
                var head = cam.transform.position;
                foreach (Transform t in transform)
                {
                    var d = t.position - head; d.y = 0;
                    if (d.sqrMagnitude > 0.01f) t.rotation = Quaternion.LookRotation(d);
                }
            }
            void OnDestroy() { if (mats != null) foreach (var m in mats) if (m != null) Destroy(m); }
        }
    }
}
