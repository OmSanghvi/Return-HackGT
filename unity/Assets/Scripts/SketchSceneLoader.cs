using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

public class SketchSceneLoader : MonoBehaviour
{
    [Header("Scene Sources")]
    [SerializeField] private string backendUrl = "http://127.0.0.1:8000/sketch";
    [SerializeField] private string apiBaseUrl = "http://127.0.0.1:8000";
    [SerializeField] private bool requestBackendOnStart = false;
    [SerializeField] private float requestTimeoutSeconds = 5f;
    [SerializeField] private Texture2D sketchTexture;

    [Header("Placeholder Prefabs")]
    [SerializeField] private GameObject housePrefab;
    [SerializeField] private GameObject treePrefab;

    [Header("Reveal")]
    [SerializeField] private PortalReveal portalReveal;
    [SerializeField] private Transform spawnedObjectsRoot;
    [SerializeField] private float spawnStaggerSeconds = 0.22f;

    private readonly Dictionary<string, GameObject> spawnedObjects = new Dictionary<string, GameObject>();
    

    public string Status { get; private set; } = "Ready";
    public event Action<string> StatusChanged;
private bool isLoading;

    private void Awake()
    {
        EnsureSpawnRoot();
    }

    private void Start()
    {
        SetStatus("Reading sketch...");
        StartCoroutine(ReloadScene());
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.R) && !isLoading)
        {
            StartCoroutine(ReloadScene());
        }
    }

    public void ReloadFallbackScene()
    {
        if (!isLoading)
        {
            SetStatus("Loading local showcase scene...");
            StartCoroutine(LoadSceneRoutine(FallbackSceneJson()));
        }
    }

    public IEnumerator ReloadScene()
    {
        if (isLoading)
        {
            yield break;
        }

        isLoading = true;
        string json = null;

        if (requestBackendOnStart)
        {
            yield return StartCoroutine(RequestScene(sceneJson => json = sceneJson));
        }

        if (string.IsNullOrWhiteSpace(json))
        {
            json = FallbackSceneJson();
            SetStatus("Using local showcase scene.");
            Debug.Log("SketchSceneLoader: backend unavailable; using the local showcase scene.");
        }

        yield return StartCoroutine(LoadSceneRoutine(json));
        isLoading = false;
    }

    public void LoadSceneFromJson(string json)
    {
        if (!isLoading)
        {
            StartCoroutine(LoadExternalSceneRoutine(json));
        }
    }

    private IEnumerator LoadExternalSceneRoutine(string json)
    {
        isLoading = true;
        yield return StartCoroutine(LoadSceneRoutine(json));
        isLoading = false;
    }

    public void ApplySceneUpdate(string json)
    {
        if (isLoading)
        {
            return;
        }

        if (TryParseDocument(json, out var document))
        {
            StartCoroutine(ApplySceneUpdateRoutine(document));
        }
        else
        {
            ReportStatus("Edit response was invalid.");
        }
    }

    public void ReportStatus(string message)
    {
        SetStatus(message);
    }

    public void ConfigureApiBaseUrl(string value)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            apiBaseUrl = value.TrimEnd('/');
        }
    }

    private IEnumerator RequestScene(Action<string> onComplete)
    {
        onComplete(null);

        if (sketchTexture == null)
        {
            sketchTexture = Resources.Load<Texture2D>("hackgttest");
        }

        if (sketchTexture == null || !sketchTexture.isReadable)
        {
            Debug.LogWarning("SketchSceneLoader: no readable sketch texture; skipping backend request.");
            yield break;
        }

        var form = new WWWForm();
        form.AddBinaryData("sketch", sketchTexture.EncodeToPNG(), "sketch.png", "image/png");

        using (var request = UnityWebRequest.Post(backendUrl, form))
        {
            request.timeout = Mathf.CeilToInt(requestTimeoutSeconds);
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning("SketchSceneLoader: backend request failed: " + request.error);
                yield break;
            }

            if (TryParseDocument(request.downloadHandler.text, out _))
            {
                SetStatus("Scene JSON received.");
                onComplete(request.downloadHandler.text);
            }
            else
            {
                Debug.LogWarning("SketchSceneLoader: backend returned invalid scene JSON.");
            }
        }
    }

    private IEnumerator LoadSceneRoutine(string json)
    {
        if (!TryParseDocument(json, out var document))
        {
            SetStatus("Scene JSON was invalid.");
            Debug.LogError("SketchSceneLoader: scene JSON has no valid objects array.");
            yield break;
        }

        ClearSpawnedObjects();
        SetStatus("Opening sketch portal...");
        portalReveal = portalReveal != null ? portalReveal : FindAnyObjectByType<PortalReveal>();

        if (portalReveal != null)
        {
            portalReveal.Reveal();
            yield return new WaitForSeconds(portalReveal.OpenDelay);
        }

        for (int i = 0; i < document.objects.Length; i++)
        {
            var sceneObject = document.objects[i];
            GameObject instance;
            if (sceneObject.source == "sketch_card")
            {
                // A Notability page shown as a flat card (Build Plan step 7).
                instance = SketchCard.Create(sceneObject.id, null);
                instance.transform.SetParent(spawnedObjectsRoot, false);
                if (!string.IsNullOrWhiteSpace(sceneObject.asset_url))
                {
                    instance.GetComponent<SketchCard>().LoadTexture(ResolveAssetReference(sceneObject.asset_url));
                }
            }
            else if (TryGetPrefab(sceneObject.type, out var prefab))
            {
                instance = Instantiate(prefab, spawnedObjectsRoot);
            }
            else if (!string.IsNullOrWhiteSpace(sceneObject.asset_url))
            {
                // Real SAM3D has no semantic prefab. Keep this visual fallback
                // until an installed splat renderer replaces it.
                instance = CreateArtifactPlaceholder(sceneObject.type);
                instance.transform.SetParent(spawnedObjectsRoot, false);
            }
            else
            {
                Debug.LogWarning("SketchSceneLoader: unsupported object type '" + sceneObject.type + "'.");
                continue;
            }

            SetStatus("Revealing " + sceneObject.type + "...");
            instance.name = string.IsNullOrWhiteSpace(sceneObject.id) ? sceneObject.type : sceneObject.id;
            var interactive = instance.GetComponent<NamedSceneInteractive>();
            if (interactive == null)
            {
                interactive = instance.AddComponent<NamedSceneInteractive>();
            }
            interactive.Configure(instance.name, sceneObject.type, sceneObject.actions);
            if (sceneObject.grabbable && instance.GetComponent<SketchScapePickup>() == null)
            {
                instance.AddComponent<SketchScapePickup>();
            }
            FindAnyObjectByType<SceneInteractionController>()?.Register(interactive);
            FreezePlaceholderPhysics(instance);
            instance.transform.SetPositionAndRotation(
                ToVector3(sceneObject.position, Vector3.zero),
                Quaternion.Euler(ToVector3(sceneObject.rotation, Vector3.zero)));

            var finalScale = ToVector3(sceneObject.scale, Vector3.one);
            spawnedObjects[instance.name] = instance;
            TryLoadAsset(sceneObject.asset_url, instance);
            StartCoroutine(AnimateObjectArrival(instance.transform, finalScale));

            yield return new WaitForSeconds(spawnStaggerSeconds);
        }

        if (portalReveal != null)
        {
            portalReveal.DismissAfter(0.9f);
            SetStatus("World ready — press R to reload.");
        }
    }

    private IEnumerator ApplySceneUpdateRoutine(SketchSceneDocument document)
    {
        SetStatus("Updating world...");
        for (int i = 0; i < document.objects.Length; i++)
        {
            var sceneObject = document.objects[i];
            if (!spawnedObjects.TryGetValue(sceneObject.id, out var instance) || instance == null)
            {
                Debug.LogWarning("SketchSceneLoader: update target not found: " + sceneObject.id);
                continue;
            }

            StartCoroutine(AnimateObjectUpdate(
                instance.transform,
                ToVector3(sceneObject.position, instance.transform.position),
                Quaternion.Euler(ToVector3(sceneObject.rotation, instance.transform.eulerAngles)),
                ToVector3(sceneObject.scale, instance.transform.localScale)));
            yield return new WaitForSeconds(0.08f);
        }

        yield return new WaitForSeconds(0.42f);
        SetStatus("World updated — press T to repeat the edit.");
    }

    private IEnumerator AnimateObjectUpdate(
        Transform subject,
        Vector3 targetPosition,
        Quaternion targetRotation,
        Vector3 targetScale)
    {
        Vector3 sourcePosition = subject.position;
        Quaternion sourceRotation = subject.rotation;
        Vector3 sourceScale = subject.localScale;
        const float duration = 0.38f;
        float elapsed = 0f;

        while (elapsed < duration && subject != null)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, elapsed / duration);
            subject.position = Vector3.Lerp(sourcePosition, targetPosition, t);
            subject.rotation = Quaternion.Slerp(sourceRotation, targetRotation, t);
            subject.localScale = Vector3.Lerp(sourceScale, targetScale, t);
            yield return null;
        }

        if (subject != null)
        {
            subject.SetPositionAndRotation(targetPosition, targetRotation);
            subject.localScale = targetScale;
        }
    }

    private IEnumerator AnimateObjectArrival(Transform subject, Vector3 finalScale)
    {
        Vector3 destination = subject.position;
        Vector3 portalOrigin = portalReveal != null ? portalReveal.transform.position : destination;
        portalOrigin.y = Mathf.Max(portalOrigin.y - 1f, 0f);
        subject.position = portalOrigin;
        subject.localScale = Vector3.zero;

        const float duration = 0.58f;
        float elapsed = 0f;
        while (elapsed < duration && subject != null)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.Clamp01(elapsed / duration);
            float eased = 1f - Mathf.Pow(1f - t, 3f);
            subject.position = Vector3.Lerp(portalOrigin, destination, eased);
            subject.localScale = Vector3.LerpUnclamped(Vector3.zero, finalScale, eased);
            yield return null;
        }

        if (subject != null)
        {
            subject.position = destination;
            subject.localScale = finalScale;
        }
    }

    private void SetStatus(string message)
    {
        Status = message;
        StatusChanged?.Invoke(message);
    }

    private void TryLoadAsset(string assetReference, GameObject placeholder)
    {
        if (string.IsNullOrWhiteSpace(assetReference))
        {
            return;
        }

        string resolvedReference = ResolveAssetReference(assetReference);
        if (assetReference.EndsWith(".ply", StringComparison.OrdinalIgnoreCase))
        {
            var splatLoader = FindAnyObjectByType<GaussianSplatBridge>();
            if (splatLoader == null || !splatLoader.TryLoad(resolvedReference))
            {
                Debug.LogWarning("SketchSceneLoader: a SAM3D PLY arrived, but no Gaussian-splat renderer is configured.");
            }
            return;
        }
        if (!assetReference.EndsWith(".glb", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        var glbLoader = FindAnyObjectByType<GlbAssetLoader>();
        if (glbLoader == null)
        {
            Debug.LogWarning("SketchSceneLoader: no GlbAssetLoader is configured; keeping placeholder.");
            return;
        }

        glbLoader.LoadAndReplace(resolvedReference, placeholder);
    }

    private string ResolveAssetReference(string assetReference)
    {
        return Uri.TryCreate(assetReference, UriKind.Absolute, out var absolute)
            ? absolute.AbsoluteUri
            : apiBaseUrl.TrimEnd('/') + "/" + assetReference.TrimStart('/');
    }

    private static GameObject CreateArtifactPlaceholder(string objectType)
    {
        var placeholder = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        placeholder.name = "SAM3D artifact fallback — " + objectType;
        placeholder.transform.localScale = Vector3.one * 0.8f;
        var renderer = placeholder.GetComponent<Renderer>();
        if (renderer != null)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var material = new Material(shader);
            material.color = new Color(0.24f, 0.88f, 1f, 1f);
            if (material.HasProperty("_EmissionColor"))
            {
                material.EnableKeyword("_EMISSION");
                material.SetColor("_EmissionColor", new Color(0.05f, 0.35f, 0.6f));
            }
            renderer.material = material;
        }
        return placeholder;
    }

    private static void FreezePlaceholderPhysics(GameObject instance)
    {
        foreach (var body in instance.GetComponentsInChildren<Rigidbody>())
        {
            body.isKinematic = true;
            body.useGravity = false;
        }
    }

    private bool TryGetPrefab(string type, out GameObject prefab)
    {
        prefab = type != null && type.Equals("house", StringComparison.OrdinalIgnoreCase) ? housePrefab
            : type != null && type.Equals("tree", StringComparison.OrdinalIgnoreCase) ? treePrefab
            : null;
        return prefab != null;
    }

    private void EnsureSpawnRoot()
    {
        if (spawnedObjectsRoot != null)
        {
            return;
        }

        var root = new GameObject("Sketch Scene Objects");
        root.transform.SetParent(transform, false);
        spawnedObjectsRoot = root.transform;
    }

    private void ClearSpawnedObjects()
    {
        foreach (Transform child in spawnedObjectsRoot)
        {
            Destroy(child.gameObject);
        }
        spawnedObjects.Clear();
    }

    private static bool TryParseDocument(string json, out SketchSceneDocument document)
    {
        document = null;
        if (string.IsNullOrWhiteSpace(json))
        {
            return false;
        }

        var envelope = JsonUtility.FromJson<SketchSceneEnvelope>(json);
        document = envelope != null && envelope.scene != null && envelope.scene.objects != null
            ? envelope.scene
            : envelope;

        return document != null && document.objects != null;
    }

    private static Vector3 ToVector3(float[] values, Vector3 fallback)
    {
        return values != null && values.Length >= 3
            ? new Vector3(values[0], values[1], values[2])
            : fallback;
    }

    private static string FallbackSceneJson()
    {
        return "{\"objects\":[{\"id\":\"tree_1\",\"type\":\"tree\",\"position\":[-2.1,0,7],\"rotation\":[0,0,0],\"scale\":[1,1,1]},{\"id\":\"house_1\",\"type\":\"house\",\"position\":[2.1,0,7.7],\"rotation\":[0,0,0],\"scale\":[1.4,1.4,1.4]}]}";
    }
}

[Serializable]
public class SketchSceneEnvelope : SketchSceneDocument
{
    public SketchSceneDocument scene;
}

[Serializable]
public class SketchSceneDocument
{
    public SketchSceneObject[] objects;
}

[Serializable]
public class SketchSceneObject
{
    public string id;
    public string type;
    public float[] position;
    public float[] rotation;
    public float[] scale;
    public string asset_url;
    public string source;
    public string[] actions;
    public bool grabbable;
}
