using System.Collections.Generic;
using AgentTown.Simulation;
using NUnit.Framework;
using Newtonsoft.Json.Linq;

namespace AgentTown.Tests
{
    public sealed class InteractionTranscriptTests
    {
        [Test]
        public void FormatTranscript_JoinsNameAndText()
        {
            var lines = new List<InteractionTranscriptLine>
            {
                new() { SpeakerId = "zhao", SpeakerName = "赵老板", Text = "价从哪来？" },
                new() { SpeakerId = "wang", SpeakerName = "王婶", Text = "你管得着吗？" },
            };

            string formatted = InteractionModel.FormatTranscript(lines);
            Assert.AreEqual("赵老板：价从哪来？\n王婶：你管得着吗？", formatted);
        }

        [Test]
        public void FormatTranscript_EmptyOrNull_ReturnsEmpty()
        {
            Assert.AreEqual("", InteractionModel.FormatTranscript(null));
            Assert.AreEqual("", InteractionModel.FormatTranscript(new List<InteractionTranscriptLine>()));
            Assert.AreEqual(
                "",
                InteractionModel.FormatTranscript(new List<InteractionTranscriptLine>
                {
                    new() { SpeakerName = "甲", Text = "   " },
                }));
        }

        [Test]
        public void LinesForAgent_CollectsMultipleLines()
        {
            var lines = new List<InteractionTranscriptLine>
            {
                new() { SpeakerId = "zhao", Text = "第一句很长很长很长很长很长很长很长" },
                new() { SpeakerId = "wang", Text = "王婶插话" },
                new() { SpeakerId = "zhao", Text = "第二句" },
                new() { SpeakerId = "zhao", Text = "第三句" },
                new() { SpeakerId = "zhao", Text = "第四句应被截断" },
            };

            string multi = InteractionModel.LinesForAgent(lines, "zhao", maxLines: 3, maxLineLen: 12);
            Assert.IsNotNull(multi);
            string[] parts = multi.Split('\n');
            Assert.AreEqual(3, parts.Length);
            Assert.IsTrue(parts[0].EndsWith("…") || parts[0].Length <= 12);
            Assert.AreEqual("第二句", parts[1]);
            Assert.AreEqual("第三句", parts[2]);
        }

        [Test]
        public void ExtractEventSummary_InteractionUsesPayloadSummary()
        {
            var evt = new SimSseEvent
            {
                Type = "sim.interaction",
                Payload = new JObject
                {
                    ["tick"] = 3,
                    ["interaction"] = new JObject
                    {
                        ["kind"] = "conversation",
                        ["summary"] = "tick3 赵老板与王婶（涨价风波·试探）",
                        ["initiator_id"] = "zhao",
                        ["target_id"] = "wang",
                        ["transcript"] = new JArray
                        {
                            new JObject
                            {
                                ["speaker_id"] = "zhao",
                                ["speaker_name"] = "赵老板",
                                ["text"] = "价从哪来？",
                                ["round"] = 0,
                            },
                            new JObject
                            {
                                ["speaker_id"] = "wang",
                                ["speaker_name"] = "王婶",
                                ["text"] = "你管得着吗？",
                                ["round"] = 1,
                            },
                        },
                    },
                },
            };

            Assert.AreEqual(
                "tick3 赵老板与王婶（涨价风波·试探）",
                SimulationSession.ExtractEventSummary(evt));
            Assert.AreEqual("zhao", SimulationSession.ExtractEventAgentId(evt));
            string detail = SimulationSession.ExtractEventDetail(evt);
            Assert.IsTrue(detail.Contains("赵老板：价从哪来？"));
            Assert.IsTrue(detail.Contains("王婶：你管得着吗？"));
        }

        [Test]
        public void ExtractEventSummary_WorldEventAndAgentAction()
        {
            var world = new SimSseEvent
            {
                Type = "sim.world_event",
                Payload = new JObject
                {
                    ["tick"] = 6,
                    ["event"] = new JObject
                    {
                        ["kind"] = "price_surge",
                        ["title"] = "市场物价上涨",
                        ["description"] = "进货渠道告急，价格飙升。",
                    },
                },
            };
            Assert.AreEqual("市场物价上涨", SimulationSession.ExtractEventSummary(world));
            Assert.AreEqual("进货渠道告急，价格飙升。", SimulationSession.ExtractEventDetail(world));
            Assert.AreEqual("", SimulationSession.ExtractEventAgentId(world));

            var action = new SimSseEvent
            {
                Type = "sim.agent_action",
                Payload = new JObject
                {
                    ["tick"] = 2,
                    ["action"] = new JObject
                    {
                        ["agent_id"] = "lin",
                        ["action"] = "move_to",
                        ["thought"] = "去市场看看行情",
                        ["detail"] = "scripted move_to 市场",
                    },
                },
            };
            Assert.AreEqual("去市场看看行情", SimulationSession.ExtractEventSummary(action));
            Assert.AreEqual("lin", SimulationSession.ExtractEventAgentId(action));
        }

        [Test]
        public void IngestSseEvent_PushTickEvent_UsesRealSummaryAndDetail()
        {
            var session = new SimulationSession();
            session.Configure("http://localhost", "", "run-test");

            session.IngestSseEvent(new SimSseEvent
            {
                Type = "sim.interaction",
                Timestamp = "2026-01-01T08:00:00.000Z",
                Payload = new JObject
                {
                    ["tick"] = 3,
                    ["interaction"] = new JObject
                    {
                        ["kind"] = "conversation",
                        ["status"] = "completed",
                        ["summary"] = "涨价风波·试探",
                        ["initiator_id"] = "zhao",
                        ["target_id"] = "wang",
                        ["transcript"] = new JArray
                        {
                            new JObject
                            {
                                ["speaker_id"] = "zhao",
                                ["speaker_name"] = "赵老板",
                                ["text"] = "价从哪来？",
                            },
                            new JObject
                            {
                                ["speaker_id"] = "wang",
                                ["speaker_name"] = "王婶",
                                ["text"] = "你管得着吗？",
                            },
                        },
                    },
                },
            });

            Assert.AreEqual(1, session.TickEvents.Count);
            SimTickEvent row = session.TickEvents[0];
            Assert.AreEqual("sim.interaction", row.Type);
            Assert.AreEqual("涨价风波·试探", row.Summary);
            Assert.AreNotEqual("sim.interaction", row.Summary);
            Assert.AreEqual("zhao", row.AgentId);
            Assert.IsTrue(row.Detail.Contains("赵老板："));
            Assert.IsTrue(row.Detail.Contains("王婶："));
        }
    }
}
