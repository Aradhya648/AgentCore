using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Single transform point converting wire world coordinates (Y-up right-handed,
    /// <c>+x</c> east / <c>+z</c> south) into Unity world space (Y-up left-handed).
    /// See <c>docs/04-前端/AgentTown客户端.md §6.2</c>.
    ///
    /// <para>Wire and Unity are both Y-up, so the up axis (<c>y</c>) passes through
    /// untouched. They differ in handedness (wire right-handed, Unity left-handed),
    /// so exactly one axis is flipped — the <c>z</c> axis, per the glTF/Three.js →
    /// Unity convention — to avoid a mirrored layout.</para>
    ///
    /// <para><b>Acceptance oracle</b>: 市场 wire <c>(36, 0, 0)</c> → Unity <c>(36, 0, 0)</c>.</para>
    /// </summary>
    public static class WireCoordinateTransform
    {
        /// <summary>
        /// World scale: 1 wire unit = 1 metre = 1 Unity unit. Unity's base unit is the
        /// metre, so (unlike the retired UE reference which used centimetres) no ×100 is
        /// applied. NPC size / speed are authored in metres and align naturally.
        /// </summary>
        public const float WorldScale = 1f;

        /// <summary><c>unity = (wire.x, wire.y, -wire.z) × S</c></summary>
        public static Vector3 ToUnity(WireVec3 wire) => ToUnity(wire.X, wire.Y, wire.Z);

        /// <summary><c>unity = (wireX, wireY, -wireZ) × S</c></summary>
        public static Vector3 ToUnity(double wireX, double wireY, double wireZ)
        {
            const float s = WorldScale;
            return new Vector3(
                (float)wireX * s,
                (float)wireY * s,
                (float)(-wireZ) * s);
        }
    }
}
