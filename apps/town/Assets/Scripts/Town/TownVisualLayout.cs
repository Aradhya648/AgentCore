using UnityEngine;

namespace AgentTown.Town
{
    public enum PlaceholderShape
    {
        /// <summary>Tall box — houses / shops (UE <c>Cube</c>).</summary>
        Building,

        /// <summary>Short disc — parasols / benches (UE <c>Cylinder</c>).</summary>
        Disc,

        /// <summary>Low slab — stalls / awnings (UE <c>FlatCube</c>).</summary>
        FlatProp,

        /// <summary>Tall column — civic towers (UE <c>TallCylinder</c>).</summary>
        Tower,
    }

    /// <summary>One placeholder building, positioned by a wire-space XZ offset from its region anchor.</summary>
    public readonly struct PlaceholderDef
    {
        public readonly double OffsetX;
        public readonly double OffsetZ;
        public readonly float RotationYRad;
        public readonly float Scale;
        public readonly PlaceholderShape Shape;

        public PlaceholderDef(double offsetX, double offsetZ, float rotationYRad, float scale, PlaceholderShape shape)
        {
            OffsetX = offsetX;
            OffsetZ = offsetZ;
            RotationYRad = rotationYRad;
            Scale = scale;
            Shape = shape;
        }
    }

    /// <summary>Per-region zone tint + placeholder cluster.</summary>
    public readonly struct RegionVisualDef
    {
        public readonly string RegionId;
        public readonly Color ZoneColor;
        public readonly PlaceholderDef[] Buildings;

        public RegionVisualDef(string regionId, Color zoneColor, PlaceholderDef[] buildings)
        {
            RegionId = regionId;
            ZoneColor = zoneColor;
            Buildings = buildings;
        }
    }

    /// <summary>One foliage / park prop, positioned in absolute wire XZ (not region-relative).</summary>
    public readonly struct NaturePropDef
    {
        public readonly double WireX;
        public readonly double WireZ;
        public readonly float RotationYRad;
        public readonly float Scale;
        /// <summary>Catalog stem (e.g. <c>tree_oak</c>); empty → pool wrap / primitive.</summary>
        public readonly string MeshName;
        /// <summary>When true, use more aggressive distance LOD (trees / dense foliage).</summary>
        public readonly bool AggressiveLod;

        public NaturePropDef(
            double wireX, double wireZ, float rotationYRad, float scale, string meshName, bool aggressiveLod = true)
        {
            WireX = wireX;
            WireZ = wireZ;
            RotationYRad = rotationYRad;
            Scale = scale;
            MeshName = meshName ?? "";
            AggressiveLod = aggressiveLod;
        }
    }

    /// <summary>A flat coloured lot / road quad in wire-space (centre + size in wire metres).</summary>
    public readonly struct GroundPatchDef
    {
        public readonly double WireX;
        public readonly double WireZ;
        public readonly double SizeX;
        public readonly double SizeZ;
        public readonly Color Color;

        public GroundPatchDef(double wireX, double wireZ, double sizeX, double sizeZ, Color color)
        {
            WireX = wireX;
            WireZ = wireZ;
            SizeX = sizeX;
            SizeZ = sizeZ;
            Color = color;
        }
    }

    /// <summary>
    /// One Kenney road mesh tile in absolute wire XZ. Catalog stem required;
    /// empty catalog → <see cref="TownBuilder"/> skips (colour slabs remain).
    /// Native Kenney footprint ≈ 1×1 m; <see cref="Scale"/> stretches to artery width.
    /// </summary>
    public readonly struct RoadTileDef
    {
        public readonly double WireX;
        public readonly double WireZ;
        public readonly float RotationYRad;
        public readonly float Scale;
        public readonly string MeshName;

        public RoadTileDef(double wireX, double wireZ, float rotationYRad, float scale, string meshName)
        {
            WireX = wireX;
            WireZ = wireZ;
            RotationYRad = rotationYRad;
            Scale = scale;
            MeshName = meshName ?? "";
        }
    }

    /// <summary>
    /// Static town layout data — placeholder buildings, nature props, roads, and zone lots
    /// for the 10 regions. Building offsets are wire XZ from each region anchor (§6.3);
    /// nature props use absolute wire XZ. <see cref="TownBuilder"/> transforms via
    /// <c>WireCoordinateTransform</c>.
    /// </summary>
    public static class TownVisualLayout
    {
        private const float Pi = Mathf.PI;

        private static PlaceholderDef P(
            double dx, double dz, float rotY = 0f, float scale = 1f, PlaceholderShape shape = PlaceholderShape.Building)
            => new(dx, dz, rotY, scale, shape);

        private static GroundPatchDef Patch(double x, double z, double w, double d, Color color)
            => new(x, z, w, d, color);

        private static NaturePropDef N(
            double x, double z, string mesh, float scale = 1f, float rotY = 0f, bool aggressiveLod = true)
            => new(x, z, rotY, scale, mesh, aggressiveLod);

        private static RoadTileDef R(
            double x, double z, string mesh, float scale = 7.5f, float rotY = 0f)
            => new(x, z, rotY, scale, mesh);

        private static readonly Color ParkPath = new(0.54f, 0.58f, 0.53f);
        private static readonly Color DockPlank = new(0.55f, 0.48f, 0.38f);
        private static readonly Color Sidewalk = new(0.58f, 0.58f, 0.56f);

        /// <summary>
        /// Zone lots blend toward the grass base so districts read as tinted ground,
        /// not a saturated debug color board next to the roads.
        /// </summary>
        private static Color ZoneTint(float r, float g, float b, float towardGrass = 0.4f)
            => Color.Lerp(new Color(r, g, b), TownPalette.Grass, towardGrass);

        /// <summary>
        /// Colour-slab roads / paths spanning the built town (always built).
        /// Main arteries + branches; mesh overlays in <see cref="RoadTiles"/> when catalog has roads.
        /// </summary>
        public static readonly GroundPatchDef[] Roads =
        {
            // Main E–W artery + N–S spine (widened for readability)
            Patch(8, 0, 100, 7.5, TownPalette.Road),
            Patch(0, 8, 7.5, 72, TownPalette.Road),
            // Soft sidewalk shoulders along main E–W (visual only; still NavMesh-friendly slabs)
            Patch(8, 4.6, 96, 1.4, Sidewalk),
            Patch(8, -4.6, 96, 1.4, Sidewalk),
            // Market / bakery / workshop branch
            Patch(36, 0, 18, 5, TownPalette.RoadAccent),
            Patch(44, -18, 5, 28, TownPalette.RoadAccent),
            Patch(42, -36, 16, 5, TownPalette.RoadAccent),
            Patch(36, -12, 14, 5, TownPalette.RoadAccent),
            // Restaurant spur
            Patch(44, 10, 20, 5, TownPalette.RoadAccent),
            Patch(52, 14, 5, 14, TownPalette.RoadAccent),
            // Residential / dock
            Patch(10, 28, 5, 24, TownPalette.RoadAccent),
            Patch(18, 36, 16, 5, TownPalette.RoadAccent),
            Patch(4, 38, 20, 5, TownPalette.RoadAccent),
            Patch(-8, 36, 5, 12, TownPalette.RoadAccent),
            // Town hall / library
            Patch(-12, -10, 20, 5, TownPalette.RoadAccent),
            Patch(-22, -14, 5, 14, TownPalette.RoadAccent),
            Patch(-32, -8, 18, 5, TownPalette.RoadAccent),
            Patch(-40, -6, 5, 10, TownPalette.RoadAccent),
            // Park paths
            Patch(-16, 8, 20, 3.5, ParkPath),
            Patch(-32, 8, 3.5, 16, ParkPath),
            Patch(-20, 20, 18, 3.5, ParkPath),
            // Dock planks
            Patch(-8, 42, 14, 3.5, DockPlank),
            Patch(-4, 40, 3.5, 8, DockPlank),
        };

        /// <summary>
        /// Kenney City Kit (Roads) mesh overlays aligned to <see cref="Roads"/> main arteries.
        /// Tile ≈ 1×1 m native; scale ~7.5 matches widened main slabs. Colliders stripped at spawn.
        /// </summary>
        public static readonly RoadTileDef[] RoadTiles =
        {
            // Plaza crossroads (main E–W × N–S)
            R(0, 0, "road-crossroad", 7.5f),
            R(0, 0, "road-crossing", 7.5f, Pi * 0.5f),

            // Main E–W artery (centre z=0; skip plaza cell)
            R(-37.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(-30, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(-22.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(-15, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(-7.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(7.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(15, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(22.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(30, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(37.5, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(45, 0, "road-straight", 7.5f, Pi * 0.5f),
            R(52.5, 0, "road-straight", 7.5f, Pi * 0.5f),

            // Main N–S spine (centre x=0; skip plaza cell)
            R(0, -30, "road-straight", 7.5f),
            R(0, -22.5, "road-straight", 7.5f),
            R(0, -15, "road-straight", 7.5f),
            R(0, -7.5, "road-straight", 7.5f),
            R(0, 7.5, "road-straight", 7.5f),
            R(0, 15, "road-straight", 7.5f),
            R(0, 22.5, "road-straight", 7.5f),
            R(0, 30, "road-straight", 7.5f),
            R(0, 37.5, "road-straight", 7.5f),

            // Sidewalk shoulders along main E–W
            R(-22.5, 4.6, "road-side", 1.4f, Pi * 0.5f),
            R(-7.5, 4.6, "road-side", 1.4f, Pi * 0.5f),
            R(15, 4.6, "road-side", 1.4f, Pi * 0.5f),
            R(37.5, 4.6, "road-side", 1.4f, Pi * 0.5f),
            R(-22.5, -4.6, "road-side", 1.4f, Pi * 0.5f),
            R(-7.5, -4.6, "road-side", 1.4f, Pi * 0.5f),
            R(15, -4.6, "road-side", 1.4f, Pi * 0.5f),
            R(37.5, -4.6, "road-side", 1.4f, Pi * 0.5f),

            // Market / bakery / workshop branch junctions
            R(36, 0, "road-intersection", 5f, Pi * 0.5f),
            R(44, -18, "road-bend", 5f, Pi),
            R(42, -36, "road-bend-sidewalk", 5f, -Pi * 0.5f),
            R(48, -36, "tile-low", 4f),

            // Town hall / library spur
            R(-12, -10, "road-intersection", 5f),
            R(-32, -8, "road-bend", 5f, Pi * 0.5f),
            R(-40, -6, "road-bend-sidewalk", 5f, Pi),

            // Residential / dock approach
            R(10, 28, "road-bend", 5f, -Pi * 0.5f),
            R(-8, 36, "road-intersection", 5f),
            R(-8, 42, "tile-low", 4f),
            R(-4, 40, "road-crossing", 4f),
        };

        /// <summary>Per-region ground lots (one per gameplay region).</summary>
        public static readonly GroundPatchDef[] Zones =
        {
            Patch(0, 0, 14, 14, ZoneTint(0.72f, 0.77f, 0.81f)),
            Patch(36, 0, 16, 14, ZoneTint(0.77f, 0.72f, 0.66f)),
            Patch(52, 20, 14, 12, ZoneTint(0.83f, 0.77f, 0.69f)),
            Patch(36, -22, 14, 12, ZoneTint(0.69f, 0.72f, 0.75f)),
            Patch(18, 38, 18, 16, ZoneTint(0.66f, 0.77f, 0.63f)),
            Patch(-22, -20, 16, 14, ZoneTint(0.69f, 0.72f, 0.78f)),
            Patch(-32, 12, 18, 14, ZoneTint(0.42f, 0.68f, 0.42f)),
            Patch(-40, -8, 14, 12, ZoneTint(0.58f, 0.62f, 0.78f)),
            Patch(48, -36, 14, 12, ZoneTint(0.72f, 0.62f, 0.52f)),
            Patch(-8, 40, 16, 12, ZoneTint(0.48f, 0.62f, 0.72f)),
            // 心动营地 — night ritual stage (decision #28); keep darker for the fire ring,
            // just soften the hard edge against grass.
            Patch(-56, 36, 18, 16, ZoneTint(0.28f, 0.36f, 0.28f, 0.25f)),
        };

        /// <summary>Gameplay regions with denser placeholder clusters (§6.3) + 心动营地.</summary>
        public static readonly RegionVisualDef[] Regions =
        {
            new("广场", new Color(0.61f, 0.64f, 0.68f), new[]
            {
                // Keep building centres off the 7.5 m E–W (z≈0) / N–S (x≈0) arteries.
                P(-5.5, -5.5, Pi / 2f), P(5.5, -5.5, -Pi / 2f), P(-5.5, 5.5, Pi), P(5.5, 5.5),
                P(-4, -5.5, Pi, 0.95f), P(4, 5.5, 0f, 0.95f), P(-5.5, 5, Pi / 2f, 0.9f), P(5.5, -5, -Pi / 2f, 0.9f),
                // |offset| ≥ 3.6 clears 7.5 m artery half-width (see PlazaBuildings_ClearMainArteries).
                P(-4, 4, Pi / 4f, 0.88f), P(4, 4, -Pi / 4f, 0.88f), P(-4, -4, 3f * Pi / 4f, 0.88f), P(4, -4, -3f * Pi / 4f, 0.88f),
                P(-2, 1, 0f, 0.8f, PlaceholderShape.Disc), P(2, -1, 0.8f, 0.8f, PlaceholderShape.Disc),
                P(0, 2.5, 1.5f, 0.8f, PlaceholderShape.Disc), P(-1, -2.5, 0.3f, 0.9f, PlaceholderShape.FlatProp),
                P(1.5, 0.5, 0.6f, 0.75f, PlaceholderShape.FlatProp),
            }),
            new("市场", new Color(0.85f, 0.47f, 0.02f), new[]
            {
                P(-5.5, -4.5, Pi), P(-2.5, -4.5, Pi), P(0.5, -4.5, Pi, 0.95f), P(3.5, -4.5, Pi, 0.95f), P(6, -4, Pi, 0.9f),
                P(-5.5, 4.5), P(-2.5, 4.5, 0f, 0.95f), P(0.5, 4.5, 0f, 0.95f), P(3.5, 4.5, 0f, 0.95f), P(6, 4, 0f, 0.9f),
                P(-6.5, 0, Pi / 2f, 0.9f), P(6.5, -1, -Pi / 2f, 0.9f), P(-6.5, 2.5, Pi / 2f, 0.85f),
                P(0, 1, Pi / 6f, 1.1f, PlaceholderShape.FlatProp), P(-3, 0, Pi / 2f, 1.0f, PlaceholderShape.FlatProp),
                P(3, 0, -Pi / 2f, 1.0f, PlaceholderShape.FlatProp), P(3, 2, 0f, 0.85f, PlaceholderShape.Disc),
                P(-3, -2, 1.0f, 0.85f, PlaceholderShape.Disc), P(1, -2, 0.4f, 0.8f, PlaceholderShape.Disc),
            }),
            new("餐厅", new Color(0.86f, 0.15f, 0.15f), new[]
            {
                P(0, 2.5, -Pi / 5f, 1.15f), P(-4.5, -1, Pi / 3f, 1.05f), P(4.5, -1, -Pi / 3f, 1.0f),
                P(-4.5, 3.5, Pi / 4f, 0.95f), P(4.5, 3.5, -Pi / 4f, 0.95f), P(0, -4.5, Pi, 0.9f),
                P(-5.5, -4, 3f * Pi / 4f, 0.88f), P(5.5, -4, -3f * Pi / 4f, 0.88f),
                P(-2.5, 0, Pi / 6f, 0.92f), P(2.5, 0, -Pi / 6f, 0.92f),
                P(-2, 4.5, 0.5f, 0.8f, PlaceholderShape.Disc), P(1, 4.5, 1.2f, 0.8f, PlaceholderShape.Disc),
                P(3, 3.5, 2.0f, 0.8f, PlaceholderShape.Disc), P(2, -3, Pi, 0.85f, PlaceholderShape.FlatProp),
                P(-2, -3, 0.2f, 0.85f, PlaceholderShape.FlatProp),
            }),
            new("面包店", new Color(0.63f, 0.38f, 0.03f), new[]
            {
                P(-4.5, 0, Pi / 2f, 1.1f), P(4.5, 0, -Pi / 2f, 1.1f), P(0, -4.5, Pi, 1.05f),
                P(-2.5, 3.5, 0f, 0.95f), P(2.5, 3.5, -Pi / 6f, 0.9f), P(-5.5, -3, Pi / 4f, 0.9f), P(5.5, -3, -Pi / 4f, 0.9f),
                P(0, 4.5, 0f, 0.88f), P(-3, -2, Pi / 3f, 0.9f), P(3, -2, -Pi / 3f, 0.9f),
                P(3.5, 3, -Pi / 6f, 0.9f, PlaceholderShape.FlatProp), P(-3.5, 3, Pi / 3f, 0.85f, PlaceholderShape.FlatProp),
                P(1, -2, 0f, 0.8f, PlaceholderShape.Disc), P(-1, 1, 1.1f, 0.75f, PlaceholderShape.Disc),
            }),
            new("住宅区", new Color(0.23f, 0.51f, 0.96f), new[]
            {
                P(-5, -5.5, Pi, 0.95f), P(-1.5, -5.5, Pi, 0.95f), P(2, -5.5, Pi, 0.93f), P(5.5, -5.5, Pi, 0.93f),
                P(-5.5, -2, Pi / 2f, 0.95f), P(-2, -2, Pi / 4f, 0.93f), P(1.5, -2, -Pi / 4f, 0.93f), P(5, -2, -Pi / 2f, 0.95f),
                P(-3.5, 1.5, Pi / 2f, 0.93f), P(0, 1.5, 0f, 0.95f), P(3.5, 1.5, -Pi / 2f, 0.93f),
                P(-5, 4.5, 3f * Pi / 4f, 0.93f), P(-1.5, 4.5, 0f, 0.95f), P(2, 4.5, 0f, 0.93f), P(5.5, 4.5, -3f * Pi / 4f, 0.93f),
                P(-5.5, 1, Pi / 2f, 0.9f), P(5.5, 1, -Pi / 2f, 0.9f),
            }),
            new("镇政厅", new Color(0.39f, 0.40f, 0.95f), new[]
            {
                P(0, -2.5, 0f, 1.3f, PlaceholderShape.Tower), P(-5.5, 0, Pi / 6f, 1.05f, PlaceholderShape.Tower),
                P(5.5, 0, -Pi / 6f, 1.0f, PlaceholderShape.Tower), P(0, 1, 0f, 1.1f, PlaceholderShape.Tower),
                P(-4.5, 4.5, Pi, 0.95f), P(4.5, 4.5, Pi, 0.95f), P(-5.5, -4.5, Pi / 3f, 0.9f), P(5.5, -4.5, -Pi / 3f, 0.9f),
                P(0, 5, 0f, 0.85f, PlaceholderShape.Tower), P(-2.5, -4, Pi / 5f, 0.9f), P(2.5, -4, -Pi / 5f, 0.9f),
                P(-2, 3.5, 0f, 0.75f, PlaceholderShape.Disc), P(2, 3.5, 1.2f, 0.75f, PlaceholderShape.Disc),
            }),
            new("公园", new Color(0.13f, 0.77f, 0.37f), new[]
            {
                // Landmark pavilion + benches (nature trees/bushes live in NatureProps)
                P(0, 0, 0f, 0.95f), P(-4.5, -4.5, Pi / 4f, 0.9f, PlaceholderShape.FlatProp),
                P(3.5, -3.5, -Pi / 3f, 0.9f, PlaceholderShape.FlatProp),
                P(-2.5, 4.5, Pi / 6f, 0.85f, PlaceholderShape.FlatProp), P(0, -5, Pi, 0.8f, PlaceholderShape.FlatProp),
                P(4.5, 3.5, 0.5f, 0.75f, PlaceholderShape.Disc), P(-5.5, 2.5, 1.2f, 0.75f, PlaceholderShape.Disc),
                P(2.5, 1.5, 2.0f, 0.7f, PlaceholderShape.Disc),
            }),
            new("图书馆", new Color(0.45f, 0.52f, 0.82f), new[]
            {
                P(0, 0, 0f, 1.35f, PlaceholderShape.Tower), P(-5, -2, Pi / 5f, 1.05f), P(5, -2, -Pi / 5f, 1.05f),
                P(-4.5, 3.5, Pi, 0.95f), P(4.5, 3.5, Pi, 0.95f), P(0, -4.5, Pi, 1.0f),
                P(-5.5, 1, Pi / 2f, 0.9f), P(5.5, 1, -Pi / 2f, 0.9f),
                P(-2, 4.5, 0.3f, 0.8f, PlaceholderShape.Disc), P(2, 4.5, 1.0f, 0.8f, PlaceholderShape.Disc),
                P(0, 3, 0f, 0.85f, PlaceholderShape.FlatProp), P(-3, -4, Pi / 4f, 0.85f, PlaceholderShape.FlatProp),
            }),
            new("工坊", new Color(0.72f, 0.48f, 0.28f), new[]
            {
                P(0, 1, 0f, 1.2f), P(-4.5, -2, Pi / 3f, 1.05f), P(4.5, -2, -Pi / 3f, 1.05f),
                P(-5, 3, Pi / 4f, 0.95f), P(5, 3, -Pi / 4f, 0.95f), P(0, -4.5, Pi, 1.0f),
                P(-3, 4.5, 0f, 0.9f), P(3, 4.5, 0f, 0.9f), P(-5.5, -4, 2f * Pi / 3f, 0.88f),
                P(2, 0, -Pi / 6f, 0.95f, PlaceholderShape.FlatProp), P(-2, 0, Pi / 6f, 0.95f, PlaceholderShape.FlatProp),
                P(0, 3.5, 0.5f, 0.8f, PlaceholderShape.Disc), P(4, -4, 1.2f, 0.85f, PlaceholderShape.FlatProp),
            }),
            new("码头", new Color(0.28f, 0.58f, 0.78f), new[]
            {
                P(0, -1, 0f, 1.15f), P(-5, 0, Pi / 2f, 1.0f), P(5, 0, -Pi / 2f, 1.0f),
                P(-4, 3.5, Pi, 0.95f), P(4, 3.5, Pi, 0.95f), P(0, 4, 0f, 0.9f),
                P(-5.5, -3.5, Pi / 3f, 0.9f), P(5.5, -3.5, -Pi / 3f, 0.9f),
                P(-2, 1.5, 0f, 0.85f, PlaceholderShape.FlatProp), P(2, 1.5, 0f, 0.85f, PlaceholderShape.FlatProp),
                P(0, 2.5, 0.4f, 0.8f, PlaceholderShape.Disc), P(-3, -4, 1.0f, 0.85f, PlaceholderShape.FlatProp),
                P(3, -4, -1.0f, 0.85f, PlaceholderShape.FlatProp), P(0, -4.5, Pi, 0.95f, PlaceholderShape.FlatProp),
            }),
            // Campfire centre + seat ring + reveal platform (primitive fallbacks OK).
            new("心动营地", new Color(0.92f, 0.48f, 0.18f), new[]
            {
                P(0, 0, 0f, 0.55f, PlaceholderShape.Disc), // campfire
                P(0, 0, 0f, 0.35f, PlaceholderShape.Tower), // flame column
                P(4.2, 0, Pi / 2f, 0.55f, PlaceholderShape.Disc),
                P(2.1, 3.6, Pi / 6f, 0.55f, PlaceholderShape.Disc),
                P(-2.1, 3.6, -Pi / 6f, 0.55f, PlaceholderShape.Disc),
                P(-4.2, 0, -Pi / 2f, 0.55f, PlaceholderShape.Disc),
                P(-2.1, -3.6, Pi, 0.55f, PlaceholderShape.Disc),
                P(2.1, -3.6, Pi, 0.55f, PlaceholderShape.Disc),
                P(0, 6.5, 0f, 1.1f, PlaceholderShape.FlatProp), // reveal board
                P(-1.5, 6.5, 0f, 0.7f, PlaceholderShape.FlatProp),
                P(1.5, 6.5, 0f, 0.7f, PlaceholderShape.FlatProp),
                P(0, -6, Pi, 0.85f, PlaceholderShape.FlatProp),
            }),
        };

        /// <summary>
        /// Absolute wire-space foliage (Kenney Nature Kit stems). Park dense; main-road edges sparse.
        /// Offsets keep trunks clear of road centre-lines so NavMesh stays walkable.
        /// </summary>
        public static readonly NaturePropDef[] NatureProps =
        {
            // --- 公园 lot (~-32,12) + paths — dense canopy ---
            N(-38, 16, "tree_oak", 1.15f, 0.3f),
            N(-36, 8, "tree_default", 1.05f, 1.1f),
            N(-28, 18, "tree_tall", 1.1f, 2.0f),
            N(-26, 10, "tree_pineDefaultA", 1.0f, 0.7f),
            N(-34, 18, "tree_oak", 0.95f, 2.4f),
            N(-30, 6, "tree_small", 0.9f, 0.2f),
            N(-24, 14, "tree_default", 1.0f, 1.6f),
            N(-38, 10, "tree_tall", 0.95f, 0.9f),
            N(-22, 8, "tree_small", 0.85f, 2.8f),
            N(-40, 14, "tree_pineDefaultA", 0.9f, 1.4f),
            N(-32, 18, "plant_bushDetailed", 1.1f, 0.4f),
            N(-28, 16, "plant_bush", 1.0f, 1.0f),
            N(-36, 14, "plant_bushSmall", 1.05f, 2.2f),
            N(-30, 12, "plant_bush", 0.95f, 0.6f),
            N(-34, 8, "plant_bushDetailed", 1.0f, 1.8f),
            N(-26, 18, "plant_bushSmall", 1.0f, 2.5f),
            N(-38, 18, "grass_large", 1.2f, 0.1f, aggressiveLod: false),
            N(-28, 8, "grass_large", 1.1f, 1.3f, aggressiveLod: false),
            N(-24, 16, "flower_yellowA", 1.0f, 0.5f, aggressiveLod: false),
            N(-36, 16, "flower_yellowA", 0.95f, 2.1f, aggressiveLod: false),
            N(-32, 6, "grass_large", 1.0f, 0.8f, aggressiveLod: false),
            // Park path edges (avoid path centres at z≈8 / x≈-32)
            N(-22, 10, "tree_small", 0.8f, 0.4f),
            N(-18, 12, "plant_bush", 0.9f, 1.5f),
            N(-20, 16, "tree_default", 0.9f, 2.3f),
            N(-14, 10, "plant_bushSmall", 1.0f, 0.9f),

            // --- Main E–W road shoulders (road centre z=0; trees at |z|≥6) ---
            N(-20, 7, "tree_small", 0.75f, 0.2f),
            N(-8, -7, "tree_small", 0.7f, 1.1f),
            N(12, 7.5, "tree_pineDefaultA", 0.7f, 2.0f),
            N(28, -7.5, "tree_small", 0.75f, 0.6f),
            N(48, 7, "tree_default", 0.7f, 1.7f),
            N(-4, 7, "plant_bushSmall", 0.85f, 0.3f),
            N(20, -7, "plant_bush", 0.8f, 2.4f),

            // --- Plaza fringe (light accent, keep square open) ---
            N(-6, -6, "plant_bushSmall", 0.9f, 0.5f),
            N(6, 6, "plant_bush", 0.85f, 1.9f),
            N(-5, 7, "flower_yellowA", 0.9f, 1.2f, aggressiveLod: false),
        };

        /// <summary>
        /// Grass base footprint in wire metres. Sized past the built town so bird's-eye
        /// corners land on grass (or <see cref="TownBuilder"/> horizon fill), not dark skybox ground.
        /// </summary>
        public static readonly Vector2 GroundSize = new(220f, 180f);

        /// <summary>Activity core (plaza ↔ market) for camera framing (wire space).</summary>
        public static readonly Vector3 ViewCenterWire = new(12f, 0f, 0f);

        /// <summary>
        /// Default bird's-eye basis (wire space). Sets the look direction (oblique ~47°,
        /// not straight-down) applied at the view centre / shoot landmark.
        /// </summary>
        public static readonly Vector3 CameraWire = new(16f, 18f, 16f);

        /// <summary>Scroll-zoom distance limits along the bird look ray (metres from view centre).</summary>
        public const float BirdZoomMinDistance = 10f;
        public const float BirdZoomMaxDistance = 56f;
        public const float BirdZoomDefaultDistance = 22f;

        /// <summary>Offline shoot framing distance — mid range: district + surroundings.</summary>
        public const float BirdZoomShootDistance = 20f;
    }
}
