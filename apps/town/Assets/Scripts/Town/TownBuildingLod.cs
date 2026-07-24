using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Lightweight distance LOD for runtime-spawned buildings and nature props.
    /// Does not rebuild the scene graph: far objects drop to a single low-detail proxy
    /// (or hide when beyond <see cref="CullDistance"/>), keeping Offline Demo / scripted
    /// watch paths intact while cutting draw cost on WebGL / mid-range GPUs.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownBuildingLod : MonoBehaviour
    {
        /// <summary>
        /// Buildings on the expanded grass footprint: full mesh near camera; mid-distance → LodLow cube.
        /// Tuned so default bird (~24 m) still shows nearby full meshes while far districts proxy.
        /// </summary>
        public const float DefaultLowDetailDistance = 32f;
        public const float DefaultCullDistance = 78f;

        /// <summary>
        /// Nature trees/bushes: no mid-distance LodLow cubes (those read as "green blocks").
        /// Low == cull so <see cref="LevelForDistance"/> jumps 0 → 2. Mildly relaxed so
        /// park canopy stays in bird view; far districts still drop.
        /// </summary>
        public const float NatureLowDetailDistance = 58f;
        public const float NatureCullDistance = 58f;

        /// <summary>Grass / flowers / micro props — cull sooner than canopy trees.</summary>
        public const float NatureMicroLowDetailDistance = 34f;
        public const float NatureMicroCullDistance = 34f;

        [SerializeField]
        private float lowDetailDistance = DefaultLowDetailDistance;

        [SerializeField]
        private float cullDistance = DefaultCullDistance;

        private Renderer[] detailRenderers;
        private GameObject lowProxy;
        private int appliedLevel = -1;
        private float nextEvalAt;

        /// <summary>
        /// Attach LOD to a spawned building. Safe on primitives and catalog prefabs.
        /// Idempotent when already present.
        /// </summary>
        public static TownBuildingLod Ensure(GameObject building)
        {
            return Ensure(building, DefaultLowDetailDistance, DefaultCullDistance);
        }

        /// <summary>Attach LOD with custom distances (nature uses tighter cull).</summary>
        public static TownBuildingLod Ensure(GameObject building, float lowDetail, float cull)
        {
            if (building == null)
            {
                return null;
            }

            TownBuildingLod existing = building.GetComponent<TownBuildingLod>();
            if (existing != null)
            {
                existing.lowDetailDistance = lowDetail;
                existing.cullDistance = cull;
                return existing;
            }

            TownBuildingLod lod = building.AddComponent<TownBuildingLod>();
            lod.lowDetailDistance = lowDetail;
            lod.cullDistance = cull;
            lod.CaptureDetail();
            lod.EnsureLowProxy();
            lod.ApplyLevel(0, force: true);
            return lod;
        }

        /// <summary>Nature-tuned LOD (more aggressive than buildings).</summary>
        public static TownBuildingLod EnsureNature(GameObject prop, bool aggressive = true)
        {
            if (aggressive)
            {
                return Ensure(prop, NatureLowDetailDistance, NatureCullDistance);
            }

            return Ensure(prop, NatureMicroLowDetailDistance, NatureMicroCullDistance);
        }

        /// <summary>LOD level from camera distance: 0 = full, 1 = low proxy, 2 = culled.</summary>
        public static int LevelForDistance(float distance, float lowDetail, float cull)
        {
            if (distance < 0f)
            {
                distance = 0f;
            }

            float low = lowDetail > 1f ? lowDetail : DefaultLowDetailDistance;
            float far = cull > low ? cull : low + 1f;
            if (distance >= far)
            {
                return 2;
            }

            if (distance >= low)
            {
                return 1;
            }

            return 0;
        }

        internal void CaptureDetail()
        {
            detailRenderers = GetComponentsInChildren<Renderer>(true);
        }

        internal void EnsureLowProxy()
        {
            if (lowProxy != null)
            {
                return;
            }

            Bounds bounds = ComputeWorldBounds();
            lowProxy = GameObject.CreatePrimitive(PrimitiveType.Cube);
            lowProxy.name = "LodLow";
            lowProxy.transform.SetParent(transform, false);

            Vector3 localCenter = transform.InverseTransformPoint(bounds.center);
            Vector3 lossy = transform.lossyScale;
            float sx = Mathf.Abs(lossy.x) < 0.001f ? 1f : Mathf.Abs(lossy.x);
            float sy = Mathf.Abs(lossy.y) < 0.001f ? 1f : Mathf.Abs(lossy.y);
            float sz = Mathf.Abs(lossy.z) < 0.001f ? 1f : Mathf.Abs(lossy.z);
            lowProxy.transform.localPosition = localCenter;
            lowProxy.transform.localRotation = Quaternion.identity;
            lowProxy.transform.localScale = new Vector3(
                Mathf.Max(0.4f, bounds.size.x / sx),
                Mathf.Max(0.4f, bounds.size.y / sy),
                Mathf.Max(0.4f, bounds.size.z / sz));

            if (lowProxy.TryGetComponent(out Collider col))
            {
                if (Application.isPlaying)
                {
                    Object.Destroy(col);
                }
                else
                {
                    Object.DestroyImmediate(col);
                }
            }

            // Match first detail tint when possible.
            if (detailRenderers != null && detailRenderers.Length > 0 && detailRenderers[0] != null)
            {
                Renderer proxyRenderer = lowProxy.GetComponent<Renderer>();
                if (proxyRenderer != null)
                {
                    proxyRenderer.sharedMaterial = detailRenderers[0].sharedMaterial;
                    var block = new MaterialPropertyBlock();
                    detailRenderers[0].GetPropertyBlock(block);
                    proxyRenderer.SetPropertyBlock(block);
                }
            }

            lowProxy.SetActive(false);
        }

        private void LateUpdate()
        {
            if (Time.unscaledTime < nextEvalAt)
            {
                return;
            }

            // Throttle + stagger: many props share the same camera; avoid sync spikes.
            float stagger = (GetInstanceID() & 7) * 0.03f;
            nextEvalAt = Time.unscaledTime + 0.28f + stagger;

            Camera cam = Camera.main;
            if (cam == null)
            {
                return;
            }

            float distance = Vector3.Distance(cam.transform.position, transform.position);
            float low = lowDetailDistance;
            float cull = cullDistance;
#if UNITY_WEBGL && !UNITY_EDITOR
            // Tiny pull-in only — parks stay fuller; far bird districts still cull.
            low *= 0.98f;
#endif
            int level = LevelForDistance(distance, low, cull);
            ApplyLevel(level, force: false);
        }

        internal void ApplyLevel(int level, bool force)
        {
            if (!force && level == appliedLevel)
            {
                return;
            }

            appliedLevel = level;
            bool showDetail = level == 0;
            bool showLow = level == 1;

            if (detailRenderers != null)
            {
                for (int i = 0; i < detailRenderers.Length; i++)
                {
                    Renderer r = detailRenderers[i];
                    if (r == null)
                    {
                        continue;
                    }

                    // Never toggle the low proxy via the detail list.
                    if (lowProxy != null && r.transform.IsChildOf(lowProxy.transform))
                    {
                        continue;
                    }

                    if (r.gameObject == lowProxy)
                    {
                        continue;
                    }

                    r.enabled = showDetail;
                }
            }

            if (lowProxy != null)
            {
                lowProxy.SetActive(showLow);
            }
        }

        private Bounds ComputeWorldBounds()
        {
            if (detailRenderers == null || detailRenderers.Length == 0)
            {
                return new Bounds(transform.position, Vector3.one * 2f);
            }

            bool any = false;
            Bounds bounds = default;
            for (int i = 0; i < detailRenderers.Length; i++)
            {
                Renderer r = detailRenderers[i];
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

            return any ? bounds : new Bounds(transform.position, Vector3.one * 2f);
        }
    }
}
