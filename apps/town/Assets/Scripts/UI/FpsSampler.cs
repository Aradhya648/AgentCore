namespace AgentTown.UI
{
    /// <summary>
    /// Pure FPS averaging + band for the top-bar <c>fps-label</c> (§14 #5).
    /// Call <see cref="AddFrame"/> each Update; when a window completes, read
    /// <see cref="LastFps"/> / <see cref="LastBand"/>. EditMode-testable without Play mode.
    /// </summary>
    public sealed class FpsSampler
    {
        public const float DefaultWindowSeconds = 0.5f;
        /// <summary>Hard watch floor from the client spec (10 NPC ≥ 30 FPS).</summary>
        public const float TargetFps = 30f;
        public const float WarnFps = 20f;

        public enum Band
        {
            Unknown = 0,
            Ok = 1,
            Warn = 2,
            Critical = 3,
        }

        private readonly float windowSeconds;
        private float accum;
        private int frames;
        private float lastFps = -1f;
        private Band lastBand = Band.Unknown;

        public FpsSampler(float windowSeconds = DefaultWindowSeconds)
        {
            this.windowSeconds = windowSeconds > 0.05f ? windowSeconds : DefaultWindowSeconds;
        }

        public float LastFps => lastFps;

        public Band LastBand => lastBand;

        public bool HasSample => lastFps >= 0f;

        /// <summary>Accumulate one frame. Returns true when the display sample was refreshed.</summary>
        public bool AddFrame(float unscaledDeltaTime)
        {
            if (unscaledDeltaTime < 0f)
            {
                unscaledDeltaTime = 0f;
            }

            accum += unscaledDeltaTime;
            frames++;
            if (accum < windowSeconds)
            {
                return false;
            }

            lastFps = frames / accum;
            lastBand = Classify(lastFps);
            accum = 0f;
            frames = 0;
            return true;
        }

        public static Band Classify(float fps)
        {
            if (fps < 0f)
            {
                return Band.Unknown;
            }

            if (fps >= TargetFps)
            {
                return Band.Ok;
            }

            if (fps >= WarnFps)
            {
                return Band.Warn;
            }

            return Band.Critical;
        }

        public static string FormatLabel(float fps)
        {
            return fps < 0f ? "— FPS" : $"{fps:0} FPS";
        }

        /// <summary>USS class suffix for the fps-label (<c>fps-ok</c> / <c>fps-warn</c> / <c>fps-critical</c>).</summary>
        public static string BandClass(Band band)
        {
            switch (band)
            {
                case Band.Ok:
                    return "fps-ok";
                case Band.Warn:
                    return "fps-warn";
                case Band.Critical:
                    return "fps-critical";
                default:
                    return "fps-unknown";
            }
        }
    }
}
