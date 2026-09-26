using UnityEngine;

[RequireComponent(typeof(SketchSceneLoader))]
public class SketchSceneStatus : MonoBehaviour
{
    private SketchSceneLoader loader;
    private GUIStyle titleStyle;
    private GUIStyle statusStyle;

    private void Awake()
    {
        loader = GetComponent<SketchSceneLoader>();
    }

    private void OnGUI()
    {
        if (loader == null)
        {
            return;
        }

        EnsureStyles();
        GUILayout.BeginArea(new Rect(24f, 24f, 430f, 90f), GUI.skin.box);
        GUILayout.Label("SKETCHSCAPE", titleStyle);
        GUILayout.Label(loader.Status, statusStyle);
        GUILayout.Label("R  Reload scene", GUI.skin.label);
        GUILayout.EndArea();
    }

    private void EnsureStyles()
    {
        if (titleStyle != null)
        {
            return;
        }

        titleStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 22,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(0.3f, 0.95f, 1f) }
        };
        statusStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 15,
            normal = { textColor = Color.white }
        };
    }
}