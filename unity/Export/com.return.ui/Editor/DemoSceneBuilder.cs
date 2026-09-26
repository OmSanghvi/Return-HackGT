using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Return.UI.Editor
{
    /// <summary>Builds the two sample scenes. Return/Build Demo Scenes, or -executeMethod Return.UI.Editor.DemoSceneBuilder.Build -out DIR.</summary>
    public static class DemoSceneBuilder
    {
        [MenuItem("Return/Build Demo Scenes")]
        public static void Build()
        {
            var a = System.Environment.GetCommandLineArgs(); string dir = "Assets/ReturnDemo";
            for (int i = 0; i < a.Length - 1; i++) if (a[i] == "-out") dir = a[i + 1];
            Directory.CreateDirectory(dir);

            Scene(dir + "/ReturnDemo.unity", cam => { var app = new GameObject("ReturnApp").AddComponent<ReturnApp>(); app.viewer = cam; });
            Scene(dir + "/ReturnGallery.unity", cam => { var g = new GameObject("ComponentGallery").AddComponent<ComponentGallery>(); g.viewer = cam; });
            AssetDatabase.SaveAssets();
            Debug.Log("Return: demo scenes built in " + dir);
        }

        /// <summary>Add ReturnApp to an existing scene (default Assets/Scenes/SampleScene.unity). Return/Add To Open Scene works on the open scene.</summary>
        [MenuItem("Return/Add To Open Scene")]
        public static void AddToOpenScene()
        {
            if (Object.FindAnyObjectByType<ReturnApp>() != null) return;
            var cam = Camera.main;
            if (cam == null) { var g = new GameObject("Main Camera") { tag = "MainCamera" }; cam = g.AddComponent<Camera>(); g.AddComponent<AudioListener>(); }
            cam.transform.position = new Vector3(0, 1.6f, 0); cam.transform.rotation = Quaternion.identity;
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.05f, 0.06f, 0.1f); cam.nearClipPlane = 0.05f;
            new GameObject("ReturnApp").AddComponent<ReturnApp>().viewer = cam;
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
        }

        public static void AddToSampleScene()
        {
            var s = EditorSceneManager.OpenScene("Assets/Scenes/SampleScene.unity");
            AddToOpenScene();
            EditorSceneManager.SaveScene(s);
            Debug.Log("Return: added to SampleScene");
        }

        static void Scene(string path, System.Action<Camera> add)
        {
            var s = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            camGo.transform.position = new Vector3(0, 1.6f, 0);
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.05f, 0.06f, 0.1f); cam.nearClipPlane = 0.05f; cam.fieldOfView = 60;
            camGo.AddComponent<AudioListener>();
            add(cam);
            EditorSceneManager.SaveScene(s, path);
        }
    }
}
