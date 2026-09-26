using System.Collections.Generic;
using System.IO;
using Return.Data;
using Return.Design;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Return.UI.Editor
{
    /// <summary>Renders every screen (Day and Dusk) to PNGs headless, for visual review. -executeMethod Return.UI.Editor.ScreenshotTool.CaptureAll -out DIR</summary>
    public static class ScreenshotTool
    {
        static string Arg(string name, string fallback)
        {
            var a = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
            return fallback;
        }

        public static void CaptureAll()
        {
            var dir = Arg("-out", Path.Combine(Application.dataPath, "../Shots"));
            Directory.CreateDirectory(dir);
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 40; cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.05f, 0.06f, 0.1f); cam.nearClipPlane = 0.05f; cam.farClipPlane = 50;

            var app = new GameObject("ReturnApp").AddComponent<ReturnApp>();
            app.viewer = cam; app.persist = false; app.startRoute = Route.Landing; app.handMenu = false;
            app.Bootstrap();

            const int W = 1920, H = 1200;
            var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            cam.targetTexture = rt; cam.aspect = W / (float)H;

            void Shot(string name)
            {
                app.Backdrop.Refresh();
                Canvas.ForceUpdateCanvases();
                foreach (var t in app.Panel.GetComponentsInChildren<UnityEngine.UI.LayoutGroup>()) UnityEngine.UI.LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)t.transform);
                Canvas.ForceUpdateCanvases();
                cam.Render();
                RenderTexture.active = rt;
                var tex = new Texture2D(W, H, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, W, H), 0, 0); tex.Apply();
                File.WriteAllBytes(Path.Combine(dir, name + ".png"), tex.EncodeToPNG());
                Object.DestroyImmediate(tex);
                RenderTexture.active = null;
                Debug.Log("Return: shot " + name);
            }

            var store = app.Store; var router = app.Router;
            void Go(Route r, string id = null) { router.Go(r, id, true); app.Backdrop.Finish(); }

            foreach (var theme in new[] { ReturnTheme.Day, ReturnTheme.Dusk })
            {
                ThemeManager.SetOverride(theme);
                string t = theme.ToString().ToLower();
                store.Reset();
                Go(Route.Landing); Shot(t + "-1-landing");
                Go(Route.SignIn); Shot(t + "-2-signin");
                store.SignIn();
                Go(Route.Dashboard); Shot(t + "-3-dashboard");
                Go(Route.CreateRoom); Shot(t + "-4-create");
                Go(Route.RoomUpload, "grandmas-porch"); // already done -> redirects to waiting
                Shot(t + "-5-waiting");
                Go(Route.RoomUpload, "ava-graduation"); Shot(t + "-6-upload");
                Go(Route.Room, "last-summer"); Shot(t + "-7-building");
                Go(Route.Room, "lake-house"); Shot(t + "-8-ready");
            }
            rt.Release();
        }

        /// <summary>Renders the VR hub from the head: sign-in, the portal ring, create room, and inside a stub world. -executeMethod Return.UI.Editor.ScreenshotTool.CaptureHub -out DIR</summary>
        public static void CaptureHub()
        {
            var dir = Arg("-out", Path.Combine(Application.dataPath, "../Shots")); Directory.CreateDirectory(dir);
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var camGo = new GameObject("Main Camera") { tag = "MainCamera" }; camGo.transform.position = new Vector3(0, 1.6f, 0);
            var cam = camGo.AddComponent<Camera>(); cam.fieldOfView = 85; cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = Color.black; cam.nearClipPlane = 0.05f; cam.farClipPlane = 200;
            var app = new GameObject("HubApp").AddComponent<HubApp>(); app.head = camGo.transform; app.persist = false;
            app.Bootstrap();
            const int W = 2400, H = 1200;
            var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB); cam.targetTexture = rt; cam.aspect = W / (float)H;
            void Shot(string name)
            {
                foreach (var t in Object.FindObjectsByType<UnityEngine.UI.LayoutGroup>(FindObjectsInactive.Exclude, FindObjectsSortMode.None)) UnityEngine.UI.LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)t.transform);
                Canvas.ForceUpdateCanvases();
                foreach (var t in Object.FindObjectsByType<UnityEngine.UI.LayoutGroup>(FindObjectsInactive.Exclude, FindObjectsSortMode.None)) UnityEngine.UI.LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)t.transform);
                Canvas.ForceUpdateCanvases();
                foreach (var e in Object.FindObjectsByType<HubEnvironment>(FindObjectsInactive.Exclude, FindObjectsSortMode.None)) e.SendMessage("LateUpdate");
                cam.Render(); RenderTexture.active = rt;
                var tex = new Texture2D(W, H, TextureFormat.RGB24, false); tex.ReadPixels(new Rect(0, 0, W, H), 0, 0); tex.Apply();
                File.WriteAllBytes(Path.Combine(dir, name + ".png"), tex.EncodeToPNG());
                Object.DestroyImmediate(tex); RenderTexture.active = null; Debug.Log("Return: shot " + name);
            }
            Shot("hub-1-signin");
            app.Store.SignIn(); app.Hub.Router.ContinueAfterSignIn();
            Shot("hub-2-ring");
            camGo.transform.rotation = Quaternion.Euler(0, -45, 0); Shot("hub-2b-ring-left");
            camGo.transform.rotation = Quaternion.Euler(0, 45, 0); Shot("hub-2c-ring-right");
            camGo.transform.rotation = Quaternion.identity;
            app.Hub.Router.Go(Route.RoomUpload, "ava-graduation", true); Shot("hub-3-add-photos");
            app.Hub.Router.Go(Route.Dashboard, null, true);
            var room = app.Store.Get("lake-house");
            GameObject.Find("ReturnHub").SetActive(false);
            new StubWorldLoader().Build(room, camGo.transform); Shot("hub-4-world");
            rt.Release();
        }

        /// <summary>Renders the component gallery, Day then Dusk, tall enough to show most sections. -executeMethod Return.UI.Editor.ScreenshotTool.CaptureGallery -out DIR</summary>
        public static void CaptureGallery()
        {
            var dir = Arg("-out", Path.Combine(Application.dataPath, "../Shots")); Directory.CreateDirectory(dir);
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var cam = new GameObject("Main Camera") { tag = "MainCamera" }.AddComponent<Camera>();
            cam.fieldOfView = 50; cam.clearFlags = CameraClearFlags.SolidColor; cam.nearClipPlane = 0.05f;
            var g = new GameObject("G").AddComponent<ComponentGallery>(); g.viewer = cam; g.Bootstrap();
            const int W = 1500, H = 1000;
            var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB); cam.targetTexture = rt; cam.aspect = W / (float)H;
            foreach (var pass in new[] { (ReturnTheme.Day, 0f), (ReturnTheme.Day, 1f), (ReturnTheme.Dusk, 0f) })
            {
                ThemeManager.SetOverride(pass.Item1);
                var content = g.Panel.rect.Find("Scroll/Viewport/Content") as RectTransform;
                g.Backdrop.Finish(); g.Backdrop.Refresh();
                Canvas.ForceUpdateCanvases();
                foreach (var t in g.Panel.GetComponentsInChildren<UnityEngine.UI.LayoutGroup>()) UnityEngine.UI.LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)t.transform);
                content.anchoredPosition = new Vector2(0, pass.Item2 * Mathf.Max(0, content.rect.height - 940));
                Canvas.ForceUpdateCanvases();
                cam.Render(); RenderTexture.active = rt;
                var tex = new Texture2D(W, H, TextureFormat.RGB24, false); tex.ReadPixels(new Rect(0, 0, W, H), 0, 0); tex.Apply();
                File.WriteAllBytes(Path.Combine(dir, "gallery-" + pass.Item1.ToString().ToLower() + "-" + pass.Item2 + ".png"), tex.EncodeToPNG());
                Object.DestroyImmediate(tex); RenderTexture.active = null;
            }
            Debug.Log("Return: gallery shots done");
        }

        /// <summary>Logs RectTransform sizes under the current screen (layout debugging). -executeMethod Return.UI.Editor.ScreenshotTool.DumpLanding</summary>
        public static void DumpLanding()
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var cam = new GameObject("Main Camera") { tag = "MainCamera" }.AddComponent<Camera>();
            var app = new GameObject("ReturnApp").AddComponent<ReturnApp>(); app.viewer = cam; app.persist = false; app.handMenu = false; app.Bootstrap();
            Canvas.ForceUpdateCanvases();
            foreach (var t in app.Panel.GetComponentsInChildren<UnityEngine.UI.LayoutGroup>()) UnityEngine.UI.LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)t.transform);
            var body = app.Panel.transform.Find("Screen:Landing/Body");
            void Dump(Transform t, int d) { var r = (RectTransform)t; Debug.Log("DUMP " + new string(' ', d * 2) + t.name + " " + r.rect.width.ToString("0") + "x" + r.rect.height.ToString("0") + " y=" + r.anchoredPosition.y.ToString("0")); if (d < 2) foreach (Transform c in t) Dump(c, d + 1); }
            if (body != null) Dump(body, 0); else Debug.Log("DUMP no body");
        }
    }
}
