using UnityEngine;
using UnityEngine.AI;

namespace AgentTown.Town
{
    /// <summary>
    /// One resident NPC (§7 NpcLayer). Body is Xbot from <see cref="TownMeshCatalog"/> when present,
    /// else a placeholder capsule. Always keeps <see cref="NavMeshAgent"/>; tint via
    /// <see cref="MaterialPropertyBlock"/> on the primary renderer. Display-name labels are
    /// screen-space via <see cref="TownNameplateHud"/>.
    ///
    /// <para>Live and Replay/Offline both drive <c>NavMeshAgent.SetDestination</c> toward the
    /// snapshot goal (no whole-frame teleport on sync). Replay may pace agent speed to the
    /// playhead step window. If NavMesh is unavailable, falls back to Transform smoothing.</para>
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownNpc : MonoBehaviour
    {
        private const float BodyHeight = 1.8f;
        private const float SampleRadius = 4f;
        private const float BaseSpeed = 3.5f;
        private const float ArrivePadding = 1.15f;

        private NavMeshAgent agent;
        private Renderer bodyRenderer;
        private Transform bodyRoot;
        private MaterialPropertyBlock propertyBlock;
        private TownMeshCatalog meshCatalog;
        private bool catalogResolved;

        /// <summary>Transform-lerp fallback target when NavMesh pathing is unavailable.</summary>
        private Vector3? softTarget;
        private float softSpeed = BaseSpeed;

        public string AgentId { get; private set; } = "";

        /// <summary>Build the body, nav agent and (placeholder) animator. Call once right after spawn.</summary>
        public void Initialize(string agentId, Material sharedMaterial)
        {
            AgentId = agentId;

            agent = gameObject.AddComponent<NavMeshAgent>();
            agent.speed = BaseSpeed;
            agent.angularSpeed = 540f;
            agent.acceleration = 12f;
            agent.radius = 0.35f;
            agent.height = BodyHeight;
            agent.stoppingDistance = 0.25f;
            agent.autoBraking = true;

            GameObject body = TrySpawnXbotBody();
            bool usedCapsule = body == null;
            if (usedCapsule)
            {
                body = SpawnCapsuleBody();
            }

            ConfigureBodyRenderer(body, sharedMaterial, assignSharedMaterial: usedCapsule);
            if (body.GetComponent<Animator>() == null && body.GetComponentInChildren<Animator>() == null)
            {
                body.AddComponent<Animator>();
            }

            // Nameplates are screen-space via TownNameplateHud (WebGL CJK-safe).
        }

        /// <summary>
        /// Kept for call-site compatibility; visible labels are drawn by
        /// <see cref="TownNameplateHud"/> from session agent state.
        /// </summary>
        public void SetNameplate(string displayName, string subtitle, bool selected)
        {
            // Screen-space HUD owns nameplates — no world-space canvas here.
        }

        /// <summary>Inject a catalog for EditMode tests (skips Resources load).</summary>
        internal void SetMeshCatalogForTests(TownMeshCatalog catalog)
        {
            meshCatalog = catalog;
            catalogResolved = true;
        }

        private void Update()
        {
            TickSoftMove(Time.deltaTime);
        }

        /// <summary>
        /// Move toward <paramref name="worldPosition"/>.
        /// <paramref name="snap"/> warps (seed / hard reset only).
        /// Otherwise NavMesh <c>SetDestination</c>; when <paramref name="paceToTick"/>, speed is
        /// scaled so the agent can cover the step within the playhead window (high replay 倍率
        /// accelerates, never whole-frame teleport). NavMesh-unavailable → Transform lerp fallback.
        /// </summary>
        public void ApplyGoal(
            Vector3 worldPosition,
            bool snap = false,
            bool paceToTick = false,
            float playbackSpeed = 1f,
            float stepSeconds = 0.6f)
        {
            Vector3 target = SampleOnNavMesh(worldPosition);

            if (snap)
            {
                SoftClear();
                if (agent != null && agent.enabled)
                {
                    agent.Warp(target);
                    if (agent.isOnNavMesh)
                    {
                        agent.ResetPath();
                    }

                    agent.speed = BaseSpeed;
                    agent.acceleration = 12f;
                }
                else
                {
                    transform.position = target;
                }

                return;
            }

            float speed = ResolveSpeed(transform.position, target, paceToTick, playbackSpeed, stepSeconds);

            if (agent == null || !agent.enabled)
            {
                BeginSoftMove(target, speed);
                return;
            }

            if (!EnsureOnNavMesh())
            {
                BeginSoftMove(target, speed);
                return;
            }

            SoftClear();
            agent.speed = speed;
            agent.acceleration = Mathf.Max(speed * 4f, 12f);
            agent.SetDestination(target);
        }

        private float ResolveSpeed(
            Vector3 from,
            Vector3 to,
            bool paceToTick,
            float playbackSpeed,
            float stepSeconds)
        {
            if (!paceToTick)
            {
                return BaseSpeed;
            }

            float distance = Vector3.Distance(from, to);
            float window = Mathf.Max(0.05f, stepSeconds / Mathf.Max(playbackSpeed, 0.1f));
            return Mathf.Max(BaseSpeed, distance / window * ArrivePadding);
        }

        private bool EnsureOnNavMesh()
        {
            if (agent.isOnNavMesh)
            {
                return true;
            }

            if (NavMesh.SamplePosition(transform.position, out NavMeshHit hit, SampleRadius, NavMesh.AllAreas))
            {
                agent.Warp(hit.position);
                return agent.isOnNavMesh;
            }

            return false;
        }

        private void BeginSoftMove(Vector3 target, float speed)
        {
            if (agent != null && agent.enabled && agent.isOnNavMesh)
            {
                agent.ResetPath();
            }

            softTarget = target;
            softSpeed = Mathf.Max(BaseSpeed, speed);
        }

        private void SoftClear() => softTarget = null;

        private void TickSoftMove(float deltaTime)
        {
            if (softTarget == null)
            {
                return;
            }

            Vector3 target = softTarget.Value;
            Vector3 pos = transform.position;
            float step = softSpeed * Mathf.Max(deltaTime, 0f);
            if (Vector3.Distance(pos, target) <= step)
            {
                transform.position = target;
                softTarget = null;
                return;
            }

            transform.position = Vector3.MoveTowards(pos, target, step);
            Vector3 dir = target - pos;
            dir.y = 0f;
            if (dir.sqrMagnitude > 0.0001f)
            {
                transform.rotation = Quaternion.Slerp(
                    transform.rotation,
                    Quaternion.LookRotation(dir.normalized),
                    Mathf.Clamp01(deltaTime * 10f));
            }
        }

        private GameObject TrySpawnXbotBody()
        {
            EnsureCatalog();
            if (meshCatalog == null || !meshCatalog.HasXbot || meshCatalog.XbotPrefab == null)
            {
                return null;
            }

            try
            {
                GameObject body = Object.Instantiate(meshCatalog.XbotPrefab, transform);
                body.name = "Body";
                body.transform.localPosition = Vector3.zero;
                body.transform.localRotation = Quaternion.identity;
                FitCharacterToCapsule(body);
                StripCollidersRecursive(body);
                return body;
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[AgentTown] TownNpc: Xbot instantiate failed ({ex.Message}) — capsule fallback");
                return null;
            }
        }

        private GameObject SpawnCapsuleBody()
        {
            var body = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            body.name = "Body";
            body.transform.SetParent(transform, false);
            body.transform.localPosition = new Vector3(0f, BodyHeight / 2f, 0f);
            body.transform.localScale = new Vector3(0.5f, BodyHeight / 2f, 0.5f);
            if (body.TryGetComponent(out Collider collider))
            {
                DestroyCompat(collider);
            }

            return body;
        }

        private void ConfigureBodyRenderer(GameObject body, Material sharedMaterial, bool assignSharedMaterial)
        {
            bodyRoot = body.transform;
            bodyRenderer = body.GetComponent<Renderer>() ?? body.GetComponentInChildren<Renderer>();
            if (assignSharedMaterial && bodyRenderer != null && sharedMaterial != null)
            {
                bodyRenderer.sharedMaterial = sharedMaterial;
            }
        }

        private void EnsureCatalog()
        {
            if (catalogResolved)
            {
                return;
            }

            catalogResolved = true;
            meshCatalog = TownMeshCatalog.LoadOrNull();
        }

        /// <summary>Scale / lift imported character so feet sit near y=0 and height ≈ <see cref="BodyHeight"/>.</summary>
        private static void FitCharacterToCapsule(GameObject body)
        {
            Renderer[] renderers = body.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            float height = bounds.size.y;
            if (height < 0.01f)
            {
                return;
            }

            float scale = BodyHeight / height;
            body.transform.localScale = body.transform.localScale * scale;

            // Recompute after scale; lift so the lowest point sits on the ground plane.
            bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            float feetY = bounds.min.y - body.transform.parent.position.y;
            body.transform.localPosition = new Vector3(0f, -feetY, 0f);
        }

        /// <summary>EditMode-safe destroy: <see cref="Object.Destroy"/> is illegal outside play mode.</summary>
        private static void DestroyCompat(Object obj)
        {
            if (obj == null)
            {
                return;
            }

            if (Application.isPlaying)
            {
                Object.Destroy(obj);
            }
            else
            {
                Object.DestroyImmediate(obj);
            }
        }

        private static void StripCollidersRecursive(GameObject go)
        {
            Collider[] colliders = go.GetComponentsInChildren<Collider>(true);
            for (int i = 0; i < colliders.Length; i++)
            {
                DestroyCompat(colliders[i]);
            }
        }

        public void ApplyTint(Color color)
        {
            if (bodyRoot == null && bodyRenderer == null)
            {
                return;
            }

            propertyBlock ??= new MaterialPropertyBlock();
            Renderer[] renderers = bodyRoot != null
                ? bodyRoot.GetComponentsInChildren<Renderer>(true)
                : new[] { bodyRenderer };

            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer renderer = renderers[i];
                if (renderer == null)
                {
                    continue;
                }

                renderer.GetPropertyBlock(propertyBlock);
                propertyBlock.SetColor("_BaseColor", color);
                propertyBlock.SetColor("_Color", color);
                renderer.SetPropertyBlock(propertyBlock);
            }
        }

        private static Vector3 SampleOnNavMesh(Vector3 worldPosition)
        {
            return NavMesh.SamplePosition(worldPosition, out NavMeshHit hit, SampleRadius, NavMesh.AllAreas)
                ? hit.position
                : worldPosition;
        }
    }
}
