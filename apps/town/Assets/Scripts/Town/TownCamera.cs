using AgentTown.Simulation;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Bird's-eye observer camera with optional third-person tracking (§7 CameraRig).
    /// When <see cref="SimulationSession.TrackedAgentId"/> is set, follows that agent
    /// (Desktop <c>TrackingCamera</c> semantics). ESC or clearing track returns to bird's-eye.
    /// Scroll-wheel zooms the bird vantage within a limited range; HUD「鸟瞰」resets to the
    /// default panoramic framing. Prefers the live <see cref="TownNpc"/> transform so
    /// Offline scrubbing does not slide toward a stale snapshot point while the body is still pathing.
    /// </summary>
    [RequireComponent(typeof(Camera))]
    [DisallowMultipleComponent]
    public sealed class TownCamera : MonoBehaviour
    {
        private const float CameraHeight = 5f;
        private const float CameraDistance = 8f;
        private const float LookHeight = 1.8f;
        private const float LerpSpeed = 4f;
        private const float ScrollZoomSpeed = 6f;

        private SimulationSession session;
        private TownNpcManager npcManager;
        private Vector3 birdPosition;
        private Quaternion birdRotation;
        private bool hasBirdPose;
        private string prevTracked;
        private float birdDistance = TownVisualLayout.BirdZoomDefaultDistance;
        /// <summary>When true, <see cref="AgentTown.Show.CinematicDirector"/> owns the transform.</summary>
        private bool externalDrive;

        public void Bind(SimulationSession target)
        {
            session = target;
            Frame();
        }

        /// <summary>Programme mode: director drives the camera; free-look clears this.</summary>
        public void SetExternalDrive(bool enabled)
        {
            externalDrive = enabled;
        }

        private void Start()
        {
            session ??= SimulationSession.Instance;
            if (!hasBirdPose)
            {
                Frame();
            }
        }

        private void Update()
        {
            if (session == null || externalDrive)
            {
                return;
            }

            if (Input.GetKeyDown(KeyCode.Escape) && !string.IsNullOrEmpty(session.TrackedAgentId))
            {
                session.SetTrackedAgent(null);
                session.SetSelectedAgent(null);
            }

            if (string.IsNullOrEmpty(session.TrackedAgentId))
            {
                HandleBirdZoom();
            }
        }

        private void LateUpdate()
        {
            if (session == null || externalDrive)
            {
                return;
            }

            string tracked = session.TrackedAgentId;
            if (string.IsNullOrEmpty(tracked))
            {
                if (!string.IsNullOrEmpty(prevTracked) && hasBirdPose)
                {
                    ApplyBirdPose(immediate: true);
                }

                prevTracked = null;
                return;
            }

            if (!TryResolveTrackedPosition(tracked, out Vector3 npcPos))
            {
                return;
            }

            // Face along +Z when no yaw is available from the agent.
            Vector3 offset = new Vector3(0f, CameraHeight, -CameraDistance);
            Vector3 targetPos = npcPos + offset;
            Vector3 lookAt = npcPos + Vector3.up * LookHeight;

            float t = 1f - Mathf.Exp(-LerpSpeed * Time.deltaTime);
            transform.position = Vector3.Lerp(transform.position, targetPos, t);
            Quaternion lookRot = Quaternion.LookRotation((lookAt - targetPos).normalized, Vector3.up);
            transform.rotation = Quaternion.Slerp(transform.rotation, lookRot, t);
            prevTracked = tracked;
        }

        /// <summary>Place the camera at the default bird's-eye vantage and look at the town centre.</summary>
        public void Frame()
        {
            birdDistance = TownVisualLayout.BirdZoomDefaultDistance;
            ApplyBirdPose(immediate: true);
        }

        /// <summary>
        /// Bird vantage looking at a wire-space point (e.g. landmark region for shoot).
        /// Keeps the same look-ray distance as the default bird zoom.
        /// </summary>
        public void FrameOnWire(float wireX, float wireY, float wireZ, float? distance = null)
        {
            birdDistance = distance ?? TownVisualLayout.BirdZoomDefaultDistance;
            Vector3 lookAt = WireCoordinateTransform.ToUnity(wireX, wireY, wireZ);
            ApplyBirdPoseLookingAt(lookAt, immediate: true);
        }

        /// <summary>HUD / ESC helper — clear track and restore default bird's-eye.</summary>
        public void ReturnToBirdseye()
        {
            if (session != null)
            {
                session.SetTrackedAgent(null);
            }

            Frame();
        }

        private void HandleBirdZoom()
        {
            float scroll = Input.mouseScrollDelta.y;
            if (Mathf.Abs(scroll) < 0.01f)
            {
                return;
            }

            // Scroll up = zoom in (closer).
            birdDistance = Mathf.Clamp(
                birdDistance - scroll * ScrollZoomSpeed,
                TownVisualLayout.BirdZoomMinDistance,
                TownVisualLayout.BirdZoomMaxDistance);
            ApplyBirdPose(immediate: true);
        }

        private void ApplyBirdPose(bool immediate)
        {
            Vector3 viewCenter = WireCoordinateTransform.ToUnity(
                TownVisualLayout.ViewCenterWire.x,
                TownVisualLayout.ViewCenterWire.y,
                TownVisualLayout.ViewCenterWire.z);
            ApplyBirdPoseLookingAt(viewCenter, immediate);
        }

        private void ApplyBirdPoseLookingAt(Vector3 viewCenter, bool immediate)
        {
            Vector3 defaultCam = WireCoordinateTransform.ToUnity(
                TownVisualLayout.CameraWire.x,
                TownVisualLayout.CameraWire.y,
                TownVisualLayout.CameraWire.z);

            Vector3 fromCenter = defaultCam - WireCoordinateTransform.ToUnity(
                TownVisualLayout.ViewCenterWire.x,
                TownVisualLayout.ViewCenterWire.y,
                TownVisualLayout.ViewCenterWire.z);
            float defaultLen = fromCenter.magnitude;
            if (defaultLen < 0.01f)
            {
                fromCenter = new Vector3(1f, 1f, 1f);
                defaultLen = fromCenter.magnitude;
            }

            Vector3 dir = fromCenter / defaultLen;
            birdPosition = viewCenter + dir * birdDistance;
            birdRotation = Quaternion.LookRotation((viewCenter - birdPosition).normalized, Vector3.up);
            hasBirdPose = true;

            if (immediate)
            {
                transform.position = birdPosition;
                transform.rotation = birdRotation;
            }
        }

        private bool TryResolveTrackedPosition(string agentId, out Vector3 npcPos)
        {
            npcPos = default;
            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            if (npcManager != null && npcManager.TryGetLiveWorldPosition(agentId, out npcPos))
            {
                return true;
            }

            if (session != null
                && session.AgentUnityPositions.TryGetValue(agentId, out Vector3 wirePos))
            {
                npcPos = wirePos + TownPersonas.UnitySpawnOffset(agentId);
                return true;
            }

            return false;
        }
    }
}
