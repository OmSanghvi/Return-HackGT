using System.Collections.Generic;
using UnityEngine;
using UnityEditor;

namespace SketchScape
{
    public static partial class RoomPolish
    {
        // hackathon_spot.unity - the photo reconstruction flattened both white tables into 4 cm slabs on the
        // floor. We restage: lift the scan + props by +0.72 (absolute Y writes, idempotent) so the slabs read as
        // table tops, then build a real table underneath and a simple shell around the room.
        internal static void PolishHackathonSpot(Ctx c)
        {
            // ------------------------------------------------------------------ 1. Restage (absolute lifts)
            HsSetY(c, "Photo Scene", 1.63f);
            HsSetY(c, "left_white_table_0", 0.56f);
            HsSetY(c, "right_white_table_4", 0.42f);
            HsSetY(c, "Staging", 0.72f);
            HsSetY(c, "Particles", 0.72f);
            HsSetY(c, "white_board_5", 0.72f);

            HsRest(c, "middle_black_laptop_2", 0.69f);
            HsRest(c, "right_black_laptop_1", 0.69f);
            HsRest(c, "right_green_chair_3", 0f);

            // Contact shadows ride with their prop; pin them just above the surface they now sit on.
            HsContactShadow(c, "middle_black_laptop_2", 0.694f);
            HsContactShadow(c, "right_black_laptop_1", 0.694f);
            HsContactShadow(c, "white_board_5", 0.694f);
            HsContactShadow(c, "left_white_table_0", 0.694f);
            HsContactShadow(c, "right_white_table_4", 0.694f);
            HsContactShadow(c, "right_green_chair_3", 0.004f);

            // ------------------------------------------------------------------ 2. Real table under the slabs
            var table = Group(c.polish, "Table");
            var matTop = Mat(c, "TableTop", new Color(0.85f, 0.85f, 0.83f), 0.3f);
            var matLeg = Mat(c, "TableLeg", new Color(0.15f, 0.15f, 0.16f), 0.4f);

            Box(table, "Table Top", new Vector3(-0.15f, 0.59f, 1.775f), new Vector3(2.5f, 0.06f, 2.55f), matTop, collider: true, castShadows: true);

            float[] legX = { -1.32f, 1.02f };
            float[] legZ = { 0.58f, 2.97f };
            int legIndex = 0;
            for (int ix = 0; ix < legX.Length; ix++)
            {
                for (int iz = 0; iz < legZ.Length; iz++)
                {
                    Box(table, "Table Leg " + legIndex, new Vector3(legX[ix], 0.28f, legZ[iz]), new Vector3(0.05f, 0.56f, 0.05f), matLeg, collider: false);
                    legIndex++;
                }
            }
            Box(table, "Table Skirt", new Vector3(-0.15f, 0.53f, 0.515f), new Vector3(2.5f, 0.08f, 0.03f), matLeg, collider: false);
            c.log.Add("[HackathonSpot] Table built: top 2.5x2.55 @ y0.59, 4 legs, front skirt");

            // ------------------------------------------------------------------ 3. Shell (walls + ceiling)
            const float xMin = -2.9f, xMax = 2.9f;
            const float yMin = 0f, yMax = 3.0f;
            const float zMin = -2.2f, zMax = 3.6f;
            const float wallT = 0.15f;
            const float halfT = wallT * 0.5f;

            float width = xMax - xMin;   // 5.8
            float depth = zMax - zMin;   // 5.8
            float height = yMax - yMin;  // 3.0
            float cx = (xMin + xMax) * 0.5f;   // 0
            float cz = (zMin + zMax) * 0.5f;   // 0.7
            var interior = new Bounds(new Vector3(cx, (yMin + yMax) * 0.5f, cz), new Vector3(width, height, depth));

            var shell = Group(c.polish, "Shell");
            var matWall = Mat(c, "Wall", new Color(0.73f, 0.72f, 0.68f), 0.06f);
            var matCeiling = Mat(c, "Ceiling", new Color(0.88f, 0.88f, 0.85f), 0.04f, CeilingTiles(), new Vector2(5.8f / 2.4f, 5.8f / 2.4f));

            // Walls run from slightly below the floor to the ceiling plane so no sliver shows at the base.
            const float wallBottom = -0.1f;
            float wallH = yMax - wallBottom;
            float wallCy = (wallBottom + yMax) * 0.5f;

            // N/S walls are extended by one wall thickness each side so the corners close.
            Box(shell, "Wall North", new Vector3(cx, wallCy, zMax + halfT), new Vector3(width + 2f * wallT, wallH, wallT), matWall, collider: true, castShadows: false);
            Box(shell, "Wall South", new Vector3(cx, wallCy, zMin - halfT), new Vector3(width + 2f * wallT, wallH, wallT), matWall, collider: true, castShadows: false);
            Box(shell, "Wall East", new Vector3(xMax + halfT, wallCy, cz), new Vector3(wallT, wallH, depth), matWall, collider: true, castShadows: false);
            Box(shell, "Wall West", new Vector3(xMin - halfT, wallCy, cz), new Vector3(wallT, wallH, depth), matWall, collider: true, castShadows: false);
            Box(shell, "Ceiling", new Vector3(cx, yMax + halfT, cz), new Vector3(width + 2f * wallT, wallT, depth + 2f * wallT), matCeiling, collider: true, castShadows: false);
            c.log.Add("[HackathonSpot] Shell: interior x " + xMin + ".." + xMax + ", z " + zMin + ".." + zMax + ", ceiling y " + yMax);

            // ------------------------------------------------------------------ 4. Baseboards
            const float bbH = 0.10f;
            const float bbT = 0.02f;
            var matBase = Mat(c, "Baseboard", new Color(0.10f, 0.10f, 0.10f), 0.2f);
            var baseboards = Group(c.polish, "Baseboards");
            float bbY = yMin + bbH * 0.5f;
            Box(baseboards, "Baseboard North", new Vector3(cx, bbY, zMax - bbT * 0.5f), new Vector3(width, bbH, bbT), matBase, collider: false);
            Box(baseboards, "Baseboard South", new Vector3(cx, bbY, zMin + bbT * 0.5f), new Vector3(width, bbH, bbT), matBase, collider: false);
            Box(baseboards, "Baseboard East", new Vector3(xMax - bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, depth), matBase, collider: false);
            Box(baseboards, "Baseboard West", new Vector3(xMin + bbT * 0.5f, bbY, cz), new Vector3(bbT, bbH, depth), matBase, collider: false);
            c.log.Add("[HackathonSpot] Baseboards on 4 walls");

            // ------------------------------------------------------------------ 5. Ceiling light panels
            var panels = Group(c.polish, "Light Panels");
            var matPanel = Mat(c, "LightPanel", new Color(0.95f, 0.95f, 0.92f), 0.2f, null, null, new Color(1.6f, 1.55f, 1.42f));
            Box(panels, "Light Panel West", new Vector3(-1.2f, 2.98f, 1.4f), new Vector3(0.6f, 0.03f, 1.2f), matPanel, collider: false);
            Box(panels, "Light Panel East", new Vector3(1.2f, 2.98f, 1.4f), new Vector3(0.6f, 0.03f, 1.2f), matPanel, collider: false);
            c.log.Add("[HackathonSpot] 2 emissive ceiling panels @ y2.98");

            // ------------------------------------------------------------------ 6. Lights
            SetLight(c, "Lighting/Key Light", null, new Vector3(65f, 30f, 0f), null, 0.9f, null);
            SetLight(c, "Lighting/Fill Light", null, null, null, 0.3f, null);
            DisableChild(c, "Lighting/Rim Light");
            SetLight(c, "Lighting/Practical ceiling lamp", new Vector3(-0.04f, 2.85f, 1.43f), null, new Color(1f, 0.93f, 0.82f), 0.9f, 5f);
            SetLight(c, "Staging/Connection Glow", null, null, null, 0.9f, null);
            c.log.Add("[HackathonSpot] Lights: key 0.9 @ (65,30,0), fill 0.3, rim off, practical lamp -> y2.85 0.9 r5, glow 0.9");

            // ------------------------------------------------------------------ 7. Ambient
            SetAmbient(new Color(0.57f, 0.56f, 0.53f), new Color(0.62f, 0.60f, 0.56f), new Color(0.30f, 0.30f, 0.28f));

            // ------------------------------------------------------------------ 8. Environment / teleport
            DisableChild(c, "Environment/Floor Apron");
            FitProbe(c, interior);
            ShrinkTeleportFloor(c, interior);
            // Hotspots 2 and 3 used to be inside the table footprint; park them either side of the spawn.
            MoveHotspot(c, 2, new Vector3(-2.2f, 0f, 0f));
            MoveHotspot(c, 3, new Vector3(2.2f, 0f, 0f));
            c.log.Add("[HackathonSpot] Floor apron off, probe + teleport floor fit to interior, hotspots 2/3 moved out of the table");
        }

        // ---------------------------------------------------------------------- helpers (HackathonSpot only)

        static Transform HsFind(Ctx c, string path)
        {
            var t = c.root != null ? c.root.Find(path) : null;
            if (t == null) c.log.Add("[HackathonSpot] MISSING '" + path + "' - skipped");
            return t;
        }

        static void HsSetY(Ctx c, string path, float y)
        {
            var t = HsFind(c, path);
            if (t == null) return;
            SetWorldY(t, y);
            c.log.Add("[HackathonSpot] " + path + " y -> " + t.position.y.ToString("0.###"));
        }

        static void HsRest(Ctx c, string path, float floorY)
        {
            var t = HsFind(c, path);
            if (t == null) return;
            RestOnFloor(t, floorY);
            c.log.Add("[HackathonSpot] " + path + " rested on y=" + floorY.ToString("0.###") + " (root y " + t.position.y.ToString("0.###") + ")");
        }

        static void HsContactShadow(Ctx c, string path, float y)
        {
            var prop = HsFind(c, path);
            if (prop == null) return;

            Transform shadow = prop.Find("Contact Shadow");
            if (shadow == null)
            {
                // Fallback: nested somewhere under the prop.
                var all = prop.GetComponentsInChildren<Transform>(true);
                for (int i = 0; i < all.Length; i++)
                {
                    if (all[i] != prop && all[i].name == "Contact Shadow") { shadow = all[i]; break; }
                }
            }
            if (shadow == null)
            {
                c.log.Add("[HackathonSpot] " + path + ": no 'Contact Shadow' child found");
                return;
            }
            SetWorldY(shadow, y);
            c.log.Add("[HackathonSpot] " + path + "/Contact Shadow y -> " + shadow.position.y.ToString("0.###"));
        }
    }
}
