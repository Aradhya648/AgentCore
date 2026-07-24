using System.Collections.Generic;
using AgentTown.Simulation;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode conformance for the wire → Unity coordinate transform (§6.2, §12).
    /// Reads the synced region fixture from <c>StreamingAssets/Fixtures</c> and asserts the
    /// 市场 oracle plus a per-region error bound &lt; 0.5 m against the §6.2 formula.
    /// </summary>
    public sealed class WireCoordinateTransformTests
    {
        private const float ToleranceMeters = 0.5f;

        private static readonly string[] ExpectedRegions =
        {
            "广场", "市场", "餐厅", "面包店", "公园", "住宅区", "镇政厅",
            "图书馆", "工坊", "码头", "心动营地",
        };

        [Test]
        public void Market_MapsTo_36_0_0()
        {
            Vector3 unity = WireCoordinateTransform.ToUnity(new WireVec3(36.0, 0.0, 0.0));

            Assert.AreEqual(36f, unity.x, 1e-4f, "market X");
            Assert.AreEqual(0f, unity.y, 1e-4f, "market Y");
            Assert.AreEqual(0f, unity.z, 1e-4f, "market Z");
        }

        [Test]
        public void Transform_FlipsZ_AndPassesYThrough()
        {
            // Y-up preserved; handedness flip is exactly the z axis (§6.2).
            Vector3 south = WireCoordinateTransform.ToUnity(new WireVec3(0.0, 3.0, 12.0));

            Assert.AreEqual(0f, south.x, 1e-4f);
            Assert.AreEqual(3f, south.y, 1e-4f, "up axis passes through");
            Assert.AreEqual(-12f, south.z, 1e-4f, "wire +z (south) → Unity -z");
        }

        [Test]
        public void AllRegionsFromFixture_MatchFormula_WithinHalfMeter()
        {
            Dictionary<string, WireVec3> regions = RegionPositions.LoadFromFile();

            Assert.IsNotEmpty(
                regions,
                $"Region fixture not loaded — expected at {RegionPositions.DefaultFixturePath}");
            Assert.AreEqual(ExpectedRegions.Length, regions.Count, "region count");

            foreach (string name in ExpectedRegions)
            {
                Assert.IsTrue(regions.ContainsKey(name), $"fixture missing region {name}");

                WireVec3 wire = regions[name];
                Assert.IsTrue(wire.IsFinite, $"region {name} wire finite");

                // Oracle per §6.2: unity = (x, y, -z) × S, with S = 1.
                var expected = new Vector3((float)wire.X, (float)wire.Y, (float)(-wire.Z));
                Vector3 actual = WireCoordinateTransform.ToUnity(wire);

                float error = Vector3.Distance(expected, actual);
                Assert.Less(error, ToleranceMeters, $"region {name} transform error < 0.5 m");
            }
        }
    }
}
