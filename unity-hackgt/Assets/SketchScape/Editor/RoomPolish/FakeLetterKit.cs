// SketchScape FakeLetterKit — Editor-only builder for a demo envelope on a stand (FakeLetter).
// Root "Fake Letter" sits on the floor at floorPos, yawed by yawDeg; at yaw 0 the envelope faces -Z
// (towards a viewer at smaller z). Materials are saved as assets in matFolder (idempotent).
using System;
using TMPro;
using UnityEditor;
using UnityEngine;

namespace SketchScape
{
    internal static class FakeLetterKit
    {
        const string FontPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";

        internal static GameObject Build(Transform parent, string matFolder, Vector3 floorPos, float yawDeg, string heading, string body)
        {
            var font = LoadFont();
            var wood = Mat(matFolder, "Wood", new Color(0.34f, 0.22f, 0.13f), 0.3f);
            var cream = Mat(matFolder, "Cream", new Color(0.94f, 0.88f, 0.75f), 0.08f);
            var creamDark = Mat(matFolder, "CreamDark", new Color(0.86f, 0.79f, 0.64f), 0.08f);
            var wax = Mat(matFolder, "Wax", new Color(0.75f, 0.12f, 0.10f), 0.5f);
            var paper = Mat(matFolder, "Paper", new Color(0.97f, 0.95f, 0.90f), 0.1f);
            var ink = new Color(0.18f, 0.16f, 0.22f);
            var creamWhite = new Color(0.95f, 0.90f, 0.80f);

            var root = new GameObject("Fake Letter");
            root.transform.SetParent(parent, false);
            root.transform.position = floorPos;
            root.transform.rotation = Quaternion.Euler(0f, yawDeg, 0f);
            root.SetActive(false);   // interactables are injected before anything wakes up
            var rt = root.transform;

            // 1. Stand: a slim column with a small top board (no colliders: Box adds none).
            SharedShapes.Box(rt, "Column", new Vector3(0f, 0.475f, 0f), new Vector3(0.08f, 0.95f, 0.08f), wood);
            SharedShapes.Box(rt, "Top", new Vector3(0f, 0.96f, 0f), new Vector3(0.34f, 0.02f, 0.26f), wood);

            // 2. Envelope, leaning back like a card on a stand. Its transform is the button face
            //    (local z = 0, facing -Z); the paper box sits behind that plane at z = +0.006.
            const float w = 0.24f, h = 0.16f;
            var envelopeGo = SharedShapes.Node(rt, "Envelope", new Vector3(0f, 1.05f, -0.02f), Quaternion.Euler(60f, 0f, 0f));
            var envelope = envelopeGo.transform;
            var bodyNode = SharedShapes.Node(envelope, "Body", Vector3.zero, Quaternion.identity).transform;
            SharedShapes.Box(bodyNode, "Paper", new Vector3(0f, 0f, 0.006f), new Vector3(w, h, 0.012f), cream);
            var pivot = SharedShapes.Node(bodyNode, "Flap Pivot", new Vector3(0f, h / 2f, -0.0004f), Quaternion.identity).transform;
            SharedShapes.MeshNode(pivot, "Flap", SharedShapes.Flap, Vector3.zero, Quaternion.identity, new Vector3(w, h * 0.58f, 1f), creamDark);
            SharedShapes.MeshNode(bodyNode, "Seal", SharedShapes.Cylinder, new Vector3(0f, h / 2f - h * 0.58f + 0.008f, -0.003f),
                                  Quaternion.Euler(90f, 0f, 0f), new Vector3(0.035f, 0.002f, 0.035f), wax);

            // 3. Poke / ray button on the envelope node. The whole body (paper, flap, seal) presses inward.
            var button = envelopeGo.AddComponent<SharedPokeButton>();
            button.size = new Vector2(0.26f, 0.18f);
            button.visual = bodyNode;
            button.payload = "fake";
            button.pressDepth = 0.006f;
            button.Setup();

            // 4. Hint under the top board, facing -Z (identity rotation reads correctly from -Z, as the room layer does).
            SharedShapes.Text(rt, "Hint", font, "Pinch or poke to read", new Vector3(0f, 0.86f, -0.14f),
                              new Vector2(0.4f, 0.04f), 0.03f, creamWhite, TextAlignmentOptions.Center, true);

            // 5. Page root (moved in front of the player at runtime) holding the letter page.
            var pageRootGo = SharedShapes.Node(rt, "Page Root", Vector3.zero, Quaternion.identity);
            var page = pageRootGo.AddComponent<SharedLetterPage>();
            var sheet = SharedShapes.Node(pageRootGo.transform, "Sheet", Vector3.zero, Quaternion.Euler(8f, 0f, 0f)).transform;
            page.sheet = sheet;
            page.paper = SharedShapes.Box(sheet, "Paper", new Vector3(0f, 0f, 0.0015f), new Vector3(0.42f, 0.55f, 0.003f), paper).transform;
            page.title = SharedShapes.Text(sheet, "Title", font, "", new Vector3(0f, 0.27f, -0.0015f), new Vector2(0.38f, 0.04f), 0.02f,
                                           ink, TextAlignmentOptions.Center, true, FontStyles.Bold);
            page.bodyText = SharedShapes.Text(sheet, "Body", font, "", new Vector3(0f, 0f, -0.0015f), new Vector2(0.37f, 0.46f), 0.022f,
                                              ink, TextAlignmentOptions.TopLeft, true);
            page.picture = null;
            page.stand = null;
            page.width = 0.42f;
            sheet.gameObject.SetActive(false);

            // 6. The behaviour that ties it together.
            var fake = root.AddComponent<FakeLetter>();
            fake.letterId = "fake";
            fake.heading = heading ?? "";
            fake.body = body ?? "";
            fake.button = button;
            fake.page = page;
            fake.pageRoot = pageRootGo.transform;
            fake.envelope = envelope;

            root.SetActive(true);
            return root;
        }

        // ------------------------------------------------------------------

        static TMP_FontAsset LoadFont()
        {
            var font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(FontPath);
            if (font == null)
            {
                try { font = TMP_Settings.defaultFontAsset; } catch (Exception) { }
            }
            return font;
        }

        /// <summary>Standard material saved at matFolder/FakeLetter_&lt;name&gt;.mat; loaded and updated if it already exists.</summary>
        static Material Mat(string folder, string name, Color color, float gloss)
        {
            var shader = Shader.Find("Standard");
            string dir = string.IsNullOrEmpty(folder) ? "Assets" : folder.Replace('\\', '/').TrimEnd('/');
            string path = dir + "/FakeLetter_" + name + ".mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (m == null)
            {
                EnsureFolder(dir);
                m = new Material(shader) { name = "FakeLetter_" + name };
                AssetDatabase.CreateAsset(m, path);
            }
            else if (shader != null && m.shader != shader)
            {
                m.shader = shader;
            }
            m.color = color;
            if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", gloss);
            EditorUtility.SetDirty(m);
            return m;
        }

        static void EnsureFolder(string dir)
        {
            if (AssetDatabase.IsValidFolder(dir)) return;
            var parts = dir.Split('/');
            string cur = parts[0];
            for (int i = 1; i < parts.Length; i++)
            {
                string next = cur + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next)) AssetDatabase.CreateFolder(cur, parts[i]);
                cur = next;
            }
        }
    }
}
