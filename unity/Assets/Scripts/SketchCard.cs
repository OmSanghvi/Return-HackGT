using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// A Notability page shown as a flat card on a slim stand (Build Plan step 7,
/// Path 1). The root is a unit card, so the scene object's scale is the card's
/// width and height in meters. The page faces the root's +Z.
/// </summary>
[DisallowMultipleComponent]
[DefaultExecutionOrder(-10)] // Build the stand before ContributorAttribution measures bounds.
public sealed class SketchCard : MonoBehaviour
{
    private const float BackingDepth = 0.01f;
    private const float StandWidth = 0.025f;

    [SerializeField] private Renderer page;

    public static GameObject Create(string name, Material pageMaterial)
    {
        var root = new GameObject(name);
        var collider = root.AddComponent<BoxCollider>();
        collider.size = new Vector3(1f, 1f, BackingDepth * 2f);

        var backing = GameObject.CreatePrimitive(PrimitiveType.Cube);
        backing.name = "Card Backing";
        DestroyCollider(backing);
        backing.transform.SetParent(root.transform, false);
        backing.transform.localScale = new Vector3(1.03f, 1.03f, BackingDepth);
        backing.GetComponent<Renderer>().sharedMaterial = CreateLitMaterial(new Color(0.92f, 0.9f, 0.86f));

        var pageQuad = GameObject.CreatePrimitive(PrimitiveType.Quad);
        pageQuad.name = "Page";
        DestroyCollider(pageQuad);
        pageQuad.transform.SetParent(root.transform, false);
        pageQuad.transform.localPosition = new Vector3(0f, 0f, BackingDepth * 0.6f);
        pageQuad.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);
        var pageRenderer = pageQuad.GetComponent<Renderer>();
        pageRenderer.sharedMaterial = pageMaterial != null ? pageMaterial : CreatePageMaterial(null);

        root.AddComponent<SketchCard>().page = pageRenderer;
        return root;
    }

    public static Material CreatePageMaterial(Texture2D texture)
    {
        var shader = Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Texture");
        var material = new Material(shader) { name = "Sketch Page", color = Color.white };
        if (texture != null)
        {
            material.mainTexture = texture;
        }
        return material;
    }

    public void LoadTexture(string url)
    {
        StartCoroutine(LoadTextureRoutine(url));
    }

    private IEnumerator LoadTextureRoutine(string url)
    {
        using (var request = UnityWebRequestTexture.GetTexture(url))
        {
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning("SketchCard: could not load " + url + " — " + request.error);
                yield break;
            }
            if (page != null)
            {
                page.material.mainTexture = DownloadHandlerTexture.GetContent(request);
            }
        }
    }

    private Transform stand;

    private void Start()
    {
        var standObject = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        standObject.name = "Card Stand";
        DestroyCollider(standObject);
        standObject.GetComponent<Renderer>().sharedMaterial = CreateLitMaterial(new Color(0.35f, 0.27f, 0.2f));
        stand = standObject.transform;
        stand.SetParent(transform, false);
        FitStand();
    }

    private void LateUpdate()
    {
        // The card animates in and can be scaled/moved by edits; keep the stand
        // a fixed width, reaching from the card's lower edge to the floor.
        if (transform.hasChanged)
        {
            FitStand();
            transform.hasChanged = false;
        }
    }

    private void FitStand()
    {
        var collider = GetComponent<Collider>();
        if (stand == null || collider == null)
        {
            return;
        }
        Bounds bounds = collider.bounds;
        float height = bounds.min.y;
        stand.gameObject.SetActive(height > 0.01f);
        if (height <= 0.01f)
        {
            return;
        }

        // A cylinder primitive is 2 units tall. Convert the wanted world size to
        // local scale under the card's (non-uniform) scale.
        stand.position = new Vector3(bounds.center.x, height / 2f, bounds.center.z);
        Vector3 parentScale = transform.lossyScale;
        stand.localScale = new Vector3(
            StandWidth / Mathf.Max(parentScale.x, 0.0001f),
            height / 2f / Mathf.Max(parentScale.y, 0.0001f),
            StandWidth / Mathf.Max(parentScale.z, 0.0001f));
    }

    private static Material CreateLitMaterial(Color color)
    {
        var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        return new Material(shader) { color = color };
    }

    public static void DestroyCollider(GameObject target)
    {
        var collider = target.GetComponent<Collider>();
        if (collider == null)
        {
            return;
        }
        if (Application.isPlaying)
        {
            Destroy(collider);
        }
        else
        {
            DestroyImmediate(collider);
        }
    }
}
