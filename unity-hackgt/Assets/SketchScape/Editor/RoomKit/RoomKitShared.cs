// SketchScape RoomKit — the "Shared Room" rig (Return-HackGT docs/WEB_TO_QUEST_PIPELINE.md sections 3-5).
// Canonical source: Return-HackGT/unity-hackgt/. Installed into HackGTUnity by
// scripts/install_hackgt_roomkit.py; edit the repo copy, not the installed one.
//
// When the spec's shared block is enabled, RoomKit.Build calls RoomKitShared.Build, which adds
//   Shared Room (at the spawn, facing the spawn yaw)
//     SharedRoomSession  - config from the spec; live view / snapshot / letters at runtime
//     SharedRoomLayer    - asset_id -> object map, materials, font; draws notes, envelopes, tags
//     Account Switcher   - AccountSwitcher pedestal with one poke/ray badge per account
//     Letters Desk       - envelopes tray + the page that unfolds from an opened letter
//     Notes Board Anchor - where notes without a separate object are pinned
// and, when the runner's snapshot (Resources/SharedSnapshots/<project_id>.json) is already
// there, draws the default account's view into the scene so the saved room shows it at once.
using System;
using System.Collections.Generic;
using System.IO;
using TMPro;
using UnityEditor;
using UnityEngine;

namespace SketchScape
{
    public static class RoomKitShared
    {
        public const string SnapshotFolder = "Assets/SketchScape/Resources";
        const string TmpFontPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";

        /// <summary>Builds the rig; returns the report token ("on(1a2b3c4d)" / "off").</summary>
        public static string Build(RoomSpec spec, GameObject root, List<string> mapAssets, List<string> mapIds, List<Transform> mapObjects,
                                   string genFolder, List<string> failures, List<string> notes)
        {
            var sh = spec.shared;
            if (sh == null || !sh.enabled) return "off";
            if (!SafeId(sh.project_id)) { failures.Add("shared: invalid project_id '" + sh.project_id + "'"); return "off(invalid project_id)"; }
            string pid8 = sh.project_id.Length > 8 ? sh.project_id.Substring(0, 8) : sh.project_id;
            try
            {
                string tmpNote = EnsureTmpEssentials();
                if (tmpNote != null) notes.Add(tmpNote);
                var font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(TmpFontPath);
                if (font == null) { try { font = TMP_Settings.defaultFontAsset; } catch (Exception) { } }
                if (font == null) failures.Add("shared: no TextMeshPro font (import TMP Essential Resources)");

                float floorY = spec.environment.floor.height;
                var spawn = RoomKit.V3(spec.player.spawn);
                var spawnFloor = new Vector3(spawn.x, floorY, spawn.z);
                float yaw = spec.player.yaw;

                var rig = new GameObject("Shared Room");
                rig.transform.SetParent(root.transform, false);
                rig.transform.position = spawnFloor;
                rig.transform.rotation = Quaternion.Euler(0f, yaw, 0f);

                var session = rig.AddComponent<SharedRoomSession>();
                session.config = new SharedRoomConfig
                {
                    enabled = true,
                    project_id = sh.project_id,
                    api_base = string.IsNullOrEmpty(sh.api_base) ? "https://returnweb-hazel.vercel.app/api" : sh.api_base.TrimEnd('/'),
                    accounts = sh.accounts.Length > 0 ? (string[])sh.accounts.Clone() : new[] { "demo-alice", "demo-bob" },
                    labels = sh.labels.Length > 0 ? (string[])sh.labels.Clone() : new[] { "Account 1", "Account 2" },
                    default_account = sh.default_account,
                    snapshot_resource = string.IsNullOrEmpty(sh.snapshot_resource) ? "SharedSnapshots/" + sh.project_id : sh.snapshot_resource,
                };
                if (string.IsNullOrEmpty(session.config.default_account)) session.config.default_account = session.config.accounts[0];

                var look = new SharedLayerLook
                {
                    font = font,
                    paper = Mat(genFolder, "SharedPaper", "Standard", SharedPalette.Paper, 0.1f),
                    wood = Mat(genFolder, "SharedWood", "Standard", new Color(0.34f, 0.22f, 0.13f), 0.3f),
                    color = Mat(genFolder, "SharedColor", "Standard", Color.white, 0.35f),
                    envelope = Mat(genFolder, "SharedEnvelope", "Standard", new Color(0.94f, 0.88f, 0.75f), 0.08f),
                    page = Mat(genFolder, "SharedPage", "Unlit/Texture", Color.white, 0f),
                    glow = RoomKit.GlowMaterial(genFolder, "SharedGlow", true, RoomKit.RadialTexture("_soft_dot", 1.4f)),
                };

                var layer = rig.AddComponent<SharedRoomLayer>();
                layer.session = session;
                layer.look = look;
                layer.spawn = spawnFloor;
                layer.floorY = floorY;
                layer.eyeHeight = spec.player.eye_height > 0f ? spec.player.eye_height : 1.6f;
                layer.mapAssetIds = mapAssets.ToArray();
                layer.mapObjectIds = mapIds.ToArray();
                layer.mapObjects = mapObjects.ToArray();

                // Anchors around the spawn, clear of the room's separate objects.
                var blockers = new List<Bounds>();
                foreach (var t in mapObjects)
                {
                    var box = t != null ? t.GetComponent<BoxCollider>() : null;
                    if (box != null) blockers.Add(RoomKit.TransformBounds(Matrix4x4.TRS(t.position, t.rotation, Vector3.one), new Bounds(box.center, box.size)));
                }
                var frame = Quaternion.Euler(0f, yaw, 0f);
                var taken = new List<Vector4>();
                var switcherPos = Pick(spawnFloor, frame, new[] { new Vector2(0.5f, 0.45f), new Vector2(0.62f, 0.12f), new Vector2(0.45f, 0.8f), new Vector2(0.85f, 0.45f), new Vector2(0.6f, -0.3f) }, 0.2f, blockers, taken);
                var deskPos = Pick(spawnFloor, frame, new[] { new Vector2(-0.62f, 0.5f), new Vector2(-0.78f, 0.1f), new Vector2(-0.6f, 0.9f), new Vector2(-1.0f, 0.45f), new Vector2(-0.7f, -0.45f) }, 0.5f, blockers, taken);
                var boardPos = Pick(spawnFloor, frame, new[] { new Vector2(-1.15f, -0.3f), new Vector2(1.15f, -0.35f), new Vector2(-1.3f, 0.35f), new Vector2(1.3f, 0.35f), new Vector2(0f, -1.1f) }, 0.45f, blockers, taken);

                var switcherGo = Anchor(rig.transform, "Account Switcher", switcherPos, spawnFloor);
                var switcher = switcherGo.AddComponent<AccountSwitcher>();
                layer.deskAnchor = Anchor(rig.transform, "Letters Desk", deskPos, spawnFloor).transform;
                layer.boardAnchor = Anchor(rig.transform, "Notes Board Anchor", boardPos, spawnFloor).transform;

                string preview;
                SharedLayerLook.TintFactory = (baseMat, c) => TintAsset(genFolder, baseMat, c);
                try
                {
                    switcher.Build(session, look);
                    layer.BuildFurniture();
                    preview = Preview(session, layer, switcher);
                }
                finally { SharedLayerLook.TintFactory = null; }
                notes.Add("shared: " + preview);
                return "on(" + pid8 + ")";
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                failures.Add("shared layer: " + e.GetType().Name + ": " + RoomKitWeb.Short(e.Message));
                return "failed(" + pid8 + ")";
            }
        }

        /// <summary>Draws the snapshot's default-account view into the scene (the runtime redraws it live).</summary>
        static string Preview(SharedRoomSession session, SharedRoomLayer layer, AccountSwitcher switcher)
        {
            string path = SnapshotFolder + "/" + session.config.snapshot_resource + ".json";
            var asset = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            if (asset == null)
            {
                layer.Render(null);
                return "no snapshot at " + path + " yet (the headset reads the live view)";
            }
            SharedSnapshot snap;
            try { snap = JsonUtility.FromJson<SharedSnapshot>(asset.text); }
            catch (Exception e) { layer.Render(null); return "snapshot unreadable: " + RoomKitWeb.Short(e.Message); }
            var view = snap != null ? snap.ViewFor(session.config.default_account) : null;
            if (view == null) { layer.Render(null); return "snapshot has no view for " + session.config.default_account; }
            view.Normalize();
            session.UsePreview(view);
            layer.Render(view);
            switcher.Refresh();
            return "preview as " + session.LabelFor(session.config.default_account) + ": " + layer.LastRender;
        }

        static GameObject Anchor(Transform rig, string name, Vector3 world, Vector3 spawnFloor)
        {
            var go = new GameObject(name);
            go.transform.SetParent(rig, false);
            go.transform.position = world;
            var away = world - spawnFloor;
            away.y = 0f;
            go.transform.rotation = away.sqrMagnitude > 1e-4f ? Quaternion.LookRotation(away.normalized, Vector3.up) : rig.rotation;
            return go;
        }

        /// <summary>First candidate (lateral, forward from the spawn) whose footprint misses the objects and earlier picks.</summary>
        static Vector3 Pick(Vector3 spawnFloor, Quaternion frame, Vector2[] candidates, float radius, List<Bounds> blockers, List<Vector4> taken)
        {
            foreach (var c in candidates)
            {
                var p = spawnFloor + frame * new Vector3(c.x, 0f, c.y);
                bool clear = true;
                foreach (var b in blockers)
                {
                    float dx = Mathf.Max(b.min.x - p.x, 0f, p.x - b.max.x);
                    float dz = Mathf.Max(b.min.z - p.z, 0f, p.z - b.max.z);
                    if (dx * dx + dz * dz < (radius + 0.08f) * (radius + 0.08f)) { clear = false; break; }
                }
                if (clear)
                    foreach (var t in taken)
                        if (new Vector2(t.x - p.x, t.z - p.z).magnitude < radius + t.w + 0.1f) { clear = false; break; }
                if (!clear) continue;
                taken.Add(new Vector4(p.x, p.y, p.z, radius));
                return p;
            }
            var first = spawnFloor + frame * new Vector3(candidates[0].x, 0f, candidates[0].y);
            taken.Add(new Vector4(first.x, first.y, first.z, radius));
            return first;
        }

        static Material Mat(string genFolder, string name, string shader, Color c, float gloss)
        {
            var sh = Shader.Find(shader) ?? Shader.Find("Standard");
            var m = new Material(sh) { name = name, color = c };
            if (m.HasProperty("_Glossiness")) m.SetFloat("_Glossiness", gloss);
            AssetDatabase.CreateAsset(m, genFolder + "/" + name + ".mat");
            return m;
        }

        static Material TintAsset(string genFolder, Material baseMat, Color c)
        {
            string path = genFolder + "/" + baseMat.name + "_" + ColorUtility.ToHtmlStringRGBA(c) + ".mat";
            var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (existing != null && existing.shader == baseMat.shader) { existing.color = c; return existing; }
            var m = new Material(baseMat) { name = Path.GetFileNameWithoutExtension(path), color = c };
            AssetDatabase.CreateAsset(m, path);
            return m;
        }

        /// <summary>TextMeshPro needs its essential resources (TMP Settings, default font) in the project.</summary>
        static string EnsureTmpEssentials()
        {
            if (Resources.Load<TMP_Settings>("TMP Settings") != null && AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(TmpFontPath) != null) return null;
            string pkg = Path.GetFullPath("Packages/com.unity.ugui/Package Resources/TMP Essential Resources.unitypackage");
            if (!File.Exists(pkg)) return "TMP Essential Resources package not found";
#pragma warning disable CS0618 // ImportPackage is obsolete in Unity 6.6 but still works (and exists in older 6.x)
            AssetDatabase.ImportPackage(pkg, false);
#pragma warning restore CS0618
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            // The import finishes on a later editor tick: this build's text may lack its font; rebuild once.
            return Resources.Load<TMP_Settings>("TMP Settings") != null ? "imported TMP Essential Resources" : "TMP Essential Resources import started (rebuild the room once it finishes)";
        }

        static bool SafeId(string id)
        {
            if (string.IsNullOrEmpty(id) || id.Length > 64) return false;
            foreach (char ch in id) if (!(char.IsLetterOrDigit(ch) || ch == '_' || ch == '-')) return false;
            return true;
        }
    }
}
