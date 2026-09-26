using System;

/// <summary>
/// [Serializable] DTOs for `/v1/rooms/{project_id}/guide/*` (Build Plan step 32,
/// backend/guide_routes.py + backend/guide.py), parsed with JsonUtility. Field
/// names are snake_case to match the JSON exactly. The backend sends "" and []
/// instead of null (JsonUtility can't represent absent values), so every string
/// here should be treated as "absent" when empty and every list as "absent"
/// when empty.
/// </summary>
[Serializable]
public sealed class GuidePersona
{
    public string name;
    public string voice;
    public string style;
}

[Serializable]
public sealed class GuideTourStepView
{
    public string step_id;
    public string stop_anchor_element_id;
    public float[] stop_offset_m = new float[3];
    public string[] focus_element_ids = Array.Empty<string>();
    public string[] reveal_element_ids = Array.Empty<string>();
}

[Serializable]
public sealed class GuideTourElementView
{
    public string element_id;
    public string object_id = "";
    public string staging_cue_id = "";
    public bool initially_visible = true;
}

[Serializable]
public sealed class GuideTourResponse
{
    public bool tour_available;
    public int tour_version;
    public GuidePersona persona;
    public GuideTourStepView[] steps = Array.Empty<GuideTourStepView>();
    public GuideTourElementView[] elements = Array.Empty<GuideTourElementView>();
    public string[] stale_element_ids = Array.Empty<string>();
}

[Serializable]
public sealed class GuideEvent
{
    public string type;
    public string element_id = "";
    public string text = "";

    public GuideEvent(string eventType, string elementId = "", string eventText = "")
    {
        type = eventType;
        element_id = elementId ?? "";
        text = eventText ?? "";
    }
}

[Serializable]
public sealed class GuideTurnRequestBody
{
    public string client_turn_id;
    public int turn_seq;
    public GuideEvent @event;
}

[Serializable]
public sealed class GuideTurnLine
{
    public string line_id;
    public string text;
    public string[] fact_ids = Array.Empty<string>();
    public string audio_url = "";
    public float duration_s;
}

[Serializable]
public sealed class GuideMoveTo
{
    public string anchor_element_id = "";
    public float[] offset_m = new float[3];
}

[Serializable]
public sealed class GuideValidationInfo
{
    public bool passed;
    public string[] repairs = Array.Empty<string>();
}

[Serializable]
public sealed class GuideTurnResponse
{
    public int turn_seq;
    public string step_id;
    public bool end;
    public GuideTurnLine[] lines = Array.Empty<GuideTurnLine>();
    public GuideMoveTo move_to = new GuideMoveTo();
    public string[] highlight_element_ids = Array.Empty<string>();
    public string[] reveal_element_ids = Array.Empty<string>();
    public string source;
    public string backend;
    public string model;
    public GuideValidationInfo validation;
    public int latency_ms;
}

[Serializable]
public sealed class GuideSessionResponse
{
    public string session_id;
    public int tour_version;
    public GuideTurnResponse turn;
}

/// <summary>
/// Body of a 409 (backend/guide.py GuideTurnConflict): the session moved on
/// without us, so here's its actual turn_count and last turn to resync
/// against. `last_turn` is a real JSON null when the session has no prior
/// turn (never happens in practice -- `start_session` always records turn 0
/// first) or when the conflict predates any turn for this client; JsonUtility
/// leaves it default-constructed rather than null in that case, so callers
/// check `last_turn.step_id` for emptiness rather than a null reference.
/// </summary>
[Serializable]
public sealed class GuideTurnConflict
{
    public int turn_count;
    public GuideTurnResponse last_turn = new GuideTurnResponse();
}
