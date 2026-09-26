using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Return.Data;

namespace Return.UI.Tests
{
    /// <summary>Port of web-app/src/data/store.test.ts.</summary>
    public class RoomLogicTests
    {
        [Test]
        public void RoomWalksInvitedToReady_AndRoutesFollow()
        {
            long now = 1_000_000;
            var r = RoomLogic.Seed(now).First(x => x.id == "ava-graduation");
            Assert.AreEqual(MemberStatus.Invited, RoomLogic.Mine(r).status);
            Assert.AreEqual(RoomLogic.Route.Add, RoomLogic.RouteForRoom(r));

            // I add my photos; Ava already has, so the next tick starts building.
            var me = RoomLogic.Mine(r); me.status = MemberStatus.Done; me.count = 3;
            Assert.AreEqual(RoomLogic.Route.Room, RoomLogic.RouteForRoom(r));
            r.members.Add(new Member { id = "x", name = "Sam", email = "s@x.io", status = MemberStatus.Invited, invitedAt = now, etaAt = now + 5000 });

            var list = new List<Room> { r };
            RoomLogic.Tick(list, now + 1000, 1000);
            Assert.AreEqual(Phase.Collecting, r.phase);   // Sam not in yet
            RoomLogic.Tick(list, now + 5000, 4000);
            Assert.AreEqual(Phase.Building, r.phase);     // everyone is in

            RoomLogic.Tick(list, now + 6000, 9000);
            Assert.Greater(r.progress, 0.4f);
            RoomLogic.Advance(r, now);
            Assert.AreEqual(Phase.Ready, r.phase);
            Assert.AreEqual(RoomLogic.Route.Room, RoomLogic.RouteForRoom(r));
        }

        [Test]
        public void Tick_LeavesUntouchedStateAlone()
        {
            var rooms = RoomLogic.Seed(0).Where(r => r.phase != Phase.Building).ToList();
            Assert.IsFalse(RoomLogic.Tick(rooms, 1, 1));
        }

        [Test]
        public void ReadyRoomsFor_OnlyJoinedOrDoneReadyRooms_PerAccount()
        {
            var rooms = RoomLogic.Seed(1_000_000);
            var mine = RoomLogic.ReadyRoomsFor(rooms, RoomLogic.MeId);
            Assert.AreEqual(4, mine.Count);
            CollectionAssert.DoesNotContain(mine.Select(r => r.id).ToList(), "ava-graduation"); // still just invited

            var maya = RoomLogic.ReadyRoomsFor(rooms, RoomLogic.MayaId);
            Assert.GreaterOrEqual(maya.Count, 3);
            CollectionAssert.IsSubsetOf(maya.Select(r => r.id), mine.Select(r => r.id)); // overlaps with Dylan's ready rooms
        }

        [Test]
        public void ParseObjects_TrimsDedupesCaps()
        {
            Assert.IsEmpty(RoomLogic.ParseObjects("  "));
            CollectionAssert.AreEqual(new[] { "vase", "porch swing" }, RoomLogic.ParseObjects("vase, porch swing,, vase "));
            Assert.AreEqual(8, RoomLogic.ParseObjects(string.Join(",", Enumerable.Range(0, 12).Select(i => "o" + i))).Count);
        }

        [Test]
        public void Store_CreateAddPhotosAndPersist()
        {
            var path = System.IO.Path.Combine(UnityEngine.Application.temporaryCachePath, "return-test.json");
            if (System.IO.File.Exists(path)) System.IO.File.Delete(path);
            var s = new RoomStore(path);
            var id = s.CreateRoom("Test room", new[] { "sam.park@gatech.edu" });
            s.AddPhotos(id, new List<string> { "a", "b" }, " hi ");
            var r = s.Get(id);
            Assert.AreEqual("hi", RoomLogic.Mine(r).note);
            Assert.AreEqual("a", r.cover);
            var again = new RoomStore(path);
            Assert.AreEqual("Test room", again.Get(id).title);
            System.IO.File.Delete(path);
        }
    }
}
