using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Return.Data;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Return.UI
{
    [Serializable] public class WorldEntry { public string roomId, sceneName; }

    /// <summary>Loads a room's world as an additive Unity scene from a roomId to sceneName map (hardcode.MD: map lake-house to one known-good scene). Falls back to the stub for unmapped rooms.
    /// The scene's WorldSceneRoot is moved under the viewer once loaded; build world scenes with Tools/Return/Worlds (ReturnWorldScenes).</summary>
    public class SceneWorldLoader : IWorldLoader
    {
        readonly Dictionary<string, string> _map = new Dictionary<string, string>();
        readonly IWorldLoader _fallback;
        Scene _loaded; bool _hasScene; bool _usedFallback;

        public SceneWorldLoader(IEnumerable<WorldEntry> entries, IWorldLoader fallback)
        {
            foreach (var e in entries) if (!string.IsNullOrEmpty(e.roomId) && !string.IsNullOrEmpty(e.sceneName)) _map[e.roomId] = e.sceneName;
            _fallback = fallback;
        }

        public bool TryGetScene(string roomId, out string sceneName) => _map.TryGetValue(roomId, out sceneName);

        public async Task LoadAsync(Room room, Transform head, Action<float> progress)
        {
            _usedFallback = false;
            if (!TryGetScene(room.id, out var name)) { _usedFallback = true; await _fallback.LoadAsync(room, head, progress); return; }
            var op = SceneManager.LoadSceneAsync(name, LoadSceneMode.Additive);
            if (op == null)
            {
                Debug.LogWarning("Return: scene '" + name + "' is not in Build Settings. Using the stub world.");
                _usedFallback = true; await _fallback.LoadAsync(room, head, progress); return;
            }
            while (!op.isDone) { progress?.Invoke(Mathf.Clamp01(op.progress / 0.9f)); await Task.Yield(); }
            _loaded = SceneManager.GetSceneByName(name); _hasScene = true;
            var root = FindRoot(_loaded);
            if (root != null) root.Arrive(room, head);
            else Debug.LogWarning("Return: scene '" + name + "' has no WorldSceneRoot, so it stays where it was authored instead of around the viewer.");
            progress?.Invoke(1f);
        }

        static WorldSceneRoot FindRoot(Scene scene)
        {
            foreach (var go in scene.GetRootGameObjects())
            {
                var root = go.GetComponentInChildren<WorldSceneRoot>(true);
                if (root != null) return root;
            }
            return null;
        }

        public async Task UnloadAsync()
        {
            if (_usedFallback) { await _fallback.UnloadAsync(); return; }
            if (_hasScene && _loaded.isLoaded) { var op = SceneManager.UnloadSceneAsync(_loaded); while (op != null && !op.isDone) await Task.Yield(); }
            _hasScene = false;
        }
    }
}
