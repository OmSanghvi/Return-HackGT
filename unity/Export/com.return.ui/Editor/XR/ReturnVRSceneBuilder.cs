using System.IO;
using Return.UI.XR;
using Return.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.UI;

namespace Return.UI.XR.Editor
{
    /// <summary>Builds Assets/Scenes/ReturnHub.unity: the XRI hands+controllers rig, an XR UI event system, the device simulator (editor only) and the Return hub.</summary>
    public static class ReturnVRSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/ReturnHub.unity";

        static string FindPrefab(string name)
        {
            foreach (var guid in AssetDatabase.FindAssets(name + " t:prefab"))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (Path.GetFileNameWithoutExtension(path) == name && path.StartsWith("Assets/")) return path;
            }
            return null;
        }

        /// <summary>The scene needs the XR Interaction Toolkit's Hands Interaction Demo rig and Device Simulator. Imports those samples.</summary>
        [MenuItem("Return/Import XRI Samples")]
        public static void ImportSamples()
        {
            foreach (var pkg in UnityEditor.PackageManager.PackageInfo.GetAllRegisteredPackages())
            {
                if (pkg.name != "com.unity.xr.interaction.toolkit") continue;
                foreach (var s in UnityEditor.PackageManager.UI.Sample.FindByPackage(pkg.name, pkg.version))
                    if (s.displayName.Contains("Starter Assets") || s.displayName.Contains("Hands Interaction") || s.displayName.Contains("Device Simulator"))
                        s.Import(UnityEditor.PackageManager.UI.Sample.ImportOptions.OverridePreviousImports);
            }
            AssetDatabase.Refresh();
        }

        [MenuItem("Return/Build VR Hub Scene")]
        public static void Build()
        {
            var RigPath = FindPrefab("XR Origin Hands (XR Rig)");
            var SimPath = FindPrefab("XR Device Simulator");
            if (RigPath == null) { Debug.LogError("Return: XR rig prefab not found. Run Return > Import XRI Samples first (Starter Assets and Hands Interaction Demo)."); return; }
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var manager = new GameObject("XR Interaction Manager").AddComponent<XRInteractionManager>();

            var es = new GameObject("EventSystem"); es.AddComponent<UnityEngine.EventSystems.EventSystem>(); es.AddComponent<XRUIInputModule>();

            var rigPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(RigPath);
            var rig = (GameObject)PrefabUtility.InstantiatePrefab(rigPrefab);
            rig.name = "XR Origin (Return)";
            var cam = rig.GetComponentInChildren<Camera>(true);
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.04f, 0.05f, 0.12f); cam.nearClipPlane = 0.05f; cam.farClipPlane = 200f;
            cam.gameObject.tag = "MainCamera";

            // wrist anchor: left controller, else left hand
            var anchorGo = new GameObject("Left Wrist Anchor"); anchorGo.transform.SetParent(cam.transform.parent, false);
            var anchor = anchorGo.AddComponent<XRWristAnchor>();
            anchor.controller = Find(rig.transform, "Left Controller"); anchor.hand = Find(rig.transform, "Left Hand");

            var hub = new GameObject("Return Hub").AddComponent<HubApp>();
            hub.head = cam.transform; hub.leftHand = anchorGo.transform; hub.fadeSeconds = 1.1f;

            if (SimPath != null)
            {
                var sim = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(SimPath));
                sim.tag = "EditorOnly"; // stripped from player builds
            }

            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, ScenePath);
            var list = new System.Collections.Generic.List<EditorBuildSettingsScene> { new EditorBuildSettingsScene(ScenePath, true) };
            foreach (var s in EditorBuildSettings.scenes) if (s.path != ScenePath) list.Add(s);
            EditorBuildSettings.scenes = list.ToArray();
            Debug.Log("Return: VR hub scene built at " + ScenePath);
        }

        static Transform Find(Transform root, string name)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true)) if (t.name == name) return t;
            return null;
        }
    }
}
