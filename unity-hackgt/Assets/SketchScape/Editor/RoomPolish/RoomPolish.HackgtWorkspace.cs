using System.Collections.Generic;
using UnityEngine;
using UnityEditor;

namespace SketchScape
{
    public static partial class RoomPolish
    {
        /// <summary>
        /// Per-room polish for hackgt_workspace.unity (root SharedRoom_hackgt_workspace).
        /// Builds a simple architectural shell around the classroom splat, fixes the
        /// lighting rig, grounds the floating backpack and tidies the teleport layout.
        /// Everything created here lives under c.polish; all positions are absolute (idempotent).
        /// </summary>
        internal static void PolishHackgtWorkspace(Ctx c)
        {
            // ---- Interior bounds (metres): x -1.95..2.8, y 0..2.92, z -1.5..5.65 ----
            const float xMin = -1.95f, xMax = 2.8f;
            const float yMin = 0f, yMax = 2.92f;
            const float zMin = -1.5f, zMax = 5.65f;
            const float t = 0.15f;          // wall / ceiling thickness
            const float ht = t * 0.5f;      // half thickness

            float w = xMax - xMin;          // 4.75
            float h = yMax - yMin;          // 2.92
            float d = zMax - zMin;          // 7.15
            float cx = (xMin + xMax) * 0.5f;    // 0.425
            float cy = (yMin + yMax) * 0.5f;    // 1.46
            float cz = (zMin + zMax) * 0.5f;    // 2.075

            Bounds interior = new Bounds(new Vector3(cx, cy, cz), new Vector3(w, h, d));

            // ---- 1. Shell ----
            Transform shell = Group(c.polish, "Shell");

            Material wallBack = Mat(c, "WallBack", new Color(0.39f, 0.40f, 0.34f), 0.06f);
            Material wallLight = Mat(c, "WallLight", new Color(0.80f, 0.79f, 0.78f), 0.06f);
            Material wallGray = Mat(c, "WallGray", new Color(0.58f, 0.58f, 0.58f), 0.06f);
            Material ceilingMat = Mat(c, "Ceiling", new Color(0.49f, 0.49f, 0.47f), 0.04f);

            // North / South walls span the full width plus wall thickness so the corners close.
            Vector3 nsSize = new Vector3(w + 2f * t, h, t);
            Box(shell, "Wall North", new Vector3(cx, cy, zMax + ht), nsSize, wallBack, true, false);
            Box(shell, "Wall South", new Vector3(cx, cy, zMin - ht), nsSize, wallLight, true, false);

            // East / West walls run the full interior depth (corners are covered by N/S walls).
            Vector3 ewSize = new Vector3(t, h, d);
            Box(shell, "Wall West", new Vector3(xMin - ht, cy, cz), ewSize, wallLight, true, false);
            Box(shell, "Wall East", new Vector3(xMax + ht, cy, cz), ewSize, wallGray, true, false);

            // Ceiling slab sits on top of the walls: full x/z plus thickness, flat colour (scan has its own ceiling).
            Box(shell, "Ceiling", new Vector3(cx, yMax + ht, cz), new Vector3(w + 2f * t, t, d + 2f * t), ceilingMat, true, false);
            c.log.Add("Shell: 4 walls + ceiling around interior x[-1.95,2.8] y[0,2.92] z[-1.5,5.65], t=0.15");

            // ---- 2. Baseboards (0.10 tall, 0.02 thick, flush to the inside face of each wall) ----
            Material baseboard = Mat(c, "Baseboard", new Color(0.12f, 0.12f, 0.12f), 0.2f);
            const float bbH = 0.10f, bbT = 0.02f;
            float bbY = yMin + bbH * 0.5f;
            Box(shell, "Baseboard North", new Vector3(cx, bbY, zMax - bbT * 0.5f), new Vector3(w, bbH, bbT), baseboard, false, false);
            Box(shell, "Baseboard South", new Vector3(cx, bbY, zMin + bbT * 0.5f), new Vector3(w, bbH, bbT), baseboard, false, false);
            Box(shell, "Baseboard West", new Vector3(xMin + bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, d), baseboard, false, false);
            Box(shell, "Baseboard East", new Vector3(xMax - bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, d), baseboard, false, false);
            c.log.Add("Baseboards on all four walls (0.10 x 0.02)");

            // ---- 3. Ceiling light panels (emissive, no collider) ----
            Material lightPanel = Mat(c, "LightPanel", new Color(0.95f, 0.95f, 0.92f), 0.2f, null, null, new Color(1.5f, 1.47f, 1.35f));
            Vector3 panelSize = new Vector3(0.6f, 0.03f, 1.2f);
            Box(shell, "Light Panel Front", new Vector3(-0.6f, 2.90f, 1.6f), panelSize, lightPanel, false, false);
            Box(shell, "Light Panel Back", new Vector3(1.4f, 2.90f, 3.6f), panelSize, lightPanel, false, false);
            c.log.Add("Ceiling light panels at (-0.6,2.90,1.6) and (1.4,2.90,3.6)");

            // ---- 4. Lights ----
            SetLight(c, "Lighting/Key Light", null, null, null, 0.9f, null);
            SetLight(c, "Lighting/Fill Light", null, null, null, 0.3f, null);
            DisableChild(c, "Lighting/Rim Light");
            SetLight(c, "Lighting/Practical ceiling lamps", new Vector3(0.42f, 2.75f, 2.72f), null, new Color(1f, 0.93f, 0.82f), 0.9f, 5f);
            SetLight(c, "Staging/Connection Glow", null, null, null, 0.9f, null);

            Transform lights = Group(c.polish, "Lights");
            Light downFront = PointLight(c, "Downlight Front", new Vector3(-0.6f, 2.75f, 1.6f), new Color(1f, 0.95f, 0.88f), 0.7f, 4.5f);
            if (downFront != null && downFront.transform.parent != lights)
                downFront.transform.SetParent(lights, true);
            c.log.Add("Lights: Key 0.9, Fill 0.3, Rim off, Practical moved to ceiling (warm 0.9/r5), Connection Glow 0.9, +Downlight Front");

            // ---- 5. Ambient ----
            SetAmbient(new Color(0.49f, 0.49f, 0.47f), new Color(0.55f, 0.54f, 0.52f), new Color(0.20f, 0.19f, 0.19f));
            c.log.Add("Ambient: trilight set to ceiling/wall/floor scan tones");

            // ---- 6. Backpack: ground it and give it a contact shadow ----
            Transform backpack = c.root != null ? c.root.Find("backpack_1") : null;
            if (backpack != null)
            {
                RestOnFloor(backpack, 0f);
                EnsureContactShadow(c, backpack, 0f);
                c.log.Add("backpack_1 rested on floor + contact shadow");
            }
            else
            {
                c.log.Add("WARN: backpack_1 not found under root");
            }

            // ---- 7. Environment tidy-up ----
            DisableChild(c, "Environment/Floor Apron");
            FitProbe(c, interior);
            ShrinkTeleportFloor(c, interior);
            MoveHotspot(c, 7, new Vector3(2.3f, 0f, 2.72f));    // was x=2.96, inside the east wall
            MoveHotspot(c, 6, new Vector3(-1.5f, 0f, 2.72f));   // was x=-2.11, inside the west wall
            c.log.Add("Floor Apron off, probe + teleport floor fit to interior, hotspots 6/7 pulled inside the walls");
        }
    }
}
