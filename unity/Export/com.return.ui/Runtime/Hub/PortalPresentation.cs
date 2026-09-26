using System.Linq;
using Return.Data;

namespace Return.UI
{
    public enum PortalKind { Ready, Building, Waiting, AddPhotos, Invited }

    /// <summary>How a room's portal should read, from the room's state. Pure so it is testable.</summary>
    public struct PortalPresentation
    {
        public PortalKind kind;
        /// <summary>Window fog 0 (clear) to 1.</summary>
        public float mist;
        /// <summary>Window opacity.</summary>
        public float alpha;
        /// <summary>The short call to action under the title.</summary>
        public string hint;

        public bool CanEnter => kind == PortalKind.Ready;

        public static PortalPresentation For(Room r)
        {
            var mine = RoomLogic.Mine(r);
            if (mine?.status == MemberStatus.Invited) return new PortalPresentation { kind = PortalKind.Invited, mist = 0.55f, alpha = 0.85f, hint = (r.invitedBy ?? "Someone") + " invited you" };
            if (r.phase == Phase.Collecting && mine?.status != MemberStatus.Done) return new PortalPresentation { kind = PortalKind.AddPhotos, mist = 0.45f, alpha = 0.9f, hint = "Add your photos" };
            if (r.phase == Phase.Collecting) return new PortalPresentation { kind = PortalKind.Waiting, mist = 0.5f, alpha = 0.8f, hint = "Waiting for " + RoomLogic.WaitingOn(r) };
            if (r.phase == Phase.Building) return new PortalPresentation { kind = PortalKind.Building, mist = UnityEngine.Mathf.Max(0f, 1f - r.progress * 1.1f), alpha = 1f, hint = "Building " + (int)(r.progress * 100) + "%" };
            return new PortalPresentation { kind = PortalKind.Ready, mist = 0f, alpha = 1f, hint = "Pinch to enter" };
        }
    }
}
