using Newtonsoft.Json;

namespace AgentTown.Simulation
{
    /// <summary>
    /// A position in wire space: <b>Y-up right-handed</b> (<c>+x</c> east, <c>+z</c> south,
    /// <c>+y</c> up). This is the backend / fixture authority (see
    /// <c>agentcore.simulation.vec3.Vec3</c> and
    /// <c>docs/04-前端/AgentTown客户端.md §6.2</c>).
    /// The engine-side transform lives in <see cref="WireCoordinateTransform"/>.
    ///
    /// <para>Newtonsoft maps the lowercase wire fields via <see cref="JsonPropertyAttribute"/>;
    /// no <c>[Serializable]</c> so there is no ambiguity with Unity/ISerializable field naming.</para>
    /// </summary>
    public struct WireVec3
    {
        [JsonProperty("x")] public double X;
        [JsonProperty("y")] public double Y;
        [JsonProperty("z")] public double Z;

        public WireVec3(double x, double y, double z)
        {
            X = x;
            Y = y;
            Z = z;
        }

        [JsonIgnore]
        public bool IsFinite =>
            !double.IsNaN(X) && !double.IsInfinity(X) &&
            !double.IsNaN(Y) && !double.IsInfinity(Y) &&
            !double.IsNaN(Z) && !double.IsInfinity(Z);

        public override string ToString() => $"({X}, {Y}, {Z})";
    }
}
