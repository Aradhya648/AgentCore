using System.Collections.Generic;
using System.IO;
using AgentTown.Show;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    public sealed class EpisodeManifestTests
    {
        private static string ManifestPath => Path.Combine(
            Application.streamingAssetsPath, "Fixtures", "show", "episode-3-manifest.json");

        [Test]
        public void Parse_Episode3_HasSegmentsQuizRevealHighlights()
        {
            Assert.IsTrue(File.Exists(ManifestPath), $"missing {ManifestPath}");
            string json = File.ReadAllText(ManifestPath);
            EpisodeManifest manifest = EpisodeManifestLoader.Parse(json);
            Assert.IsTrue(EpisodeManifestLoader.Validate(manifest, out string error), error);
            Assert.AreEqual(1, manifest.Version);
            Assert.AreEqual(3, manifest.EpisodeNo);
            Assert.AreEqual(7, manifest.Segments.Count);
            Assert.IsNotNull(manifest.Quiz);
            Assert.AreEqual("xuanan", manifest.Quiz.Focus);
            Assert.AreEqual("xieheng", manifest.Quiz.Answer);
            Assert.IsNotNull(manifest.Reveal);
            Assert.AreEqual(6, manifest.Reveal.Steps.Count);
            Assert.AreEqual(3, manifest.Highlights.Count);
        }

        [Test]
        public void ShotAtTick_PicksLatestShot()
        {
            string json = File.ReadAllText(ManifestPath);
            EpisodeManifest manifest = EpisodeManifestLoader.Parse(json);
            EpisodeShot night = EpisodeManifestLoader.ShotAtTick(manifest, 60);
            Assert.IsNotNull(night);
            Assert.AreEqual("night-toxic", night.Id);

            EpisodeShot reveal = EpisodeManifestLoader.ShotAtTick(manifest, 101);
            Assert.IsNotNull(reveal);
            Assert.AreEqual("reveal-xuanan", reveal.Id);
        }

        [Test]
        public void OfflineShowBuilder_SynthesisesInclusiveTickRange()
        {
            string json = File.ReadAllText(ManifestPath);
            EpisodeManifest manifest = EpisodeManifestLoader.Parse(json);
            Dictionary<string, WireVec3> regions = RegionPositions.LoadFromFile();
            OfflineDemoPack pack = OfflineShowBuilder.Build(manifest, regions);
            Assert.AreEqual(120, pack.Frames.Count, "ticks 0..119 inclusive");
            Assert.AreEqual(0, pack.Frames[0].Tick);
            Assert.AreEqual(119, pack.Frames[pack.Frames.Count - 1].Tick);
            Assert.AreEqual(6, pack.Frames[50].Agents.Count, "six cast members");
            Assert.IsTrue(pack.Frames[50].Agents.ContainsKey("xuanan"));
        }

        [Test]
        public void ShowShootLandmark_HasShotAndCaptionOnFrame()
        {
            string json = File.ReadAllText(ManifestPath);
            EpisodeManifest manifest = EpisodeManifestLoader.Parse(json);
            int tick = TownBootstrap.ShowShootLandmarkTick;

            Assert.GreaterOrEqual(tick, manifest.TickRange.Start, "landmark inside episode range");
            Assert.LessOrEqual(tick, manifest.TickRange.End, "landmark inside episode range");

            EpisodeShot shot = EpisodeManifestLoader.ShotAtTick(manifest, tick);
            Assert.IsNotNull(shot, "landmark tick must resolve a manifest shot");
            Assert.IsNotEmpty(shot.Subjects, "landmark shot should frame cast members");

            EpisodeSegment segment = EpisodeManifestLoader.SegmentAtTick(manifest, tick);
            Assert.IsNotNull(segment, "landmark tick must sit inside a segment");

            bool hasCaption = false;
            foreach (EpisodeOverlayView view in EpisodeManifestLoader.FlattenOverlays(manifest))
            {
                if (view?.TickAt == null || view.TickAt.Value > tick
                    || view.TickAt.Value < segment.TickSpan.Start)
                {
                    continue;
                }

                if (view.Kind == "line" || view.Kind == "action" || view.Kind == "narration"
                    || view.Kind == "title_card")
                {
                    hasCaption = true;
                    break;
                }
            }

            Assert.IsTrue(hasCaption, "shoot gate frame needs a caption overlay at or before the landmark");
        }

        [Test]
        public void CinematicDirector_ResolvesCameraKinds()
        {
            Assert.AreEqual(
                CinematicDirector.CameraKind.FollowPair,
                CinematicDirector.ParseKind("follow_pair"));
            Assert.AreEqual(
                CinematicDirector.CameraKind.RevealCloseup,
                CinematicDirector.ParseKind("reveal_closeup"));

            var shot = new EpisodeShot
            {
                Id = "t",
                Camera = "push_in",
                Subjects = new List<string> { "a" },
                TickAt = 1,
            };
            var positions = new Dictionary<string, Vector3> { ["a"] = new Vector3(1, 0, 2) };
            Assert.IsTrue(CinematicDirector.TryResolveFraming(
                shot, positions, Vector3.zero,
                out CinematicDirector.CameraKind kind, out Vector3 lookAt, out Vector3 camPos));
            Assert.AreEqual(CinematicDirector.CameraKind.PushIn, kind);
            Assert.AreEqual(new Vector3(1, 0, 2), lookAt);
            Assert.Greater(camPos.y, 0f);
        }
    }
}
