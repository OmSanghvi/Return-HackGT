using System.Collections.Generic;
using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.EventSystems;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
#endif

namespace Return.UI
{
    /// <summary>
    /// Drop-in headset frontend. Put it on an empty GameObject in a scene that has your XR rig (or just a camera for desktop testing).
    /// Assign head (the camera) and optionally leftHand (wrist menu anchor). Worlds load through IWorldLoader; the default is a stub.
    /// </summary>
    public class HubApp : MonoBehaviour
    {
        [Header("Rig")]
        public Transform head;
        public Transform leftHand;

        [Header("Worlds")]
        [Tooltip("Room id to scene name (scene must be in Build Settings). Unmapped rooms load the stub world.")]
        public List<WorldEntry> worldMap = new List<WorldEntry>();
        public float fadeSeconds = 1.1f;

        [Header("Behaviour")]
        [Tooltip("Off = rooms live in memory only.")] public bool persist = true;
        [Tooltip("'.' fast-forwards the room you face or have open (demo).")] public bool demoSimulator = true;

        public IRoomStore Store { get; private set; }
        public HubController Hub { get; private set; }
        bool _booted;

        void Start() { Bootstrap(); }

        /// <summary>Runs from Start; call manually in edit mode (tools, tests).</summary>
        public void Bootstrap(IWorldLoader loaderOverride = null, IRoomStore storeOverride = null)
        {
            if (_booted) return; _booted = true;
            if (head == null && Camera.main != null) head = Camera.main.transform;
            UIEventSystem.Ensure();
            var cam = head != null ? head.GetComponent<Camera>() : null;
            if (cam != null && cam.GetComponent<PhysicsRaycaster>() == null) cam.gameObject.AddComponent<PhysicsRaycaster>(); // mouse clicks on portals

            Store = storeOverride ?? new RoomStore(persist ? RoomStore.DefaultPath : null);
            IWorldLoader loader = loaderOverride ?? (worldMap.Count > 0 ? new SceneWorldLoader(worldMap, new StubWorldLoader()) : new StubWorldLoader());
            Hub = gameObject.AddComponent<HubController>();
            Hub.store = Store; Hub.head = head; Hub.leftHand = leftHand; Hub.loader = loader; Hub.fadeSeconds = fadeSeconds;
            Hub.Bootstrap();
        }

        void Update()
        {
            if (Store == null) return;
            Store.Step(Time.unscaledDeltaTime);
#if ENABLE_INPUT_SYSTEM
            if (demoSimulator && Keyboard.current != null && Keyboard.current.periodKey.wasPressedThisFrame)
            { var id = Hub.FocusedRoomId(); if (id != null) Store.FastForward(id); }
#endif
        }
    }

    public static class UIEventSystem
    {
        /// <summary>Make sure there is an EventSystem. XR rigs usually bring their own (XRUIInputModule); this only adds a standard one if none exists.</summary>
        public static void Ensure()
        {
            if (Object.FindAnyObjectByType<EventSystem>() != null) return;
            var go = new GameObject("EventSystem", typeof(EventSystem));
#if ENABLE_INPUT_SYSTEM
            go.AddComponent<InputSystemUIInputModule>();
#else
            go.AddComponent<StandaloneInputModule>();
#endif
        }
    }
}
