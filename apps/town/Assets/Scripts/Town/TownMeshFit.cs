using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Ground-fit + height normalisation for mixed Quaternius FBX / Kenney GLB prefabs.
    /// Catalog meshes often arrive with arbitrary pivot / authoring scale; layout
    /// <see cref="PlaceholderDef.Scale"/> is a relative intent, not a raw localScale.
    /// </summary>
    public static class TownMeshFit
    {
        public const float GroundY = 0.02f;
        public const float QuaterniusBuildingHeight = 5.2f;
        public const float KenneyBuildingHeight = 4.0f;
        public const float NatureTreeHeight = 3.0f;
        public const float NatureBushHeight = 1.1f;
        public const float RoadDeckY = 0.08f;

        /// <summary>Quaternius LowPoly Buildings stems (FE-18 landmarks).</summary>
        public static bool IsQuaterniusStem(string stem)
        {
            if (string.IsNullOrEmpty(stem))
            {
                return false;
            }

            return stem.Equals("Bank", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("Flat", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("Flat2", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("Hospital", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("House", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("House2", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("House3", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("House4", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("House5", System.StringComparison.OrdinalIgnoreCase)
                || stem.Equals("Shop", System.StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Uniform-scale a building so world height ≈ target, then sit the AABB on
        /// <see cref="GroundY"/>. <paramref name="layoutScale"/> is the relative
        /// PlaceholderDef scale (1 = default landmark size).
        /// </summary>
        public static void FitBuilding(GameObject actor, float layoutScale, string meshStem)
        {
            if (actor == null)
            {
                return;
            }

            float target = IsQuaterniusStem(meshStem)
                ? QuaterniusBuildingHeight
                : KenneyBuildingHeight;
            target *= Mathf.Clamp(layoutScale, 0.35f, 2.2f);
            FitUniformHeight(actor, target, GroundY);
        }

        /// <summary>Fit a nature prop (tree vs bush/flower) and ground it.</summary>
        public static void FitNature(GameObject actor, float layoutScale, string meshStem)
        {
            if (actor == null)
            {
                return;
            }

            bool isTree = !string.IsNullOrEmpty(meshStem)
                && meshStem.StartsWith("tree", System.StringComparison.OrdinalIgnoreCase);
            float target = isTree ? NatureTreeHeight : NatureBushHeight;
            target *= Mathf.Clamp(layoutScale, 0.35f, 2.0f);
            FitUniformHeight(actor, target, GroundY);
        }

        /// <summary>
        /// Apply intentional road tile scale, then pin the mesh deck to
        /// <see cref="RoadDeckY"/> (just above colour slabs).
        /// </summary>
        public static void FitRoad(GameObject actor, float layoutScale)
        {
            if (actor == null)
            {
                return;
            }

            float s = Mathf.Max(0.2f, layoutScale);
            actor.transform.localScale = Vector3.one * s;
            SnapMinY(actor, RoadDeckY);
        }

        /// <summary>Uniform scale so renderer AABB height matches <paramref name="targetHeight"/>.</summary>
        public static void FitUniformHeight(GameObject actor, float targetHeight, float minY)
        {
            if (actor == null || targetHeight < 0.05f)
            {
                return;
            }

            if (!TryWorldBounds(actor, out Bounds bounds) || bounds.size.y < 0.001f)
            {
                SnapMinY(actor, minY);
                return;
            }

            float current = bounds.size.y;
            float factor = targetHeight / current;
            // Guard against pathological FBX (cm vs m): clamp extreme corrections.
            factor = Mathf.Clamp(factor, 0.01f, 80f);
            actor.transform.localScale *= factor;
            SnapMinY(actor, minY);
        }

        /// <summary>Move actor so world AABB min.y == <paramref name="minY"/>.</summary>
        public static void SnapMinY(GameObject actor, float minY)
        {
            if (actor == null)
            {
                return;
            }

            if (!TryWorldBounds(actor, out Bounds bounds))
            {
                Vector3 p = actor.transform.position;
                actor.transform.position = new Vector3(p.x, minY, p.z);
                return;
            }

            float dy = minY - bounds.min.y;
            if (Mathf.Abs(dy) < 0.0001f)
            {
                return;
            }

            actor.transform.position += new Vector3(0f, dy, 0f);
        }

        public static bool TryWorldBounds(GameObject actor, out Bounds bounds)
        {
            bounds = default;
            if (actor == null)
            {
                return false;
            }

            Renderer[] renderers = actor.GetComponentsInChildren<Renderer>(true);
            bool any = false;
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer r = renderers[i];
                if (r == null)
                {
                    continue;
                }

                if (!any)
                {
                    bounds = r.bounds;
                    any = true;
                }
                else
                {
                    bounds.Encapsulate(r.bounds);
                }
            }

            return any;
        }
    }
}
