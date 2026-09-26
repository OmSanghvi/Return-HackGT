using System;
using System.Threading.Tasks;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    public enum SessionState { Hub, Loading, InWorld }

    /// <summary>Enter and leave worlds: fade out, swap hub for world, fade in. One transition at a time.</summary>
    public class WorldSession
    {
        readonly IWorldLoader _loader; readonly ScreenFade _fade; readonly Transform _head; readonly Action<bool> _hubVisible;
        readonly PortalTransition _transition;
        public float fadeSeconds = 1.1f;
        public SessionState State { get; private set; } = SessionState.Hub;
        public Room Current { get; private set; }
        public event Action<SessionState> StateChanged;
        /// <summary>0..1 while Loading.</summary>
        public float Progress { get; private set; }

        /// <summary>The session driving whatever world is currently loaded, or null in the hub. XR glue (hold-to-exit, the
        /// per-world interactable pass) reaches it here instead of through HubController, which the core assembly can't see.</summary>
        public static WorldSession Active { get; private set; }
        /// <summary>Fired once a world finishes loading and the fade back in starts, with the room and the head transform it
        /// was built around. The XR assembly subscribes to run its grab/collider pass without this assembly depending on XRI.</summary>
        public static event Action<Room, Transform> WorldEntered;

        /// <summary>Signed-in account; HubController sets it before each enter so the arrival card leaves the viewer out.</summary>
        public string ViewerAccountId = RoomLogic.MeId;

        RoomPortal _homePortal; GameObject _arrivalCard;

        public WorldSession(IWorldLoader loader, ScreenFade fade, Transform head, Action<bool> hubVisible, PortalTransition transition = null)
        { _loader = loader; _fade = fade; _head = head; _hubVisible = hubVisible; _transition = transition; Active = this; }

        void Set(SessionState s) { State = s; StateChanged?.Invoke(s); }

        /// <summary>The one non-wrist-menu way home: fired by the HomePortal arch and by the XR hold-to-exit gesture.
        /// Fire-and-forget with the fault logged, same as HubController.ExitWorld.</summary>
        public void RequestExit() => ExitAsync().ContinueWith(t => Debug.LogException(t.Exception), TaskContinuationOptions.OnlyOnFaulted);

        /// <summary>Pure geometry rule shared with the XR world-interactable pass and its EditMode test: small enough to
        /// hold in one hand gets picked up by every prop consistently, so if one cup is grabbable every cup is.</summary>
        public const float HoldableMaxExtent = 0.5f;
        public static bool IsHoldable(Vector3 boundsSize) => Mathf.Max(boundsSize.x, Mathf.Max(boundsSize.y, boundsSize.z)) < HoldableMaxExtent;

        /// <summary>White-out for day paintings, deep blue for dusk ones (ReturnMotion.Enter).</summary>
        static Color FadeColor(Room r) => UIAssets.IsDusk(r.scene) ? (Color)ReturnColorsDusk.Canvas : Color.white;

        /// <summary>portal is the arch that was activated; step-through visuals (glide + vignette) play around it if given.</summary>
        public async Task EnterAsync(Room room, RoomPortal portal = null)
        {
            if (State != SessionState.Hub) return;
            Current = room; Progress = 0; Set(SessionState.Loading);
            try
            {
                if (_transition != null) await _transition.EnterStep(portal, _head);
                _fade.SetColor(FadeColor(room));
                await _fade.FadeTo(1f, fadeSeconds);
                _hubVisible(false);
                await _loader.LoadAsync(room, _head, p => Progress = p);
                await _fade.FadeTo(0f, fadeSeconds);
                Set(SessionState.InWorld); // only once the transition is done, so nothing can start on top of it
                _homePortal = HomePortal.Spawn(_head, RequestExit);
                _arrivalCard = ArrivalCard.Show(room, ViewerAccountId, _head);
                WorldEntered?.Invoke(room, _head);
            }
            catch (Exception e)
            {
                Debug.LogError("Return: could not enter " + room.title + ": " + e);
                await _loader.UnloadAsync(); _hubVisible(true); Current = null; await _fade.FadeTo(0f, fadeSeconds);
                if (_transition != null) await _transition.ExitStep(_head); // undo the glide so a failed enter doesn't strand the rig mid-arch
                Set(SessionState.Hub);
            }
        }

        public async Task ExitAsync()
        {
            if (State != SessionState.InWorld) return;
            Set(SessionState.Loading);
            HomePortal.Despawn(_homePortal); _homePortal = null;
            if (_arrivalCard != null) { UnityEngine.Object.Destroy(_arrivalCard); _arrivalCard = null; }
            try
            {
                _fade.SetColor(FadeColor(Current));
                await _fade.FadeTo(1f, fadeSeconds);
                await _loader.UnloadAsync();
                _hubVisible(true);
                Current = null;
                await _fade.FadeTo(0f, fadeSeconds);
                if (_transition != null) await _transition.ExitStep(_head);
            }
            catch (Exception e)
            {
                // Without this a throw after the fade-out left the view on the opaque (near-black, for dusk) fade quad with the
                // hub audio already back, and nothing in the log: callers fire and forget this task.
                Debug.LogError("Return: could not leave " + (Current != null ? Current.title : "the world") + ": " + e);
                try { _hubVisible(true); } catch (Exception e2) { Debug.LogException(e2); }
                Current = null;
                _fade.SetAlpha(0f);
            }
            Set(SessionState.Hub);
        }
    }
}
