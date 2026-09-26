using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;

/// <summary>
/// Parses the JSON stage_immersive_reveal produces (backend/scene_tools.py).
/// JsonUtility handles most of it directly (StagingPlanDto); the two shapes
/// it cannot (a JSON object used as a string-to-string map, and a jagged
/// array of [x,y,z] triples) are pulled out with small regex readers below.
///
/// ponytail: a real JSON library (e.g. Newtonsoft.Json via UPM) would parse
/// all of this generically; hand-rolled extraction for exactly two known
/// shapes is the lazy fix given JsonUtility's documented limits, not a
/// general-purpose parser. Upgrade if the contract grows more nested shapes.
/// </summary>
public static class StagingPlanParser
{
    private static readonly Regex Vec3TripleRegex = new Regex(
        @"\[\s*(-?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*,\s*(-?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*,\s*(-?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*\]",
        RegexOptions.Compiled);

    private static readonly Regex StringPairRegex = new Regex(
        "\"([^\"]+)\"\\s*:\\s*\"([^\"]*)\"",
        RegexOptions.Compiled);

    /// <summary>Finds the "staging" object inside a full compiled-scene.json document (meta.staging).</summary>
    public static bool TryExtractStagingBlock(string compiledSceneJson, out string block)
    {
        return TryExtractRawObject(compiledSceneJson, "staging", out block);
    }

    /// <summary>Parses a JSON object that IS a StagingPlan (the extracted "staging" block).</summary>
    public static bool TryParseFromComponentJson(string stagingJson, out StagingPlan plan)
    {
        plan = null;
        if (string.IsNullOrWhiteSpace(stagingJson))
        {
            return false;
        }

        StagingPlanDto dto;
        try
        {
            dto = JsonUtility.FromJson<StagingPlanDto>(stagingJson);
        }
        catch
        {
            return false;
        }

        if (dto == null)
        {
            return false;
        }

        plan = new StagingPlan
        {
            RevealOrder = dto.reveal_order ?? System.Array.Empty<string>(),
            LightingPreset = dto.lighting_preset ?? "",
            MotifType = dto.connecting_motif?.type ?? "",
            MotifCurve = dto.connecting_motif?.curve ?? "",
            MotifColor = ToColor(dto.connecting_motif?.color),
            NarrationText = dto.narration?.text ?? "",
            NarrationVoice = dto.narration?.voice ?? "narrator_default",
            Summary = dto.summary ?? "",
        };

        plan.MotifControlPoints = ExtractControlPoints(stagingJson);
        plan.HapticSignatures = ExtractHapticSignatures(stagingJson);
        return true;
    }

    private static Vector3[] ExtractControlPoints(string stagingJson)
    {
        if (!TryExtractRawArray(stagingJson, "control_points", out string arrayBlock))
        {
            return System.Array.Empty<Vector3>();
        }

        var matches = Vec3TripleRegex.Matches(arrayBlock);
        var points = new Vector3[matches.Count];
        for (int i = 0; i < matches.Count; i++)
        {
            points[i] = new Vector3(
                ParseFloat(matches[i].Groups[1].Value),
                ParseFloat(matches[i].Groups[2].Value),
                ParseFloat(matches[i].Groups[3].Value));
        }
        return points;
    }

    private static Dictionary<string, string> ExtractHapticSignatures(string stagingJson)
    {
        var result = new Dictionary<string, string>();
        if (!TryExtractRawObject(stagingJson, "haptic_signatures", out string objectBlock))
        {
            return result;
        }

        foreach (Match match in StringPairRegex.Matches(objectBlock))
        {
            result[match.Groups[1].Value] = match.Groups[2].Value;
        }
        return result;
    }

    private static Color ToColor(float[] rgb)
    {
        if (rgb == null || rgb.Length < 3)
        {
            return Color.white;
        }
        return new Color(rgb[0], rgb[1], rgb[2]);
    }

    private static float ParseFloat(string token)
    {
        return float.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out float value) ? value : 0f;
    }

    /// <summary>Finds `"key": { ... }` and returns it, braces included.</summary>
    internal static bool TryExtractRawObject(string json, string key, out string block)
    {
        return TryExtractBalanced(json, key, '{', '}', out block);
    }

    /// <summary>Finds `"key": [ ... ]` and returns it, brackets included.</summary>
    internal static bool TryExtractRawArray(string json, string key, out string block)
    {
        return TryExtractBalanced(json, key, '[', ']', out block);
    }

    private static bool TryExtractBalanced(string json, string key, char open, char close, out string block)
    {
        block = null;
        if (string.IsNullOrEmpty(json))
        {
            return false;
        }

        string needle = "\"" + key + "\"";
        int keyIndex = json.IndexOf(needle, System.StringComparison.Ordinal);
        if (keyIndex < 0)
        {
            return false;
        }

        int colon = json.IndexOf(':', keyIndex + needle.Length);
        if (colon < 0)
        {
            return false;
        }

        int start = colon + 1;
        while (start < json.Length && char.IsWhiteSpace(json[start]))
        {
            start++;
        }
        if (start >= json.Length || json[start] != open)
        {
            return false;
        }

        int depth = 0;
        int i = start;
        for (; i < json.Length; i++)
        {
            char c = json[i];
            if (c == '"')
            {
                // Skip over string contents so a brace/bracket inside a string
                // literal doesn't unbalance the count.
                i++;
                while (i < json.Length && json[i] != '"')
                {
                    if (json[i] == '\\')
                    {
                        i++;
                    }
                    i++;
                }
                continue;
            }
            if (c == open)
            {
                depth++;
            }
            else if (c == close)
            {
                depth--;
                if (depth == 0)
                {
                    i++;
                    break;
                }
            }
        }

        if (depth != 0)
        {
            return false;
        }

        // Keep the outer open/close characters: TryExtractStagingBlock hands
        // its result straight to JsonUtility.FromJson, which needs them.
        block = json.Substring(start, i - start);
        return true;
    }
}
