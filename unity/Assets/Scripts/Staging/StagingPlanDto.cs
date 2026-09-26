using System;

/// <summary>
/// JsonUtility DTOs for the JSON produced by backend/scene_tools.py's
/// stage_immersive_reveal (Build Plan step 6, Part A). These mirror only the
/// fields JsonUtility can deserialize directly (flat scalars, flat float[]);
/// "haptic_signatures" (a JSON object keyed by object id) and
/// "control_points" (a jagged float[][]) are NOT declared here because
/// JsonUtility cannot parse either shape -- StagingPlanParser extracts them
/// with a small hand-rolled reader instead. See StagingPlanParser.cs.
/// </summary>
[Serializable]
internal class StagingPlanDto
{
    public string[] reveal_order;
    public string lighting_preset;
    public ConnectingMotifDto connecting_motif;
    public NarrationDto narration;
    public string summary;
}

[Serializable]
internal class ConnectingMotifDto
{
    public string type;
    public string curve;
    public float[] color;
}

[Serializable]
internal class NarrationDto
{
    public string text;
    public string voice;
    public string tts_engine;
}
