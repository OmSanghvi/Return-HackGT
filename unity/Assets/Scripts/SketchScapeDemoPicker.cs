using UnityEngine;

/// <summary>
/// Instant, local showcase worlds for judging and offline demos. These JSON
/// documents use the same loader and portal path as API results, but never
/// claim to be SAM3D output and never make a network request.
/// </summary>
[RequireComponent(typeof(SketchSceneLoader))]
public class SketchScapeDemoPicker : MonoBehaviour
{
    [SerializeField] private bool showDebugUi = true;

    private SketchSceneLoader loader;
    private FurniturePortalWorld furnitureWorld;

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
        furnitureWorld = GetComponent<FurniturePortalWorld>();
    }

    public void ShowDoodleGrove() => Load("Doodle Grove", DoodleGrove);
    public void ShowPortalVillage() => Load("Portal Village", PortalVillage);
    public void ShowMoonlitGarden() => Load("Moonlit Garden", MoonlitGarden);

    public void ShowFurnitureWorld()
    {
        if (furnitureWorld == null)
        {
            loader.ReportStatus("Furniture world is not configured yet.");
            return;
        }
        furnitureWorld.RevealFurnitureWorld();
    }

    private void Load(string title, string json)
    {
        loader.ReportStatus("Opening " + title + "...");
        loader.LoadSceneFromJson(json);
    }

    private void OnGUI()
    {
        if (!showDebugUi)
        {
            return;
        }
        GUILayout.BeginArea(new Rect(24f, 478f, 430f, 144f), GUI.skin.box);
        GUILayout.Label("INSTANT SHOWCASE WORLDS");
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Doodle Grove")) ShowDoodleGrove();
        if (GUILayout.Button("Portal Village")) ShowPortalVillage();
        if (GUILayout.Button("Moonlit Garden")) ShowMoonlitGarden();
        GUILayout.EndHorizontal();
        if (GUILayout.Button("Furniture Portal (Blender)")) ShowFurnitureWorld();
        GUILayout.Label("Local fallback — no upload, model, or network required.");
        GUILayout.EndArea();
    }

    private const string DoodleGrove =
        "{\"objects\":[" +
        "{\"id\":\"tree_1\",\"type\":\"tree\",\"position\":[-3,0,7],\"rotation\":[0,-12,0],\"scale\":[1.35,1.35,1.35],\"source\":\"placeholder\"}," +
        "{\"id\":\"house_1\",\"type\":\"house\",\"position\":[1.9,0,8.1],\"rotation\":[0,-20,0],\"scale\":[1.2,1.2,1.2],\"source\":\"placeholder\"}," +
        "{\"id\":\"tree_2\",\"type\":\"tree\",\"position\":[4.4,0,10.5],\"rotation\":[0,22,0],\"scale\":[0.78,0.78,0.78],\"source\":\"placeholder\"}]," +
        "\"instructions\":[],\"meta\":{\"pipeline\":\"local-showcase\",\"title\":\"Doodle Grove\"}}";

    private const string PortalVillage =
        "{\"objects\":[" +
        "{\"id\":\"house_1\",\"type\":\"house\",\"position\":[-2.8,0,8.8],\"rotation\":[0,20,0],\"scale\":[1,1,1],\"source\":\"placeholder\"}," +
        "{\"id\":\"house_2\",\"type\":\"house\",\"position\":[2.6,0,8.1],\"rotation\":[0,-18,0],\"scale\":[1.5,1.5,1.5],\"source\":\"placeholder\"}," +
        "{\"id\":\"tree_1\",\"type\":\"tree\",\"position\":[0,0,12.4],\"rotation\":[0,0,0],\"scale\":[1.8,1.8,1.8],\"source\":\"placeholder\"}," +
        "{\"id\":\"tree_2\",\"type\":\"tree\",\"position\":[-5,0,12],\"rotation\":[0,35,0],\"scale\":[0.75,0.75,0.75],\"source\":\"placeholder\"}]," +
        "\"instructions\":[],\"meta\":{\"pipeline\":\"local-showcase\",\"title\":\"Portal Village\"}}";

    private const string MoonlitGarden =
        "{\"objects\":[" +
        "{\"id\":\"tree_1\",\"type\":\"tree\",\"position\":[-4.8,0,9.8],\"rotation\":[0,-26,0],\"scale\":[1.6,1.6,1.6],\"source\":\"placeholder\"}," +
        "{\"id\":\"tree_2\",\"type\":\"tree\",\"position\":[3.8,0,8],\"rotation\":[0,18,0],\"scale\":[1.15,1.15,1.15],\"source\":\"placeholder\"}," +
        "{\"id\":\"house_1\",\"type\":\"house\",\"position\":[0.3,0,13.3],\"rotation\":[0,180,0],\"scale\":[0.82,0.82,0.82],\"source\":\"placeholder\"}," +
        "{\"id\":\"tree_3\",\"type\":\"tree\",\"position\":[0,0,6.8],\"rotation\":[0,0,0],\"scale\":[0.6,0.6,0.6],\"source\":\"placeholder\"}]," +
        "\"instructions\":[],\"meta\":{\"pipeline\":\"local-showcase\",\"title\":\"Moonlit Garden\"}}";
}
