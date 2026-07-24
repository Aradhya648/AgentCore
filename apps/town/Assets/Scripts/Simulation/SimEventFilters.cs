namespace AgentTown.Simulation
{
    /// <summary>
    /// Event Tab presentation helpers. Does not invent fields — only filters known noise types.
    /// </summary>
    public static class SimEventFilters
    {
        /// <summary>
        /// Tick bookends flood the Events Tab; prefer interaction / world_event / decisions.
        /// </summary>
        public static bool IsTickNoise(string type)
        {
            return type == "sim.tick_started" || type == "sim.tick_ended";
        }

        /// <summary>True when the Events Tab should render this row.</summary>
        public static bool IsStoryEvent(string type)
        {
            return !string.IsNullOrEmpty(type) && !IsTickNoise(type);
        }

        /// <summary>
        /// Story beats for 「下一故事」seek: interaction / world_event (and agent_action).
        /// Vote arrives as <c>sim.interaction</c> with kind vote — still a story event type.
        /// Narration (<c>sim.narration</c>) enriches the Events Tab but does not advance seek.
        /// </summary>
        public static bool IsStoryBeat(string type)
        {
            if (string.IsNullOrEmpty(type) || IsTickNoise(type))
            {
                return false;
            }

            return type == "sim.interaction"
                || type == "sim.world_event"
                || type == "sim.agent_action";
        }

        /// <summary>Narration / transition rows shown in the Events Tab between dialogue pulses.</summary>
        public static bool IsNarration(string type) => type == "sim.narration";
    }
}
