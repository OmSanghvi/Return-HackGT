using System.Collections.Generic;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

/// <summary>
/// Sanity check on real-world scale: parses every world layout under Assets/Worlds/Layouts and, for props whose
/// bounding-box height (real metres, kit-scale already applied by ReturnWorldScenes.Props) plausibly maps to a
/// known furniture category, asserts it against that category's real-world size range.
///
/// Only door and chair props currently appear in the shipped layouts (no table/bed yet), so those are the only
/// two ranges actually exercised today; table/bed rules are wired up and will start checking automatically the
/// day a layout places one. Chair seat height (0.4-0.5 m) isn't recoverable from a whole-chair bounding box
/// (that also includes the backrest), so the chair check uses a looser whole-object sanity range and is not a
/// substitute for a real seat-height measurement.
/// </summary>
public class ReturnWorldScaleTests
{
    // (exact prop id match, category label, min metres, max metres)
    static readonly (string id, string category, float min, float max)[] Rules =
    {
        ("furniture-kit/doorway", "door", 1.9f, 2.1f),
        ("furniture-kit/doorwayFront", "door", 1.9f, 2.1f),
        ("furniture-kit/doorwayOpen", "door", 1.9f, 2.1f),
        ("furniture-kit/table", "table", 0.7f, 0.8f),
        ("furniture-kit/bedSingle", "bed", 0.4f, 0.6f),
        ("furniture-kit/bedDouble", "bed", 0.4f, 0.6f),
        // Whole-chair height, not seat height: real seat height (0.4-0.5 m) isn't isolable from these bounds.
        ("furniture-kit/chair", "chair (whole-object sanity, not seat height)", 0.3f, 1.2f),
    };

    [Test]
    public void LayoutProps_MatchKnownFurnitureSizeRanges()
    {
        var sizes = ReturnWorldScenes.Props().ToDictionary(p => p.id, p => p.size);
        int checked_ = 0;
        var failures = new List<string>();

        foreach (var path in ReturnWorldScenes.LayoutPaths())
        {
            var layout = ReturnWorldScenes.ParseLayout(File.ReadAllText(path));
            foreach (var p in layout.props)
            {
                foreach (var rule in Rules)
                {
                    if (p.prop != rule.id) continue;
                    if (!sizes.TryGetValue(p.prop, out var size))
                    {
                        failures.Add($"{layout.roomId}: prop '{p.prop}' not found under Assets/Worlds/Props.");
                        continue;
                    }
                    float scale = p.scale > 0 ? p.scale : 1f;
                    float height = size.y * scale;
                    checked_++;
                    if (height < rule.min || height > rule.max)
                        failures.Add($"{layout.roomId}: {rule.category} '{p.prop}' is {height:F2} m tall, expected {rule.min}-{rule.max} m.");
                }
            }
        }

        Assert.Greater(checked_, 0, "No recognizable door/table/chair/bed props found in any layout; nothing was checked.");
        Assert.IsEmpty(failures, string.Join("\n", failures));
    }
}
