using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR;

/// <summary>
/// Applies a backend/scene_tools.py stage_immersive_reveal StagingPlan to an
/// already-built SketchScape experience: mood lighting, a connecting light-
/// path motif, an ordered per-object reveal, narration, and per-object
/// haptics (Build Plan step 6, Part B).
///
/// Per the immersive-reveal-staging skill's hard rule, this never draws a
/// floating UI text card or HUD panel for the theme/explanation -- the
/// narration text is spoken (or, failing that, raised as an event for an
/// external accessibility captioning system, never rendered here).
///
/// Configured at authoring time by SketchScapeOfflineExperienceBuilder
/// (edit mode, so only serialized fields are set -- no coroutines run until
/// the built scene actually plays).
/// </summary>
[DisallowMultipleComponent]
public sealed class ImmersiveStagingDirector : MonoBehaviour
{
    [Serializable]
    public class StagedObjectRef
    {
        public string objectId;
        public GameObject target;
    }

    [Tooltip("Raw JSON of the staging block extracted from compiled-scene.json's meta.staging (or null if the scene has none -- graceful degradation applies).")]
    [SerializeField] private string stagingPlanJson;
    [SerializeField] private List<StagedObjectRef> stagedObjects = new List<StagedObjectRef>();

    [Header("Optional overrides (auto-found under this GameObject if left empty)")]
    [SerializeField] private Light moodLight;
    [SerializeField] private Volume moodVolume;
    [SerializeField] private AudioSource narrationSource;

    [SerializeField] private float revealStaggerSeconds = 0.35f;
    [SerializeField] private float revealScaleDuration = 0.5f;

    /// <summary>Raised with the narration text when no audio clip is available for it.
    /// Never rendered by this class -- hook a captioning system to it if one exists.</summary>
    public event Action<string> NarrationCaptionAvailable;

    private readonly Dictionary<string, Vector3> finalScales = new Dictionary<string, Vector3>();

    /// <summary>Editor-time setup only: stores data, does not touch play-mode-only APIs.</summary>
    public void Configure(string json, List<StagedObjectRef> objects)
    {
        stagingPlanJson = json;
        stagedObjects = objects ?? new List<StagedObjectRef>();
    }

    private void Awake()
    {
        // Hide authored objects until their turn in the reveal order; capture
        // their authored scale first so ScaleIn has a target to animate to.
        foreach (var entry in stagedObjects)
        {
            if (entry?.target == null || string.IsNullOrEmpty(entry.objectId))
            {
                continue;
            }
            finalScales[entry.objectId] = entry.target.transform.localScale;
            entry.target.transform.localScale = Vector3.zero;
        }
    }

    private void Start()
    {
        if (!StagingPlanParser.TryParseFromComponentJson(stagingPlanJson, out var plan))
        {
            // Graceful degradation (skill requirement): no staging data, room
            // must still load correctly -- just show everything immediately.
            RevealAllImmediately();
            return;
        }

        ApplyMoodLighting(plan);
        BuildConnectingMotif(plan);
        PlayNarration(plan);
        StartCoroutine(RevealSequence(plan));
    }

    private void RevealAllImmediately()
    {
        foreach (var kv in finalScales)
        {
            var entry = FindStagedObject(kv.Key);
            if (entry?.target != null)
            {
                entry.target.transform.localScale = kv.Value;
            }
        }
    }

    private void ApplyMoodLighting(StagingPlan plan)
    {
        Color mood = plan.MotifColor;

        var light = moodLight != null ? moodLight : GetComponentInChildren<Light>();
        if (light != null)
        {
            light.color = mood;
            light.intensity = Mathf.Max(light.intensity, 1.1f);
        }

        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.ExponentialSquared;
        RenderSettings.fogColor = mood;
        RenderSettings.fogDensity = 0.02f;

        if (moodVolume != null && moodVolume.profile != null &&
            moodVolume.profile.TryGet(out ColorAdjustments colorAdjustments))
        {
            colorAdjustments.colorFilter.Override(Color.Lerp(Color.white, mood, 0.35f));
        }
        // ponytail: CristianQiu/Unity-URP-Volumetric-Light or the
        // URP-Volumetric-Fog package (immersive-reveal-staging skill, Part B
        // bullet 3) would give real volumetric shafts here; a Volume
        // ColorAdjustments tweak + RenderSettings.fog is the installed-only
        // substitute. Swap in when one of those packages is approved.
    }

    private void BuildConnectingMotif(StagingPlan plan)
    {
        if (plan.MotifControlPoints == null || plan.MotifControlPoints.Length < 2)
        {
            return;
        }

        var line = gameObject.AddComponent<LineRenderer>();
        line.useWorldSpace = true;
        line.widthMultiplier = 0.03f;
        line.numCapVertices = 4;
        line.material = CreateGlowMaterial(plan.MotifColor);
        line.startColor = plan.MotifColor;
        line.endColor = plan.MotifColor;

        Vector3[] points = plan.MotifCurve == "catmull_rom"
            ? SubdivideCatmullRom(plan.MotifControlPoints, 12)
            : plan.MotifControlPoints;
        line.positionCount = points.Length;
        line.SetPositions(points);
        // ponytail: Unity's VisualEffectGraph-Samples (skill Part B bullet 4)
        // would dress this curve with restrained ambient particles; a glowing
        // LineRenderer is the installed-only stand-in.
    }

    private void PlayNarration(StagingPlan plan)
    {
        if (string.IsNullOrWhiteSpace(plan.NarrationText))
        {
            return;
        }

        // Convention: a recorded/synthesized line lives at
        // Resources/Narration/<voice>.<ext>. None is packaged yet (Part A
        // only emits the text + a voice id, no audio asset), so this is the
        // hook for when one is added -- not a promise one exists today.
        AudioClip clip = Resources.Load<AudioClip>("Narration/" + plan.NarrationVoice);
        if (clip != null)
        {
            var source = narrationSource != null ? narrationSource : gameObject.AddComponent<AudioSource>();
            source.spatialBlend = 1f;
            source.clip = clip;
            source.Play();
            return;
        }

        // No clip: this is the *primary* explanation channel per the skill,
        // so raise it for an external captioning/accessibility system rather
        // than silently dropping it. Do NOT render a floating UI card here.
        NarrationCaptionAvailable?.Invoke(plan.NarrationText);
        Debug.Log("ImmersiveStagingDirector: no narration clip for voice '" + plan.NarrationVoice +
            "'. Narration text: " + plan.NarrationText);
        // ponytail: Meta MMS TTS (skill Part B bullet 5) would synthesize
        // this line on demand; a recorded-clip lookup + caption fallback is
        // the installed-only substitute until that's wired up.
    }

    private IEnumerator RevealSequence(StagingPlan plan)
    {
        foreach (string objectId in plan.RevealOrder)
        {
            var entry = FindStagedObject(objectId);
            if (entry?.target == null)
            {
                continue;
            }

            Vector3 finalScale = finalScales.TryGetValue(objectId, out var scale) ? scale : Vector3.one;
            yield return StartCoroutine(ScaleIn(entry.target.transform, finalScale));

            string signature = plan.HapticSignatures.TryGetValue(objectId, out var sig) ? sig : "pulse_soft";
            PulseHaptics(signature);

            yield return new WaitForSeconds(revealStaggerSeconds);
        }
    }

    private IEnumerator ScaleIn(Transform target, Vector3 finalScale)
    {
        float elapsed = 0f;
        while (elapsed < revealScaleDuration && target != null)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, elapsed / revealScaleDuration);
            target.localScale = Vector3.LerpUnclamped(Vector3.zero, finalScale, t);
            yield return null;
        }
        if (target != null)
        {
            target.localScale = finalScale;
        }
    }

    private StagedObjectRef FindStagedObject(string objectId)
    {
        foreach (var entry in stagedObjects)
        {
            if (entry != null && entry.objectId == objectId)
            {
                return entry;
            }
        }
        return null;
    }

    // amplitude, duration per signature id from _HAPTIC_PALETTE in
    // backend/scene_tools.py. Unmapped ids fall back to pulse_soft's feel.
    private static readonly Dictionary<string, (float amplitude, float duration)> HapticMap =
        new Dictionary<string, (float, float)>
        {
            { "pulse_soft", (0.3f, 0.15f) },
            { "pulse_sharp", (0.9f, 0.05f) },
            { "pulse_warm", (0.5f, 0.25f) },
            { "pulse_cool", (0.4f, 0.2f) },
            { "pulse_deep", (0.7f, 0.35f) },
        };

    private static void PulseHaptics(string signature)
    {
        var (amplitude, duration) = HapticMap.TryGetValue(signature, out var value) ? value : (0.5f, 0.15f);
        // Both hands: staging is an automatic choreography moment, not tied
        // to a specific held controller. ponytail: route to just the owning
        // contributor's controller if/when per-player identity is threaded
        // through here.
        PulseNode(XRNode.LeftHand, amplitude, duration);
        PulseNode(XRNode.RightHand, amplitude, duration);
    }

    private static void PulseNode(XRNode node, float amplitude, float duration)
    {
        var device = InputDevices.GetDeviceAtXRNode(node);
        if (device.isValid && device.TryGetHapticCapabilities(out var capabilities) && capabilities.supportsImpulse)
        {
            device.SendHapticImpulse(0u, amplitude, duration);
        }
    }

    private static Vector3[] SubdivideCatmullRom(Vector3[] control, int segmentsPerSpan)
    {
        if (control.Length < 2)
        {
            return control;
        }

        var result = new List<Vector3>();
        for (int i = 0; i < control.Length - 1; i++)
        {
            Vector3 p0 = control[Mathf.Max(i - 1, 0)];
            Vector3 p1 = control[i];
            Vector3 p2 = control[i + 1];
            Vector3 p3 = control[Mathf.Min(i + 2, control.Length - 1)];

            for (int s = 0; s < segmentsPerSpan; s++)
            {
                float t = s / (float)segmentsPerSpan;
                result.Add(CatmullRom(p0, p1, p2, p3, t));
            }
        }
        result.Add(control[control.Length - 1]);
        return result.ToArray();
    }

    private static Vector3 CatmullRom(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        float t2 = t * t;
        float t3 = t2 * t;
        return 0.5f * (
            2f * p1 +
            (-p0 + p2) * t +
            (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2 +
            (-p0 + 3f * p1 - 3f * p2 + p3) * t3);
    }

    private static Material CreateGlowMaterial(Color color)
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        var material = new Material(shader) { color = color };
        if (material.HasProperty("_EmissionColor"))
        {
            material.EnableKeyword("_EMISSION");
            material.SetColor("_EmissionColor", color * 2f);
        }
        return material;
    }
}
