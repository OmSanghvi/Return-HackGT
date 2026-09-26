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

        public WorldSession(IWorldLoader loader, ScreenFade fade, Transform head, Action<bool> hubVisible, PortalTransition transition = null)
        { _loader = loader; _fade = fade; _head = head; _hubVisible = hubVisible; _transition = transition; }

        void Set(SessionState s) { State = s; StateChanged?.Invoke(s); }

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
