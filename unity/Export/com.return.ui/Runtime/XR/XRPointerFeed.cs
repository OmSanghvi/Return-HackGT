using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

namespace Return.UI.XR
{
    /// <summary>
    /// Fills Return.UI.HubPointers from whatever controller interactors exist in the scene (NearFarInteractor,
    /// XRI 3.x's default, or the older XRRayInteractor), found once and refreshed on scene load. In the editor with
    /// no XR rig it falls back to the main camera + mouse ray, so the hub's water/fireflies/lanterns are testable
    /// in Play mode without a headset.
    /// </summary>
    static class XRPointerFeed
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Init()
        {
            if (GameObject.Find("XRPointerFeed") != null) return;
            var go = new GameObject("XRPointerFeed");
            UnityEngine.Object.DontDestroyOnLoad(go);
            go.AddComponent<Runner>();
        }

        class Runner : MonoBehaviour
        {
            XRBaseInteractor[] _interactors = Array.Empty<XRBaseInteractor>();
            float _rescanAt;
            readonly List<HubPointer> _pts = new List<HubPointer>(2);

            void OnEnable() { SceneManager.sceneLoaded += OnSceneLoaded; Rescan(); }
            void OnDisable() { SceneManager.sceneLoaded -= OnSceneLoaded; }
            void OnSceneLoaded(Scene s, LoadSceneMode m) => Rescan();

            void Rescan() => _interactors = FindObjectsByType<XRBaseInteractor>(FindObjectsSortMode.None)
                .Where(i => i is NearFarInteractor || i is XRRayInteractor).ToArray();

            void Update()
            {
                // controllers can spawn a frame or two after scene load; keep looking until we find some
                if (_interactors.Length == 0 && Time.unscaledTime > _rescanAt) { _rescanAt = Time.unscaledTime + 1f; Rescan(); }

                _pts.Clear();
                foreach (var it in _interactors)
                {
                    if (it == null || !it.isActiveAndEnabled) continue;
                    var t = it.attachTransform != null ? it.attachTransform : it.transform;
                    _pts.Add(new HubPointer { tip = t.position, forward = t.forward, select = it.isSelectActive });
                }
                if (_pts.Count == 0 && Application.isEditor && Camera.main != null)
                {
                    var ray = Camera.main.ScreenPointToRay(Input.mousePosition);
                    _pts.Add(new HubPointer { tip = ray.origin, forward = ray.direction, select = Input.GetMouseButton(0) });
                }
                HubPointers.Set(_pts);
            }
        }
    }
}
