using System.Collections.Generic;
using UnityEngine;
using UnityEditor;

namespace SketchScape
{
    public static partial class RoomPolish
    {
        // Polish pass for bed.unity (root "SharedRoom_bed").
        // Everything created here lives under c.polish; all positions are absolute world-space so re-running is idempotent.
        internal static void PolishBed(Ctx c)
        {
            // ---- Interior bounds: x -2.0..2.4, y 0..3.5, z -2.2..4.15 ----
            const float xMin = -2.0f, xMax = 2.4f;
            const float yMin = 0f, yMax = 3.5f;
            const float zMin = -2.2f, zMax = 4.15f;
            const float wallT = 0.15f;
            const float halfT = wallT * 0.5f;

            float cx = (xMin + xMax) * 0.5f;   // 0.2
            float cy = (yMin + yMax) * 0.5f;   // 1.75
            float cz = (zMin + zMax) * 0.5f;   // 0.975
            float sx = xMax - xMin;            // 4.4
            float sy = yMax - yMin;            // 3.5
            float sz = zMax - zMin;            // 6.35

            var interior = new Bounds(new Vector3(cx, cy, cz), new Vector3(sx, sy, sz));

            // ---- 1. Shell ----
            Transform shell = Group(c.polish, "Shell");
            Material wallMat = Mat(c, "Wall", new Color(0.86f, 0.84f, 0.80f), 0.06f);
            Material ceilingMat = Mat(c, "Ceiling", new Color(0.90f, 0.89f, 0.86f), 0.04f, CeilingTiles(),
                new Vector2(4.4f / 2.4f, 6.35f / 2.4f));

            // North/South walls span the full x extent plus wall thickness so the corners close.
            Box(shell, "Wall North", new Vector3(cx, cy, zMax + halfT), new Vector3(sx + 2f * wallT, sy, wallT), wallMat, true, false);
            Box(shell, "Wall South", new Vector3(cx, cy, zMin - halfT), new Vector3(sx + 2f * wallT, sy, wallT), wallMat, true, false);
            Box(shell, "Wall East", new Vector3(xMax + halfT, cy, cz), new Vector3(wallT, sy, sz), wallMat, true, false);
            Box(shell, "Wall West", new Vector3(xMin - halfT, cy, cz), new Vector3(wallT, sy, sz), wallMat, true, false);
            // Ceiling sits on top of the interior, spanning the full x/z plus thickness.
            Box(shell, "Ceiling", new Vector3(cx, yMax + halfT, cz), new Vector3(sx + 2f * wallT, wallT, sz + 2f * wallT), ceilingMat, true, false);
            c.log.Add("Shell: 4 walls + ceiling around interior x[-2.0,2.4] y[0,3.5] z[-2.2,4.15], t=0.15");

            // ---- 2. Baseboards (flush against the inside face of each wall) ----
            const float bbH = 0.10f;
            const float bbT = 0.02f;
            float bbY = yMin + bbH * 0.5f;
            Material baseboardMat = Mat(c, "Baseboard", new Color(0.05f, 0.05f, 0.05f), 0.25f);
            Box(shell, "Baseboard North", new Vector3(cx, bbY, zMax - bbT * 0.5f), new Vector3(sx, bbH, bbT), baseboardMat, false, false);
            Box(shell, "Baseboard South", new Vector3(cx, bbY, zMin + bbT * 0.5f), new Vector3(sx, bbH, bbT), baseboardMat, false, false);
            Box(shell, "Baseboard East", new Vector3(xMax - bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, sz), baseboardMat, false, false);
            Box(shell, "Baseboard West", new Vector3(xMin + bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, sz), baseboardMat, false, false);
            c.log.Add("Baseboards: black 0.10 x 0.02 along all four walls");

            // ---- 3. Night panel behind the blinds (so gaps read as darkness, not white wall) ----
            Material nightMat = Mat(c, "Night", new Color(0.02f, 0.03f, 0.06f), 0.0f);
            Box(shell, "Night Window", new Vector3(0.15f, 2.1f, 4.12f), new Vector3(3.1f, 2.4f, 0.02f), nightMat, false, false);
            c.log.Add("Night Window: dark panel behind the blinds at (0.15, 2.1, 4.12)");

            // ---- 4. Ceiling light panels ----
            Material panelMat = Mat(c, "LightPanel", new Color(0.95f, 0.95f, 0.92f), 0.2f, null, null,
                new Color(1.6f, 1.55f, 1.4f));
            Vector3 panelSize = new Vector3(0.6f, 0.03f, 1.2f);
            Box(shell, "Light Panel L", new Vector3(-1.0f, 3.47f, 1.2f), panelSize, panelMat, false, false);
            Box(shell, "Light Panel R", new Vector3(1.0f, 3.47f, 1.2f), panelSize, panelMat, false, false);
            c.log.Add("Light panels: 2 emissive 0.6 x 1.2 panels at x=-1.0 / 1.0, z=1.2");

            // ---- 5. Lights ----
            Transform lights = Group(c.polish, "Lights");
            Light key = DirLight(c, "Polish Key", new Vector3(55f, 200f, 0f), new Color(1f, 0.93f, 0.85f), 0.9f, true);
            Light dlL = PointLight(c, "Downlight L", new Vector3(-1.0f, 3.35f, 1.2f), new Color(1f, 0.93f, 0.82f), 0.8f, 5f);
            Light dlR = PointLight(c, "Downlight R", new Vector3(1.0f, 3.35f, 1.2f), new Color(1f, 0.93f, 0.82f), 0.8f, 5f);
            if (key != null) key.transform.SetParent(lights, true);
            if (dlL != null) dlL.transform.SetParent(lights, true);
            if (dlR != null) dlR.transform.SetParent(lights, true);

            DisableChild(c, "Lighting/Key Light");
            SetLight(c, "Lighting/Fill Light", null, new Vector3(25f, -90f, 0f), null, 0.25f, null);
            DisableChild(c, "Lighting/Rim Light");
            SetLight(c, "Staging/Connection Glow", null, null, null, 0.9f, null);
            c.log.Add("Lights: Polish Key (55,200,0) 0.9 soft + 2 downlights 0.8/5m; Key Light + Rim Light off, Fill 0.25, Connection Glow 0.9");

            // ---- 6. Ambient ----
            SetAmbient(new Color(0.36f, 0.34f, 0.32f), new Color(0.30f, 0.28f, 0.26f), new Color(0.12f, 0.11f, 0.10f));
            c.log.Add("Ambient: trilight warm-neutral, fog off");

            // ---- 7. Environment fit ----
            DisableChild(c, "Environment/Floor Apron");
            FitProbe(c, interior);
            ShrinkTeleportFloor(c, interior);
            MoveHotspot(c, 4, new Vector3(-1.5f, 0f, 2.0f));
            c.log.Add("Env: Floor Apron off, probe + teleport floor fit to interior, hotspot 4 -> (-1.5, 0, 2.0)");

            // ---- 8. Grounding ----
            Transform bench = c.root != null ? c.root.Find("teal_bench_0") : null;
            if (bench != null)
            {
                EnsureContactShadow(c, bench, 0f);
                c.log.Add("Grounding: contact shadow ensured on teal_bench_0");
            }
            else
            {
                c.log.Add("Grounding: teal_bench_0 not found, skipped");
            }
        }
    }
}
