using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// A small floating light-orb guide companion (not a humanoid, per the
/// skill's "light path" motif language). State machine: Idle -> Thinking ->
/// Moving -> Speaking -> Idle. No text on screen anywhere in this class --
/// everything is voice, light, and motion (AGENT.md: felt, not read).
/// </summary>
[RequireComponent(typeof(SketchScapeGuideClient))]
[RequireComponent(typeof(SketchScapeGuideObjectMap))]
[RequireComponent(typeof(SketchScapeGuideHighlighter))]
public sealed class SketchScapeGuideBot : MonoBehaviour
{
    public enum State { Idle, Thinking, Moving, Speaking }

    [Header("Motion")]
    [SerializeField] private float maxMoveSpeed = 1.2f;
    [SerializeField] private float minHeight = 1.2f;
    [SerializeField] private float arrivalTolerance = 0.05f;

    [Header("Reveal / audio")]
    [SerializeField] private float revealScaleDuration = 0.6f;
    [SerializeField] private float thinkingPulseHz = 0.8f;
    [SerializeField] private AudioClip chimeClip;
    [SerializeField] private AudioClip thinkingHumClip;

    public State CurrentState { get; private set; } = State.Idle;
    public bool Busy => CurrentState != State.Idle || turnInFlight;
    public SketchScapeGuideObjectMap ObjectMap { get; private set; }
    public string CurrentStepId { get; private set; } = "";
    public Dictionary<string, GuideTourStepView> StepsById { get; } = new Dictionary<string, GuideTourStepView>();

    private SketchScapeGuideClient client;
    private SketchScapeGuideHighlighter highlighter;
    private AudioSource audioSource;
    private Light haloLight;
    private ParticleSystem halo;
    private string projectId;
    private readonly HashSet<string> revealedElementIds = new HashSet<string>();
    private bool turnInFlight;
    private Coroutine thinkingRoutine;
    private float haloBaseIntensity;

    /// <summary>Builds a 12 cm emissive-sphere bot under `parent`, with its
    /// particle halo, spatial AudioSource, and point light, and every Guide/
    /// component it needs. Procedural (not a hand-authored prefab) so
    /// SketchScapeOfflineExperienceBuilder can create it at edit time the
    /// same way it already creates every other authored GameObject --
    /// see CreateKeepsakePlaceholder for the precedent.</summary>
    public static SketchScapeGuideBot Spawn(Transform parent)
    {
        var root = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        root.name = "GuideBot";
        root.transform.SetParent(parent, false);
        root.transform.localScale = Vector3.one * 0.12f;
        SketchCard.DestroyCollider(root); // Edit-mode/play-mode-safe (this factory also runs at Editor build time).
        var boxCollider = root.AddComponent<BoxCollider>();
        boxCollider.size = Vector3.one * 1.4f; // Larger than the mesh: an easy grip target for "more".

        Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        var material = new Material(shader) { color = new Color(0.65f, 0.85f, 1f) };
        material.EnableKeyword("_EMISSION");
        if (material.HasProperty("_EmissionColor"))
        {
            material.SetColor("_EmissionColor", new Color(0.65f, 0.85f, 1f) * 2f);
        }
        root.GetComponent<Renderer>().sharedMaterial = material;

        var lightObject = new GameObject("Halo Light");
        lightObject.transform.SetParent(root.transform, false);
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Point;
        light.color = new Color(0.65f, 0.85f, 1f);
        light.range = 3f;
        light.intensity = 1.2f;

        var particleObject = new GameObject("Halo Particles");
        particleObject.transform.SetParent(root.transform, false);
        var particles = particleObject.AddComponent<ParticleSystem>();
        var main = particles.main;
        main.startLifetime = 1.2f;
        main.startSpeed = 0.05f;
        main.startSize = 0.02f;
        main.startColor = new Color(0.75f, 0.9f, 1f, 0.6f);
        main.maxParticles = 40;
        var emission = particles.emission;
        emission.rateOverTime = 12f;
        var shape = particles.shape;
        shape.shapeType = ParticleSystemShapeType.Sphere;
        shape.radius = 0.08f;
        var particleRenderer = particleObject.GetComponent<ParticleSystemRenderer>();
        particleRenderer.material = new Material(Shader.Find("Particles/Standard Unlit") ?? shader);

        var audioSource = root.AddComponent<AudioSource>();
        audioSource.spatialBlend = 1f;
        audioSource.minDistance = 0.5f;
        audioSource.maxDistance = 8f;
        audioSource.playOnAwake = false;
        audioSource.loop = false;

        root.AddComponent<SketchScapeGuideClient>();
        root.AddComponent<SketchScapeGuideObjectMap>();
        root.AddComponent<SketchScapeGuideHighlighter>();
        return root.AddComponent<SketchScapeGuideBot>();
    }

    private void Awake()
    {
        client = GetComponent<SketchScapeGuideClient>();
        ObjectMap = GetComponent<SketchScapeGuideObjectMap>();
        highlighter = GetComponent<SketchScapeGuideHighlighter>();
        audioSource = GetComponent<AudioSource>();
        haloLight = GetComponentInChildren<Light>();
        halo = GetComponentInChildren<ParticleSystem>();
        haloBaseIntensity = haloLight != null ? haloLight.intensity : 1.2f;
    }

    private void Start()
    {
        var owner = GetComponentInParent<BuiltExperienceController>();
        projectId = owner != null ? owner.ProjectId : "";
        if (string.IsNullOrEmpty(projectId))
        {
            Debug.LogWarning("SketchScapeGuideBot: no BuiltExperienceController project id found; disabling.");
            gameObject.SetActive(false);
            return;
        }
        StartCoroutine(Bootstrap());
    }

    private IEnumerator Bootstrap()
    {
        GuideTourResponse tour = null;
        bool failed = false;
        yield return client.GetTour(projectId, t => tour = t, err =>
        {
            failed = true;
            Debug.Log("SketchScapeGuideBot: guide tour unavailable (" + err + "); room continues with no bot.");
        });

        // Graceful degradation (skill rule): no tour, or an unreachable
        // backend, means the room loads and works exactly as before.
        if (failed || tour == null || !tour.tour_available)
        {
            gameObject.SetActive(false);
            yield break;
        }

        StepsById.Clear();
        foreach (var step in tour.steps)
        {
            StepsById[step.step_id] = step;
        }
        ObjectMap.ResolveTour(tour);

        foreach (var element in tour.elements)
        {
            if (!element.initially_visible && ObjectMap.TryGet(element.element_id, out var go))
            {
                go.SetActive(false);
            }
        }

        turnInFlight = true;
        StartThinkingPulse();
        GuideSessionResponse session = null;
        yield return client.StartSession(projectId, s => session = s, err =>
            Debug.LogWarning("SketchScapeGuideBot: could not start guide session -- " + err));
        StopThinkingPulse();
        turnInFlight = false;

        if (session != null)
        {
            yield return Execute(session.turn);
        }
        else
        {
            gameObject.SetActive(false);
        }
    }

    /// <summary>Sends a visitor event (next/repeat/ask_about/more/linger/question).
    /// Input ignores everything while Busy, but this guards it too.</summary>
    public void SendEvent(string type, string elementId = "", string text = "")
    {
        if (Busy)
        {
            return;
        }
        StartCoroutine(SendEventRoutine(new GuideEvent(type, elementId, text)));
    }

    private IEnumerator SendEventRoutine(GuideEvent evt)
    {
        turnInFlight = true;
        StartThinkingPulse();
        GuideTurnResponse turn = null;
        yield return client.SendTurn(projectId, evt, t => turn = t,
            err => Debug.LogWarning("SketchScapeGuideBot: turn failed -- " + err));
        StopThinkingPulse();
        turnInFlight = false;
        if (turn != null)
        {
            yield return Execute(turn);
        }
    }

    private IEnumerator Execute(GuideTurnResponse turn)
    {
        highlighter.ClearAll();
        CurrentStepId = turn.step_id;

        CurrentState = State.Moving;
        if (!string.IsNullOrEmpty(turn.move_to.anchor_element_id) && ObjectMap.TryGet(turn.move_to.anchor_element_id, out var anchor))
        {
            Vector3 offset = ToVector3(turn.move_to.offset_m);
            Vector3 target = anchor.transform.position + anchor.transform.rotation * offset;
            target.y = Mathf.Max(target.y, minHeight);
            yield return MoveTo(target, anchor.transform.position);
        }

        CurrentState = State.Speaking;
        foreach (string elementId in turn.reveal_element_ids)
        {
            if (revealedElementIds.Contains(elementId) || !ObjectMap.TryGet(elementId, out var revealTarget))
            {
                continue;
            }
            revealedElementIds.Add(elementId);
            revealTarget.SetActive(true);
            PlayChime();
            yield return ScaleIn(revealTarget.transform, revealScaleDuration);
        }

        highlighter.Highlight(turn.highlight_element_ids, ObjectMap, transform);

        foreach (var line in turn.lines)
        {
            yield return SpeakLine(line);
        }

        if (turn.end)
        {
            yield return FadeOutAndDespawn();
            yield break;
        }

        CurrentState = State.Idle;
    }

    private IEnumerator SpeakLine(GuideTurnLine line)
    {
        if (!string.IsNullOrEmpty(line.audio_url))
        {
            using (var request = UnityWebRequestMultimedia.GetAudioClip(line.audio_url, AudioType.WAV))
            {
                yield return request.SendWebRequest();
                if (request.result == UnityWebRequest.Result.Success)
                {
                    AudioClip clip = DownloadHandlerAudioClip.GetContent(request);
                    audioSource.clip = clip;
                    audioSource.Play();
                    yield return new WaitForSeconds(clip.length + 0.25f);
                    yield break;
                }
                Debug.LogWarning("SketchScapeGuideBot: line audio failed to load -- " + request.error);
            }
        }
        // No audio for this line (mock backend, or TTS still catching up):
        // never fall back to on-screen text (AGENT.md), just a soft chime and
        // a beat so there's no silent dead air.
        PlayChime();
        yield return new WaitForSeconds(Mathf.Max(line.duration_s, 1f));
    }

    private IEnumerator MoveTo(Vector3 target, Vector3 lookAt)
    {
        Vector3 velocity = Vector3.zero;
        while (Vector3.Distance(transform.position, target) > arrivalTolerance)
        {
            transform.position = Vector3.SmoothDamp(transform.position, target, ref velocity, 0.5f, maxMoveSpeed);
            Vector3 facing = lookAt - transform.position;
            if (facing.sqrMagnitude > 0.0001f)
            {
                transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(facing), Time.deltaTime * 4f);
            }
            yield return null;
        }
        transform.position = target;
    }

    private IEnumerator ScaleIn(Transform target, float duration)
    {
        Vector3 finalScale = target.localScale == Vector3.zero ? Vector3.one : target.localScale;
        float elapsed = 0f;
        while (elapsed < duration && target != null)
        {
            elapsed += Time.deltaTime;
            target.localScale = Vector3.LerpUnclamped(Vector3.zero, finalScale, Mathf.SmoothStep(0f, 1f, elapsed / duration));
            yield return null;
        }
        if (target != null)
        {
            target.localScale = finalScale;
        }
    }

    private IEnumerator FadeOutAndDespawn()
    {
        float elapsed = 0f;
        const float fadeSeconds = 0.6f;
        Vector3 startScale = transform.localScale;
        while (elapsed < fadeSeconds)
        {
            elapsed += Time.deltaTime;
            transform.localScale = Vector3.LerpUnclamped(startScale, Vector3.zero, elapsed / fadeSeconds);
            yield return null;
        }
        Destroy(gameObject);
    }

    private void PlayChime()
    {
        if (chimeClip != null)
        {
            audioSource.PlayOneShot(chimeClip);
        }
    }

    private void StartThinkingPulse()
    {
        CurrentState = State.Thinking;
        if (thinkingHumClip != null)
        {
            audioSource.clip = thinkingHumClip;
            audioSource.loop = true;
            audioSource.volume = 0.125f; // -18 dB
            audioSource.Play();
        }
        thinkingRoutine = StartCoroutine(ThinkingPulseRoutine());
    }

    private void StopThinkingPulse()
    {
        if (thinkingRoutine != null)
        {
            StopCoroutine(thinkingRoutine);
            thinkingRoutine = null;
        }
        if (audioSource.loop)
        {
            audioSource.Stop();
            audioSource.loop = false;
            audioSource.volume = 1f;
        }
        if (haloLight != null)
        {
            haloLight.intensity = haloBaseIntensity;
        }
    }

    private IEnumerator ThinkingPulseRoutine()
    {
        while (true)
        {
            if (haloLight != null)
            {
                float phase = Mathf.Sin(Time.time * thinkingPulseHz * Mathf.PI * 2f) * 0.5f + 0.5f;
                haloLight.intensity = Mathf.Lerp(haloBaseIntensity * 0.5f, haloBaseIntensity * 1.5f, phase);
            }
            yield return null;
        }
    }

    private static Vector3 ToVector3(float[] values)
    {
        return values != null && values.Length >= 3 ? new Vector3(values[0], values[1], values[2]) : Vector3.zero;
    }
}
