using System;
using System.Collections.Generic;

namespace Return.Data
{
    public enum MemberStatus { Invited, Joined, Done }
    public enum Phase { Collecting, Building, Ready }

    /// <summary>The painted environments. Keys mirror web-app/src/world/scenes.ts.</summary>
    /// <summary>Painted environments. Hub is the VR hub's own sky; it is last so saved rooms keep their meaning. Never reorder.</summary>
    public enum SceneKey { Meadow, Clouds, Painted, Home, Beach, Plain, CloudSea, Night, Hub }

    [Serializable]
    public class Member
    {
        public string id, name, email, note;
        public MemberStatus status;
        public int count;
        public bool isOwner;
        public long invitedAt;
        public long etaAt; // 0 = none

        public Member Clone() => (Member)MemberwiseClone();
    }

    [Serializable]
    public class Room
    {
        public string id, title, place, date, cover, note, invitedBy;
        public SceneKey scene;
        /// <summary>Photo ids. In the demo these are sample image names; a real backend would hold URLs.</summary>
        public List<string> photos = new List<string>();
        public List<Member> members = new List<Member>();
        public Phase phase;
        public float progress;
        public long createdAt;
        /// <summary>What to rebuild; empty = everything in the photos.</summary>
        public List<string> objects = new List<string>();

        public Room Clone()
        {
            var r = (Room)MemberwiseClone();
            r.photos = new List<string>(photos);
            r.objects = new List<string>(objects);
            r.members = members.ConvertAll(m => m.Clone());
            return r;
        }
    }

    [Serializable]
    public class Person { public string name, email; }
}
