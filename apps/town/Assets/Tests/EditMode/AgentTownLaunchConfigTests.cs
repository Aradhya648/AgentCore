using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;

namespace AgentTown.Tests
{
    /// <summary>EditMode coverage for launch-arg / URL-query parsing (§8.1).</summary>
    public sealed class AgentTownLaunchConfigTests
    {
        [Test]
        public void ParseCommandLine_HandlesSpaceAndEqualsForms()
        {
            string[] argv =
            {
                "AgentTown.exe", "--api", "http://localhost:9000", "--token=abc.def", "--run-id", "run-123",
            };

            Dictionary<string, string> args = AgentTownLaunchConfig.ParseCommandLine(argv);

            Assert.AreEqual("http://localhost:9000", args["api"]);
            Assert.AreEqual("abc.def", args["token"]);
            Assert.AreEqual("run-123", args["run-id"]);
        }

        [Test]
        public void ParseQuery_DecodesEscapedValues()
        {
            Dictionary<string, string> query =
                AgentTownLaunchConfig.ParseQuery("https://town.example/app?api=http%3A%2F%2Fh%3A8000&token=t1&run=r9#frag");

            Assert.AreEqual("http://h:8000", query["api"], "url-encoded api decoded");
            Assert.AreEqual("t1", query["token"]);
            Assert.AreEqual("r9", query["run"], "fragment stripped");
        }

        [Test]
        public void ParseCommandLine_NullSafe()
        {
            Assert.IsEmpty(AgentTownLaunchConfig.ParseCommandLine(null));
        }

        [Test]
        public void ParseCommandLine_DemoFlag()
        {
            Dictionary<string, string> args = AgentTownLaunchConfig.ParseCommandLine(
                new[] { "AgentTown.exe", "--demo" });
            Assert.AreEqual("true", args["demo"]);

            Dictionary<string, string> offline = AgentTownLaunchConfig.ParseCommandLine(
                new[] { "AgentTown.exe", "--offline=1" });
            Assert.AreEqual("1", offline["offline"]);
        }

        [Test]
        public void ParseQuery_DemoFlag()
        {
            Dictionary<string, string> query =
                AgentTownLaunchConfig.ParseQuery("https://town.example/app?demo=true");
            Assert.AreEqual("true", query["demo"]);
        }

        [Test]
        public void ParseQuery_PackParam()
        {
            Dictionary<string, string> query =
                AgentTownLaunchConfig.ParseQuery("https://town.example/app?demo=1&pack=festival");
            Assert.AreEqual("1", query["demo"]);
            Assert.AreEqual("festival", query["pack"]);
        }

        [Test]
        public void ParseQuery_ShootFlag()
        {
            Dictionary<string, string> query =
                AgentTownLaunchConfig.ParseQuery("https://town.example/app?demo=1&shoot=1&pack=price_surge");
            Assert.AreEqual("1", query["shoot"]);
        }

        [Test]
        public void ParseQuery_EpisodeParam()
        {
            Dictionary<string, string> query =
                AgentTownLaunchConfig.ParseQuery("https://town.example/app?episode=3");
            Assert.AreEqual("3", query["episode"]);
        }

        [Test]
        public void LaunchConfig_EpisodeDisablesAutoOffline()
        {
            var show = new AgentTownLaunchConfig(
                "http://localhost:8000", "", "", demo: false, packId: null, shoot: false, episode: 3);
            Assert.AreEqual(3, show.Episode);
            Assert.IsTrue(show.ShouldAutoShowEpisode);
            Assert.IsFalse(show.ShouldAutoOfflineDemo);
        }

        [Test]
        public void LaunchConfig_ShootFlag()
        {
            var shoot = new AgentTownLaunchConfig("http://localhost:8000", "", "", true, "price_surge", shoot: true);
            Assert.IsTrue(shoot.Shoot);
            Assert.IsTrue(shoot.ShouldAutoOfflineDemo);

            var watch = new AgentTownLaunchConfig("http://localhost:8000", "", "", true, "festival");
            Assert.IsFalse(watch.Shoot);
        }

        [Test]
        public void DemoPackIds_ShootLandmarkTicks()
        {
            Assert.AreEqual(9, DemoPackIds.ShootLandmarkTick(DemoPackIds.PriceSurge));
            Assert.AreEqual(12, DemoPackIds.ShootLandmarkTick(DemoPackIds.Festival));
            Assert.AreEqual(6, DemoPackIds.ShootLandmarkTick(DemoPackIds.TownHall));
            Assert.AreEqual("图书馆", DemoPackIds.ShootLandmarkRegion(DemoPackIds.PriceSurge));
            Assert.AreEqual("工坊", DemoPackIds.ShootLandmarkRegion(DemoPackIds.Festival));
            Assert.AreEqual("图书馆", DemoPackIds.ShootLandmarkRegion(DemoPackIds.TownHall));
        }

        [Test]
        public void ParseCommandLine_PackParam()
        {
            Dictionary<string, string> args = AgentTownLaunchConfig.ParseCommandLine(
                new[] { "AgentTown.exe", "--demo", "--pack", "town_hall" });
            Assert.AreEqual("true", args["demo"]);
            Assert.AreEqual("town_hall", args["pack"]);
        }

        [Test]
        public void LaunchConfig_NormalizesPackAndAutoDemo()
        {
            var withPack = new AgentTownLaunchConfig("http://localhost:8000", "", "", true, "Festival");
            Assert.AreEqual(DemoPackIds.Festival, withPack.PackId);
            Assert.IsTrue(withPack.ShouldAutoOfflineDemo);

            var blank = new AgentTownLaunchConfig("http://localhost:8000", "", "", false, null);
            Assert.AreEqual(DemoPackIds.PriceSurge, blank.PackId);
            Assert.IsTrue(blank.ShouldAutoOfflineDemo, "no token/run → auto offline");

            var live = new AgentTownLaunchConfig("http://localhost:8000", "tok", "run-1", false, "price_surge");
            Assert.IsFalse(live.ShouldAutoOfflineDemo);
        }

        [Test]
        public void DemoPackIds_NormalizeUnknownFallsBack()
        {
            Assert.AreEqual(DemoPackIds.PriceSurge, DemoPackIds.Normalize(null));
            Assert.AreEqual(DemoPackIds.PriceSurge, DemoPackIds.Normalize("nope"));
            Assert.AreEqual(DemoPackIds.TownHall, DemoPackIds.Normalize("TOWN_HALL"));
        }
    }
}
