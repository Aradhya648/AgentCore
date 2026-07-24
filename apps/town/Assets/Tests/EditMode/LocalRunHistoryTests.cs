using System.Collections.Generic;
using AgentTown.Simulation;
using NUnit.Framework;

namespace AgentTown.Tests
{
    /// <summary>EditMode coverage for local Run history (§9 UT-10).</summary>
    public sealed class LocalRunHistoryTests
    {
        private string storage;

        [SetUp]
        public void SetUp()
        {
            storage = "[]";
            LocalRunHistory.ReadRawOverride = () => storage;
            LocalRunHistory.WriteRawOverride = value => storage = value ?? "[]";
        }

        [TearDown]
        public void TearDown() => LocalRunHistory.ResetOverrides();

        [Test]
        public void Remember_UpsertsAndCapsAtTwelve()
        {
            for (int i = 0; i < 15; i++)
            {
                LocalRunHistory.Remember($"run-{i}", scenario: "town", seed: i, lastTick: i);
            }

            List<SavedRunEntry> listed = LocalRunHistory.List();
            Assert.AreEqual(LocalRunHistory.MaxRuns, listed.Count, "cap at 12");
            Assert.AreEqual("run-14", listed[0].Id, "most recent first");
            Assert.AreEqual(14, listed[0].Seed);
            Assert.AreEqual(14, listed[0].LastTick);
            Assert.IsFalse(listed.Exists(r => r.Id == "run-0"), "oldest dropped");
        }

        [Test]
        public void Remember_PreservesCreatedAt_OnResume()
        {
            LocalRunHistory.Remember("run-a", lastTick: 0);
            string created = LocalRunHistory.List()[0].CreatedAt;
            Assert.IsNotEmpty(created);

            LocalRunHistory.Remember("run-a", lastTick: 3, status: "running");
            SavedRunEntry again = LocalRunHistory.List()[0];
            Assert.AreEqual(created, again.CreatedAt, "createdAt stable");
            Assert.AreEqual(3, again.LastTick);
            Assert.AreEqual("running", again.Status);
            Assert.IsNotEmpty(again.UpdatedAt);
        }

        [Test]
        public void Update_PatchesLastTick()
        {
            LocalRunHistory.Remember("run-b", lastTick: 1);
            LocalRunHistory.Update("run-b", lastTick: 5, status: "paused");
            SavedRunEntry entry = LocalRunHistory.List()[0];
            Assert.AreEqual(5, entry.LastTick);
            Assert.AreEqual("paused", entry.Status);
        }
    }
}
