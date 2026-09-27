using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Scripted screenshots from saved camera poses. Every child of a "Screenshot Poses" object in the open scene is one shot
/// (an empty GameObject: its position and rotation are the camera's). Tools > Return > Screenshots > Capture Open Scene
/// enters Play mode, lets the scene settle, moves the main camera to each pose and calls ScreenCapture.CaptureScreenshot
/// with the Game view pinned to 1920x1080 at 2x, so every file is 3840x2160. It then leaves Play mode.
/// Files land in unity/Screenshots/{scene}/{pose}.png. To add a shot, frame it in the Scene view and use
/// Tools > Return > Screenshots > Add Pose From Scene View.
/// </summary>
[InitializeOnLoad]
public static class PoseScreenshots
{
    const string PosesRoot = "Screenshot Poses", Pending = "PoseScreenshots.Pending";
    const uint Width = 1920, Height = 1080;
    const int SuperSize = 2;
    const float SettleSeconds = 6f; // the hub's greeting, sky wake and portal bloom finish in about 4 s

    static PoseScreenshots()
    {
        EditorApplication.playModeStateChanged += state =>
        {
            if (state == PlayModeStateChange.EnteredEditMode) SessionState.SetBool(Pending, false); // a run that never started
            if (state != PlayModeStateChange.EnteredPlayMode || !SessionState.GetBool(Pending, false)) return;
            SessionState.SetBool(Pending, false);
            Run(exitAfter: true);
        };
    }

    [MenuItem("Tools/Return/Screenshots/Capture Open Scene")]
    public static void Capture()
    {
        if (EditorApplication.isPlaying) { Run(exitAfter: false); return; }
        SessionState.SetBool(Pending, true); // Play mode reloads scripts; the handler above picks the run back up
        EditorApplication.isPlaying = true;
    }

    [MenuItem("Tools/Return/Screenshots/Add Pose From Scene View")]
    static void AddPose()
    {
        var view = SceneView.lastActiveSceneView;
        if (view == null) { Debug.LogWarning("Screenshots: open a Scene view and frame the shot first."); return; }
        var root = GameObject.Find(PosesRoot);
        if (root == null) { root = new GameObject(PosesRoot) { tag = "EditorOnly" }; Undo.RegisterCreatedObjectUndo(root, "Add Screenshot Pose"); } // EditorOnly: stripped from player builds
        var pose = new GameObject("shot-" + (root.transform.childCount + 1));
        pose.transform.SetParent(root.transform, false);
        pose.transform.SetPositionAndRotation(view.camera.transform.position, view.camera.transform.rotation);
        Undo.RegisterCreatedObjectUndo(pose, "Add Screenshot Pose");
        Selection.activeGameObject = pose;
    }

    static async void Run(bool exitAfter)
    {
        var root = GameObject.Find(PosesRoot);
        if (root == null || root.transform.childCount == 0)
        {
            Debug.LogError("Screenshots: no '" + PosesRoot + "' object with pose children in this scene. Add one with Tools > Return > Screenshots > Add Pose From Scene View.");
            if (exitAfter) EditorApplication.isPlaying = false;
            return;
        }
        var cam = Camera.main != null ? Camera.main : new GameObject("Screenshot Camera").AddComponent<Camera>(); // world scenes played on their own have no rig
        PlayModeWindow.SetCustomRenderingResolution(Width, Height, "Screenshots 1920x1080");
        bool gizmos = SetGameViewGizmos(false); // the Game view's Gizmos toggle draws component icons into the capture
        await Seconds(SettleSeconds);

        var restore = new List<Behaviour>(); var reshow = new List<GameObject>();
        void Hide(GameObject go) { if (go.activeSelf) { go.SetActive(false); reshow.Add(go); } }
        // XR tracking would pull the camera back to the headset (or device simulator) pose every frame; the simulator also
        // draws its help overlay into the Game view, and the rig's hands, controllers and wrist menu hang in front of the lens
        foreach (var b in cam.GetComponents<Behaviour>()) if (b.enabled && b.GetType().Name == "TrackedPoseDriver") { b.enabled = false; restore.Add(b); }
        foreach (var mb in Object.FindObjectsByType<MonoBehaviour>()) if (mb.GetType().Name == "XRDeviceSimulator" || mb.GetType().Name == "XRInteractionSimulator") Hide(mb.gameObject);
        if (cam.transform.parent != null) foreach (Transform t in cam.transform.parent) if (t != cam.transform) Hide(t.gameObject);
        bool signedIn = PrepareHub();
        await Seconds(2f); // the hover glow used to dismiss the hub's nudge fades out

        var dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Screenshots", SceneManager.GetActiveScene().name);
        Directory.CreateDirectory(dir);
        foreach (Transform pose in root.transform)
        {
            if (!pose.gameObject.activeSelf) continue;
            cam.transform.SetPositionAndRotation(pose.position, pose.rotation);
            await Frames(3); // billboarded labels and camera-following effects catch up
            var path = Path.Combine(dir, pose.name + ".png");
            if (File.Exists(path)) File.Delete(path);
            ScreenCapture.CaptureScreenshot(path, SuperSize);
            for (float t = 0; t < 10f && !File.Exists(path); t += 0.1f) await Seconds(0.1f);
            await Frames(2); // let the write finish before the camera moves
            Debug.Log(File.Exists(path) ? "Screenshots: " + path : "Screenshots: capture timed out for " + pose.name);
        }

        if (signedIn) Object.FindAnyObjectByType<Return.UI.HubApp>().Store.SignOut(); // leave the demo on its account picker
        SetGameViewGizmos(gizmos);
        if (exitAfter) { EditorApplication.isPlaying = false; return; }
        foreach (var b in restore) if (b != null) b.enabled = true;
        foreach (var go in reshow) if (go != null) go.SetActive(true);
    }

    /// <summary>The Return hub shows its account picker until someone signs in: sign in so the portals are up, and hover a
    /// portal once, which dismisses the "reach toward a world" nudge its greeting ends on. Returns whether it signed in.</summary>
    static bool PrepareHub()
    {
        var app = Object.FindAnyObjectByType<Return.UI.HubApp>();
        if (app == null || app.Store == null) return false;
        bool signIn = !app.Store.SignedIn;
        if (signIn) { app.Store.SignIn(); app.Hub.ShowRing(); }
        var portal = Object.FindAnyObjectByType<Return.UI.RoomPortal>();
        if (portal != null) portal.Hover();
        return signIn;
    }

    /// <summary>Sets the Gizmos toggle on every Game view; returns whether any had it on.</summary>
    static bool SetGameViewGizmos(bool on)
    {
        bool was = false;
        foreach (var w in Resources.FindObjectsOfTypeAll<EditorWindow>())
        {
            if (w.GetType().Name != "GameView") continue;
            var so = new SerializedObject(w); var p = so.FindProperty("m_Gizmos");
            if (p == null) continue;
            was |= p.boolValue; p.boolValue = on; so.ApplyModifiedPropertiesWithoutUndo(); w.Repaint();
        }
        return was;
    }

    static async Task Seconds(float s)
    {
        float end = Time.realtimeSinceStartup + s;
        while (Time.realtimeSinceStartup < end) await Frames(1);
    }

    static async Task Frames(int n)
    {
        for (int i = 0; i < n; i++) { UnityEditorInternal.InternalEditorUtility.RepaintAllViews(); await Task.Yield(); } // keeps the Game view rendering when the editor is in the background
    }
}
