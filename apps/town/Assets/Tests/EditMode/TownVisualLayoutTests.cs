using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode checks for the static town layout data (§6.3, §15.2 step 4). Guards that the
    /// runtime builder covers the authoritative regions from the fixture (incl. 心动营地) and that every
    /// region / road / zone table is populated.
    /// </summary>
    public sealed class TownVisualLayoutTests
    {
        private static readonly string[] ExpectedRegions =
        {
            "广场", "市场", "餐厅", "面包店", "公园", "住宅区", "镇政厅",
            "图书馆", "工坊", "码头", "心动营地",
        };

        [Test]
        public void Regions_CoverAllElevenAnchors()
        {
            Assert.AreEqual(ExpectedRegions.Length, TownVisualLayout.Regions.Length, "region count");

            var ids = new HashSet<string>();
            foreach (RegionVisualDef region in TownVisualLayout.Regions)
            {
                ids.Add(region.RegionId);
                Assert.IsNotEmpty(region.Buildings, $"region {region.RegionId} has placeholders");
            }

            foreach (string expected in ExpectedRegions)
            {
                Assert.IsTrue(ids.Contains(expected), $"layout covers region {expected}");
            }
        }

        [Test]
        public void GroundAndCamera_MatchExpandedWorld()
        {
            Assert.AreEqual(220f, TownVisualLayout.GroundSize.x, 0.01f);
            Assert.AreEqual(180f, TownVisualLayout.GroundSize.y, 0.01f);
            Assert.Greater(TownVisualLayout.CameraWire.y, 12f, "elevated bird look-down for core framing");
            Assert.Less(TownVisualLayout.CameraWire.y, 28f, "oblique angle, not straight-down top view");
            Assert.LessOrEqual(
                TownVisualLayout.BirdZoomShootDistance,
                TownVisualLayout.BirdZoomDefaultDistance,
                "shoot no wider than default watch");
            Assert.LessOrEqual(
                TownVisualLayout.BirdZoomDefaultDistance,
                30f,
                "mid framing on activity core, not far sand-table");
            Assert.GreaterOrEqual(
                TownVisualLayout.BirdZoomShootDistance,
                TownVisualLayout.BirdZoomMinDistance);
            Assert.Greater(TownVisualLayout.BirdZoomMaxDistance, TownVisualLayout.BirdZoomMinDistance);
            Assert.GreaterOrEqual(
                TownVisualLayout.BirdZoomDefaultDistance,
                TownVisualLayout.BirdZoomMinDistance);
        }

        [Test]
        public void Regions_MatchFixtureAnchorKeys()
        {
            Dictionary<string, WireVec3> anchors = RegionPositions.LoadFromFile();
            Assert.IsNotEmpty(anchors, "region fixture loaded");

            foreach (RegionVisualDef region in TownVisualLayout.Regions)
            {
                Assert.IsTrue(anchors.ContainsKey(region.RegionId), $"fixture has anchor for {region.RegionId}");
            }
        }

        [Test]
        public void RoadsAndZones_ArePopulated()
        {
            Assert.IsNotEmpty(TownVisualLayout.Roads, "road patches");
            Assert.IsNotEmpty(TownVisualLayout.Zones, "zone patches");
            Assert.AreEqual(TownVisualLayout.Regions.Length, TownVisualLayout.Zones.Length, "one lot per region");
            Assert.Greater(TownVisualLayout.GroundSize.x, 0f);
            Assert.Greater(TownVisualLayout.GroundSize.y, 0f);
        }

        [Test]
        public void RoadTiles_CoverMainArteries()
        {
            Assert.GreaterOrEqual(TownVisualLayout.RoadTiles.Length, 20, "road mesh tiles");
            bool hasCrossroad = false;
            bool hasStraight = false;
            foreach (RoadTileDef tile in TownVisualLayout.RoadTiles)
            {
                Assert.IsNotEmpty(tile.MeshName, "road stem");
                Assert.Greater(tile.Scale, 0f);
                if (tile.MeshName == "road-crossroad")
                {
                    hasCrossroad = true;
                }

                if (tile.MeshName == "road-straight")
                {
                    hasStraight = true;
                }
            }

            Assert.IsTrue(hasCrossroad, "plaza crossroad tile");
            Assert.IsTrue(hasStraight, "artery straight tiles");
        }

        [Test]
        public void NatureProps_ParkDenseAndOffRoadCenter()
        {
            Assert.GreaterOrEqual(TownVisualLayout.NatureProps.Length, 20, "nature props present");

            int parkish = 0;
            foreach (NaturePropDef prop in TownVisualLayout.NatureProps)
            {
                Assert.IsNotEmpty(prop.MeshName, "nature stem");
                Assert.Greater(prop.Scale, 0f);
                // Main E–W artery centre is z≈0 with width 7.5 → keep trunks outside |z|<3.5
                bool onMainRoadCenter = System.Math.Abs(prop.WireZ) < 3.5 && System.Math.Abs(prop.WireX) < 50;
                Assert.IsFalse(onMainRoadCenter, $"nature at ({prop.WireX},{prop.WireZ}) blocks main road");

                // Park lot roughly around (-32, 12)
                if (prop.WireX < -12 && prop.WireZ > 4)
                {
                    parkish++;
                }
            }

            Assert.GreaterOrEqual(parkish, 12, "park should be densely planted");
        }

        [Test]
        public void PlazaBuildings_ClearMainArteries()
        {
            RegionVisualDef plaza = default;
            bool found = false;
            foreach (RegionVisualDef region in TownVisualLayout.Regions)
            {
                if (region.RegionId == "广场")
                {
                    plaza = region;
                    found = true;
                    break;
                }
            }

            Assert.IsTrue(found, "plaza region");
            foreach (PlaceholderDef b in plaza.Buildings)
            {
                if (b.Shape == PlaceholderShape.Disc || b.Shape == PlaceholderShape.FlatProp)
                {
                    continue;
                }

                // Main E–W (z≈0, width 7.5) / N–S (x≈0): keep building centres off the road bed.
                Assert.GreaterOrEqual(
                    System.Math.Abs(b.OffsetZ), 3.6,
                    $"plaza building at ({b.OffsetX},{b.OffsetZ}) on E–W artery");
                Assert.GreaterOrEqual(
                    System.Math.Abs(b.OffsetX), 3.6,
                    $"plaza building at ({b.OffsetX},{b.OffsetZ}) on N–S artery");
            }
        }

        [Test]
        public void MeshFit_Constants_AreSane()
        {
            Assert.Greater(TownMeshFit.QuaterniusBuildingHeight, TownMeshFit.KenneyBuildingHeight * 0.5f);
            Assert.Greater(TownMeshFit.NatureTreeHeight, TownMeshFit.NatureBushHeight);
            Assert.IsTrue(TownMeshFit.IsQuaterniusStem("Hospital"));
            Assert.IsTrue(TownMeshFit.IsQuaterniusStem("Shop"));
            Assert.IsFalse(TownMeshFit.IsQuaterniusStem("building-a"));
            Assert.IsFalse(TownMeshFit.IsQuaterniusStem(null));
        }
    }
}
