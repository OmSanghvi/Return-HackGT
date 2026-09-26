using System.Collections.Generic;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Small signs of life in an otherwise static placeholder world: a sparse column of dust motes drifting along the
    /// main light's direction, gentle Perlin sway on foliage/cloth-shaped props, and a slow flicker on candle/lamp/fire
    /// shaped ones. All keyed off the GameObject name ReturnWorldScenes gives a placed prop (its id or layout "name").
    /// </summary>
    public static class WorldLife
    {
        static readonly string[] FoliageWords = { "tree", "bush", "plant", "grass", "leaf", "flower", "curtain", "flag", "banner", "cloth", "tent" };
        static readonly string[] FlickerWords = { "candle", "lamp", "lantern", "fire", "torch", "campfire" };

        /// <summary>True if a prop's name suggests foliage or cloth that should sway. Pure, unit tested without a scene.</summary>
        public static bool IsFoliageName(string name) => MatchesAny(name, FoliageWords);
        /// <summary>True if a prop's name suggests a candle/lamp/fire that should flicker. Pure, unit tested without a scene.</summary>
        public static bool IsFlickerName(string name) => MatchesAny(name, FlickerWords);

        static bool MatchesAny(string name, string[] words)
        {
            if (string.IsNullOrEmpty(name)) return false;
            var n = name.ToLowerInvariant();
            foreach (var w in words) if (n.Contains(w)) return true;
            return false;
        }

        public static void Build(Transform root, Bounds bounds)
        {
            DustColumn(root, bounds);

            var seen = new HashSet<Transform>();
            var phase = 0;
            foreach (var r in WorldSceneRoot.PropRenderers(root))
            {
                var prop = PropRootOf(r.transform, root);
                if (!seen.Add(prop)) continue; // one sway/flicker per placed prop, not per sub-mesh renderer
                if (IsFoliageName(prop.name)) prop.gameObject.AddComponent<Sway>().Init(phase++);
                if (IsFlickerName(prop.name)) prop.gameObject.AddComponent<Flicker>().Init(prop, phase++);
            }
        }

        /// <summary>Walks up from a renderer to the placed prop directly under the world root (ReturnWorldScenes parents
        /// every placement straight to the root, so this is at most one hop for a model's own child renderers).</summary>
        static Transform PropRootOf(Transform t, Transform root)
        {
            while (t.parent != null && t.parent != root) t = t.parent;
            return t;
        }

        static void DustColumn(Transform root, Bounds bounds)
        {
            var dir = MainLightDirection();
            var go = new GameObject("DustColumn");
            go.transform.SetParent(root, false);
            go.transform.position = bounds.center + Vector3.up * (bounds.extents.y * 0.6f);
            go.transform.rotation = Quaternion.LookRotation(dir);

            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.playOnAwake = true; main.maxParticles = 40;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.startLifetime = 10f; main.startSpeed = 0f; main.startSize = 0.02f;
            main.startColor = new Color(1f, 0.95f, 0.85f, 0.35f);
            main.gravityModifier = 0f;

            var emission = ps.emission; emission.rateOverTime = 3f; // sparse

            var shape = ps.shape;
            shape.shapeType = ParticleSystemShapeType.Circle;
            shape.radius = Mathf.Clamp(Mathf.Min(bounds.extents.x, bounds.extents.z), 0.5f, 2f);

            // drift slowly along the light's direction, with a little jitter so the column doesn't look like a straight line
            var vel = ps.velocityOverLifetime; vel.enabled = true; vel.space = ParticleSystemSimulationSpace.World;
            const float speed = 0.1f, jitter = 0.04f;
            var v = dir.normalized * speed;
            vel.x = new ParticleSystem.MinMaxCurve(v.x - jitter, v.x + jitter);
            vel.y = new ParticleSystem.MinMaxCurve(v.y - jitter, v.y + jitter);
            vel.z = new ParticleSystem.MinMaxCurve(v.z - jitter, v.z + jitter);

            var noise = ps.noise; noise.enabled = true; noise.strength = 0.06f; noise.frequency = 0.12f;

            var r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Billboard;
            r.sharedMaterial = Shapes.ParticleMaterial(additive: false);
            ps.Play();
        }

        static Vector3 MainLightDirection()
        {
            var sun = RenderSettings.sun;
            if (sun != null) return sun.transform.forward;
            foreach (var l in Object.FindObjectsOfType<Light>())
                if (l.type == LightType.Directional) return l.transform.forward;
            return new Vector3(0.3f, -1f, 0.2f).normalized; // no directional light yet: a gentle downward drift
        }

        /// <summary>Small Perlin rotation wobble, per-instance phase so a row of trees doesn't sway in lockstep.</summary>
        class Sway : MonoBehaviour
        {
            const float AmplitudeDeg = 3f, Speed = 0.35f;
            Quaternion _base; float _phase;

            public void Init(int seed) { _base = transform.localRotation; _phase = seed * 1.7f; }

            void Update()
            {
                float t = Time.time * Speed + _phase;
                float x = (Mathf.PerlinNoise(t, 0f) - 0.5f) * 2f * AmplitudeDeg;
                float z = (Mathf.PerlinNoise(0f, t) - 0.5f) * 2f * AmplitudeDeg;
                transform.localRotation = _base * Quaternion.Euler(x, 0f, z);
            }
        }

        /// <summary>Slow intensity + slight warm/cool color flicker on a Light and/or an emissive renderer under the prop.</summary>
        class Flicker : MonoBehaviour
        {
            static readonly int EmissionColor = Shader.PropertyToID("_EmissionColor");
            static readonly Color WarmTint = new Color(1f, 0.72f, 0.4f);

            Light _light; float _baseIntensity; Color _baseLightColor;
            Renderer _renderer; MaterialPropertyBlock _block; Color _baseEmission; bool _hasEmission;
            float _phase;

            public void Init(Transform prop, int seed)
            {
                _phase = seed * 2.3f;
                _light = prop.GetComponentInChildren<Light>();
                if (_light != null) { _baseIntensity = _light.intensity; _baseLightColor = _light.color; }

                _renderer = prop.GetComponentInChildren<Renderer>();
                var mat = _renderer != null ? _renderer.sharedMaterial : null;
                if (mat != null && mat.HasProperty(EmissionColor))
                {
                    _hasEmission = true;
                    _baseEmission = mat.GetColor(EmissionColor);
                    _block = new MaterialPropertyBlock();
                }
            }

            void Update()
            {
                float n = Mathf.PerlinNoise(Time.time * 2.2f + _phase, 0f);
                float k = 0.75f + n * 0.4f; // gentle flicker, never fully dark

                if (_light != null)
                {
                    _light.intensity = _baseIntensity * k;
                    _light.color = Color.Lerp(_baseLightColor, WarmTint, Mathf.Abs(n - 0.5f));
                }
                if (_hasEmission)
                {
                    _renderer.GetPropertyBlock(_block);
                    _block.SetColor(EmissionColor, _baseEmission * k);
                    _renderer.SetPropertyBlock(_block);
                }
            }
        }
    }
}
