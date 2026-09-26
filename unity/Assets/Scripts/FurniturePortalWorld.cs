using System.Collections;
using UnityEngine;

/// <summary>
/// Presents the curated Blender furniture kit as a warm portal destination.
/// The source FBX is local in Resources; this never requires a network call.
/// </summary>
[RequireComponent(typeof(SketchSceneLoader))]
public class FurniturePortalWorld : MonoBehaviour
{
    [SerializeField] private string resourcePath = "Furniture/FurniturePortalWorld";
    [SerializeField] private Vector3 worldPosition = new Vector3(0f, 0f, 8.5f);
    [SerializeField] private float worldScale = 1.1f;

    private SketchSceneLoader loader;
    private GameObject activeWorld;

    private void Awake() => loader = GetComponent<SketchSceneLoader>();

    public void RevealFurnitureWorld() => StartCoroutine(RevealRoutine());

    private IEnumerator RevealRoutine()
    {
        loader.ReportStatus("Opening furniture world...");
        loader.LoadSceneFromJson("{\"objects\":[],\"instructions\":[],\"meta\":{\"pipeline\":\"local-art\"}}");
        yield return new WaitForSeconds(0.42f);

        if (activeWorld != null) Destroy(activeWorld);
        var furniturePrefab = Resources.Load<GameObject>(resourcePath);
        if (furniturePrefab == null)
        {
            loader.ReportStatus("Furniture FBX is importing — try again in a moment.");
            yield break;
        }

        activeWorld = new GameObject("Furniture Portal World");
        activeWorld.transform.position = worldPosition;
        activeWorld.transform.localScale = Vector3.one * worldScale;
        CreateFloor(activeWorld.transform);
        CreateLight(activeWorld.transform, new Vector3(-2.8f, 2.6f, 1f), new Color(1f, 0.55f, 0.24f), 4f);
        CreateLight(activeWorld.transform, new Vector3(2.5f, 2.1f, 2.8f), new Color(0.3f, 0.72f, 1f), 3f);

        var furniture = Instantiate(furniturePrefab, activeWorld.transform);
        furniture.name = "Curated Blender Furniture";
        furniture.transform.localPosition = Vector3.zero;
        furniture.transform.localRotation = Quaternion.identity;
        furniture.transform.localScale = Vector3.one;
        activeWorld.AddComponent<FurnitureWorldArrival>().Begin();
        loader.ReportStatus("Furniture world ready — built from your Blender kit.");
    }

    private static void CreateFloor(Transform root)
    {
        var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
        floor.name = "Furniture World Floor";
        floor.transform.SetParent(root, false);
        floor.transform.localPosition = new Vector3(0f, -0.02f, 2.2f);
        floor.transform.localScale = new Vector3(0.72f, 1f, 0.72f);
        var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        var material = new Material(shader) { color = new Color(0.065f, 0.08f, 0.13f) };
        if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", 0.25f);
        if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", 0.55f);
        floor.GetComponent<Renderer>().material = material;
    }

    private static void CreateLight(Transform root, Vector3 localPosition, Color color, float range)
    {
        var lightObject = new GameObject("Portal Room Light");
        lightObject.transform.SetParent(root, false);
        lightObject.transform.localPosition = localPosition;
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Point;
        light.color = color;
        light.intensity = 2.2f;
        light.range = range;
    }

    private sealed class FurnitureWorldArrival : MonoBehaviour
    {
        public void Begin() => StartCoroutine(Animate());

        private IEnumerator Animate()
        {
            Vector3 finalScale = transform.localScale;
            transform.localScale = Vector3.zero;
            float elapsed = 0f;
            const float duration = 0.75f;
            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t = 1f - Mathf.Pow(1f - Mathf.Clamp01(elapsed / duration), 3f);
                transform.localScale = Vector3.LerpUnclamped(Vector3.zero, finalScale, t);
                yield return null;
            }
            transform.localScale = finalScale;
        }
    }
}
