using System.Collections;
using UnityEngine;

public class PortalReveal : MonoBehaviour
{
    [SerializeField] private Color portalColor = new Color(0.21f, 0.85f, 1f, 1f);
    [SerializeField] private int ringSegments = 34;
    [SerializeField] private float portalWidth = 1.1f;
    [SerializeField] private float portalHeight = 1.75f;
    [SerializeField] private float openDuration = 0.52f;

    public float OpenDelay => openDuration * 0.65f;

    private Transform visualRoot;
    private Transform core;
    private readonly System.Collections.Generic.List<Transform> ringPieces = new System.Collections.Generic.List<Transform>();
    private Coroutine revealRoutine;

    private void Awake()
    {
        BuildVisuals();
        visualRoot.localScale = Vector3.zero;
    }

    private void Update()
    {
        if (visualRoot == null || visualRoot.localScale.sqrMagnitude < 0.001f)
        {
            return;
        }

        visualRoot.Rotate(0f, 0f, 20f * Time.deltaTime, Space.Self);
        float pulse = 0.92f + Mathf.Sin(Time.time * 3.8f) * 0.08f;
        core.localScale = new Vector3(portalWidth * 0.83f * pulse, portalHeight * 0.83f * pulse, 0.1f);

        for (int i = 0; i < ringPieces.Count; i++)
        {
            float shimmer = 0.78f + Mathf.Sin(Time.time * 5f + i * 0.6f) * 0.22f;
            ringPieces[i].localScale = Vector3.one * shimmer;
        }
    }

    public void Reveal()
    {
        if (revealRoutine != null)
        {
            StopCoroutine(revealRoutine);
        }
        gameObject.SetActive(true);
        revealRoutine = StartCoroutine(ScalePortal(Vector3.one, openDuration));
    }

    public void DismissAfter(float delay)
    {
        StartCoroutine(DismissRoutine(delay));
    }

    private IEnumerator DismissRoutine(float delay)
    {
        yield return new WaitForSeconds(delay);
        if (revealRoutine != null)
        {
            StopCoroutine(revealRoutine);
        }
        revealRoutine = StartCoroutine(ScalePortal(Vector3.zero, 0.32f));
    }

    private IEnumerator ScalePortal(Vector3 target, float duration)
    {
        Vector3 source = visualRoot.localScale;
        float elapsed = 0f;
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, elapsed / duration);
            visualRoot.localScale = Vector3.LerpUnclamped(source, target, t);
            yield return null;
        }
        visualRoot.localScale = target;
    }

    private void BuildVisuals()
    {
        visualRoot = new GameObject("Portal Visuals").transform;
        visualRoot.SetParent(transform, false);

        core = GameObject.CreatePrimitive(PrimitiveType.Sphere).transform;
        core.name = "Sketch Energy";
        core.SetParent(visualRoot, false);
        core.localScale = new Vector3(portalWidth * 0.83f, portalHeight * 0.83f, 0.1f);
        var coreCollider = core.GetComponent<Collider>();
        if (coreCollider != null) Destroy(coreCollider);
        ApplyMaterial(core.GetComponent<Renderer>(), new Color(portalColor.r * 0.25f, portalColor.g * 0.55f, portalColor.b, 0.42f));

        for (int i = 0; i < ringSegments; i++)
        {
            float angle = (float)i / ringSegments * Mathf.PI * 2f;
            var piece = GameObject.CreatePrimitive(PrimitiveType.Sphere).transform;
            piece.name = "Ink Ring " + i;
            piece.SetParent(visualRoot, false);
            piece.localPosition = new Vector3(Mathf.Cos(angle) * portalWidth * 0.5f, Mathf.Sin(angle) * portalHeight * 0.5f, 0f);
            piece.localScale = Vector3.one * (0.12f + (i % 3) * 0.025f);
            var pieceCollider = piece.GetComponent<Collider>();
            if (pieceCollider != null) Destroy(pieceCollider);
            ApplyMaterial(piece.GetComponent<Renderer>(), portalColor);
            ringPieces.Add(piece);
        }
    }

    private static void ApplyMaterial(Renderer renderer, Color color)
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null) shader = Shader.Find("Standard");
        if (shader == null) shader = Shader.Find("Sprites/Default");

        var material = new Material(shader);
        material.color = color;
        if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", color);
        if (material.HasProperty("_EmissionColor"))
        {
            material.EnableKeyword("_EMISSION");
            material.SetColor("_EmissionColor", color * 2.2f);
        }
        renderer.material = material;
    }
}