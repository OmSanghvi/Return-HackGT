using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// A scatter of Kenney nature-kit trees around the hub, past the meadow floor's edge, so the horizon reads as a
    /// treeline instead of empty grass. Loaded from Resources/ReturnUI/Props (copied from the world-scene prop library,
    /// see THIRD-PARTY.md), deterministically scattered so a rebuild doesn't reshuffle the view. No colliders, no shadow
    /// casting: these are backdrop, not props to interact with.
    /// </summary>
    public static class DistantTrees
    {
        static readonly string[] Names = { "tree_default", "tree_detailed", "tree_cone", "tree_fat", "tree_blocks" };
        static readonly Color Pink = new Color(1f, 0.72f, 0.82f);
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor"), ColorId = Shader.PropertyToID("_Color"), GltfColorId = Shader.PropertyToID("baseColorFactor");

        static GameObject[] _prefabs;
        static bool _loggedMissing;

        const int Count = 35, MinRadius = 12, MaxRadius = 32, ClearArcDeg = 100, ClearRadius = 18;

        public static void Create(Transform parent, int seed = 7)
        {
            EnsureLoaded();
            var root = new GameObject("DistantTrees"); root.transform.SetParent(parent, false);
            var rng = new System.Random(seed);
            var block = new MaterialPropertyBlock();

            for (int i = 0; i < Count; i++)
            {
                var prefab = PickPrefab(rng);
                if (prefab == null) continue;

                float angle = (float)(rng.NextDouble() * 360.0);
                float radius = MinRadius + (float)rng.NextDouble() * (MaxRadius - MinRadius);
                // keep the arc in front of the portals clear at close range; farther out in that same arc is fine
                if (Mathf.Abs(Mathf.DeltaAngle(0f, angle)) <= ClearArcDeg && radius < ClearRadius)
                    radius = ClearRadius + (float)rng.NextDouble() * (MaxRadius - ClearRadius);

                float rad = angle * Mathf.Deg2Rad;
                var inst = Object.Instantiate(prefab, root.transform);
                inst.transform.localPosition = new Vector3(radius * Mathf.Sin(rad), 0f, radius * Mathf.Cos(rad));
                inst.transform.localRotation = Quaternion.Euler(0f, (float)(rng.NextDouble() * 360.0), 0f);
                inst.transform.localScale = Vector3.one * (2.5f + (float)rng.NextDouble() * 2f);

                Strip(inst);
                if (rng.NextDouble() < 0.4) TintPink(inst, block);
            }
        }

        static void EnsureLoaded()
        {
            if (_prefabs != null) return;
            _prefabs = new GameObject[Names.Length];
            bool missing = false;
            for (int i = 0; i < Names.Length; i++)
            {
                _prefabs[i] = Resources.Load<GameObject>("ReturnUI/Props/" + Names[i]);
                if (_prefabs[i] == null) missing = true;
            }
            if (missing && !_loggedMissing)
            {
                Debug.LogWarning("[Return] DistantTrees: one or more tree prefabs missing under Resources/ReturnUI/Props.");
                _loggedMissing = true;
            }
        }

        static GameObject PickPrefab(System.Random rng)
        {
            // a few random draws instead of maintaining a separate compacted list; fine odds even with one missing name
            for (int tries = 0; tries < _prefabs.Length; tries++)
            {
                var p = _prefabs[rng.Next(_prefabs.Length)];
                if (p != null) return p;
            }
            return null;
        }

        static void Strip(GameObject inst)
        {
            foreach (var c in inst.GetComponentsInChildren<Collider>()) Object.Destroy(c);
            foreach (var r in inst.GetComponentsInChildren<Renderer>()) r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        }

        static void TintPink(GameObject inst, MaterialPropertyBlock block)
        {
            foreach (var r in inst.GetComponentsInChildren<Renderer>())
            {
                var mats = r.sharedMaterials;
                for (int i = 0; i < mats.Length; i++)
                {
                    if (!LooksFoliage(mats[i] != null ? mats[i].name : null, i)) continue;
                    block.Clear();
                    block.SetColor(BaseColorId, Pink);
                    block.SetColor(ColorId, Pink);
                    block.SetColor(GltfColorId, Pink); // glTFast's shader graph names it baseColorFactor
                    r.SetPropertyBlock(block, i);
                }
            }
        }

        /// <summary>True if a material's name reads as leaves, or (with no clearer signal) it isn't the trunk/wood
        /// material. Pure, so it's cheap to get right without a scene: nature-kit trees name theirs "leafsGreen" /
        /// "woodBark", but material order isn't consistent across the different tree meshes.</summary>
        static bool LooksFoliage(string name, int index)
        {
            if (!string.IsNullOrEmpty(name))
            {
                var n = name.ToLowerInvariant();
                if (n.Contains("leaf") || n.Contains("leaves") || n.Contains("green") || n.Contains("foliage")) return true;
                if (n.Contains("wood") || n.Contains("bark") || n.Contains("trunk")) return false;
            }
            return index > 0;
        }
    }
}
