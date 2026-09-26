using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Runtime-friendly form of backend/scene_tools.py's stage_immersive_reveal
/// output. Plain data, no MonoBehaviour, so ImmersiveStagingDirector stays
/// the only thing that knows how to apply it (AGENT.md-style separation:
/// StagingPlan is the contract, the director is the choreography).
/// </summary>
public class StagingPlan
{
    public string[] RevealOrder = System.Array.Empty<string>();
    public string LightingPreset = "";
    public string MotifType = "";
    public string MotifCurve = "";
    public Color MotifColor = Color.white;
    public Vector3[] MotifControlPoints = System.Array.Empty<Vector3>();
    public string NarrationText = "";
    public string NarrationVoice = "";
    public string Summary = "";
    public Dictionary<string, string> HapticSignatures = new Dictionary<string, string>();
}
