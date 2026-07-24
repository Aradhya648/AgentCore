using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using UnityEngine;

namespace AgentTown.Show
{
    /// <summary>
    /// Drives the main camera from EpisodeManifest shot table. Free-look reuses
    /// <see cref="TownCamera"/>; <see cref="ReturnToDirector"/> resumes shot framing.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class CinematicDirector : MonoBehaviour
    {
        public enum CameraKind
        {
            WideEstablish,
            FollowPair,
            OrbitGroup,
            PushIn,
            RevealCloseup,
        }

        private EpisodeManifest manifest;
        private SimulationSession session;
        private TownCamera townCamera;
        private TownNpcManager npcManager;
        private Transform camTransform;
        private bool freeLook;
        private float orbitAngle;
        private string lastShotId;

        public bool IsFreeLook => freeLook;
        public EpisodeShot ActiveShot { get; private set; }

        public void Bind(
            EpisodeManifest episode,
            SimulationSession target,
            TownCamera camera,
            TownNpcManager npcs)
        {
            manifest = episode;
            session = target;
            townCamera = camera;
            npcManager = npcs;
            camTransform = camera != null ? camera.transform : Camera.main?.transform;
            freeLook = false;
            lastShotId = null;
            if (townCamera != null)
            {
                townCamera.SetExternalDrive(true);
            }
        }

        public void Unbind()
        {
            if (townCamera != null)
            {
                townCamera.SetExternalDrive(false);
            }

            manifest = null;
            ActiveShot = null;
        }

        public void SetFreeLook(bool enabled)
        {
            freeLook = enabled;
            if (townCamera != null)
            {
                townCamera.SetExternalDrive(!enabled);
                if (enabled)
                {
                    townCamera.ReturnToBirdseye();
                }
            }

            if (!enabled)
            {
                lastShotId = null;
            }
        }

        public void ReturnToDirector() => SetFreeLook(false);

        private void LateUpdate()
        {
            if (freeLook || manifest == null || session == null || camTransform == null)
            {
                return;
            }

            int tick = session.Playhead ?? session.Tick;
            EpisodeShot shot = EpisodeManifestLoader.ShotAtTick(manifest, tick);
            ActiveShot = shot;
            if (shot == null)
            {
                return;
            }

            if (shot.Id != lastShotId)
            {
                lastShotId = shot.Id;
                orbitAngle = 0f;
            }

            ApplyShot(shot, Time.deltaTime);
        }

        public void ApplyShotImmediate(EpisodeShot shot)
        {
            if (shot == null || camTransform == null)
            {
                return;
            }

            ActiveShot = shot;
            lastShotId = shot.Id;
            ApplyShot(shot, 1f);
        }

        /// <summary>EditMode / unit: resolve camera kind + focus without mutating transforms.</summary>
        public static bool TryResolveFraming(
            EpisodeShot shot,
            IReadOnlyDictionary<string, Vector3> agentWorldPositions,
            Vector3 fallbackLookAt,
            out CameraKind kind,
            out Vector3 lookAt,
            out Vector3 cameraPos)
        {
            kind = ParseKind(shot?.Camera);
            lookAt = fallbackLookAt;
            cameraPos = fallbackLookAt + new Vector3(8f, 12f, 8f);

            if (shot == null)
            {
                return false;
            }

            List<Vector3> subjects = CollectSubjects(shot, agentWorldPositions);
            if (subjects.Count > 0)
            {
                lookAt = Average(subjects);
            }

            switch (kind)
            {
                case CameraKind.WideEstablish:
                    cameraPos = lookAt + new Vector3(14f, 16f, 14f);
                    break;
                case CameraKind.FollowPair:
                    cameraPos = lookAt + new Vector3(0f, 5.5f, -9f);
                    break;
                case CameraKind.OrbitGroup:
                    cameraPos = lookAt + new Vector3(10f, 8f, 0f);
                    break;
                case CameraKind.PushIn:
                    cameraPos = lookAt + new Vector3(0f, 3.2f, -5.5f);
                    break;
                case CameraKind.RevealCloseup:
                    cameraPos = lookAt + new Vector3(1.2f, 2.4f, -3.2f);
                    break;
            }

            return true;
        }

        private void ApplyShot(EpisodeShot shot, float dt)
        {
            Dictionary<string, Vector3> positions = BuildPositionMap();
            Vector3 fallback = RegionFallback(shot);
            if (!TryResolveFraming(
                    shot, positions, fallback, out CameraKind kind, out Vector3 lookAt, out Vector3 camPos))
            {
                return;
            }

            if (kind == CameraKind.OrbitGroup)
            {
                orbitAngle += dt * 0.35f;
                float radius = 11f;
                camPos = lookAt + new Vector3(
                    Mathf.Cos(orbitAngle) * radius,
                    8f,
                    Mathf.Sin(orbitAngle) * radius);
            }

            float t = 1f - Mathf.Exp(-4f * Mathf.Max(dt, 0.001f));
            camTransform.position = Vector3.Lerp(camTransform.position, camPos, t);
            Quaternion look = Quaternion.LookRotation((lookAt - camPos).normalized, Vector3.up);
            camTransform.rotation = Quaternion.Slerp(camTransform.rotation, look, t);
        }

        private Dictionary<string, Vector3> BuildPositionMap()
        {
            var map = new Dictionary<string, Vector3>();
            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            if (npcManager != null)
            {
                foreach (ShowCastMember member in ShowCast.Members)
                {
                    if (npcManager.TryGetLiveWorldPosition(member.Id, out Vector3 pos))
                    {
                        map[member.Id] = pos;
                    }
                }
            }

            if (session != null)
            {
                foreach (KeyValuePair<string, Vector3> pair in session.AgentUnityPositions)
                {
                    if (!map.ContainsKey(pair.Key))
                    {
                        map[pair.Key] = pair.Value;
                    }
                }
            }

            return map;
        }

        private static List<Vector3> CollectSubjects(
            EpisodeShot shot, IReadOnlyDictionary<string, Vector3> positions)
        {
            var list = new List<Vector3>();
            if (shot?.Subjects == null || positions == null)
            {
                return list;
            }

            foreach (string id in shot.Subjects)
            {
                if (!string.IsNullOrEmpty(id) && positions.TryGetValue(id, out Vector3 pos))
                {
                    list.Add(pos);
                }
            }

            return list;
        }

        private static Vector3 Average(List<Vector3> points)
        {
            Vector3 sum = Vector3.zero;
            foreach (Vector3 p in points)
            {
                sum += p;
            }

            return sum / points.Count;
        }

        private Vector3 RegionFallback(EpisodeShot shot)
        {
            string cam = shot?.Camera ?? "";
            // Reveal / night default toward heart camp; day establish toward market.
            if (cam == "wide_establish" && shot?.Subjects != null && shot.Subjects.Count >= 4)
            {
                // Could be market or camp — prefer camp wire if subjects empty-ish establish at camp.
            }

            WireVec3 camp = new WireVec3(-56, 0, 36);
            return WireCoordinateTransform.ToUnity(camp);
        }

        public static CameraKind ParseKind(string camera)
        {
            switch (camera)
            {
                case "follow_pair":
                    return CameraKind.FollowPair;
                case "orbit_group":
                    return CameraKind.OrbitGroup;
                case "push_in":
                    return CameraKind.PushIn;
                case "reveal_closeup":
                    return CameraKind.RevealCloseup;
                default:
                    return CameraKind.WideEstablish;
            }
        }
    }
}
