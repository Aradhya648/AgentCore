using System.Collections.Generic;
using AgentTown.Simulation;
using UnityEngine;
using UnityEngine.UIElements;

namespace AgentTown.Town
{
    /// <summary>
    /// Screen-space nameplates projected from NPC world positions onto the HUD panel.
    /// Uses UI Toolkit so Chinese display names share the panel font atlas (WebGL-safe).
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownNameplateHud : MonoBehaviour
    {
        private const float HeadHeight = 2.35f;
        private const float UpdateInterval = 0.05f;

        private UIDocument document;
        private SimulationSession session;
        private TownNpcManager npcManager;
        private VisualElement layer;
        private readonly Dictionary<string, Label> labels = new();
        private float nextUpdateAt;

        public void Bind(SimulationSession target)
        {
            session = target;
            npcManager = FindFirstObjectByType<TownNpcManager>();
            EnsureLayer();
        }

        private void OnEnable()
        {
            document = GetComponent<UIDocument>()
                ?? FindFirstObjectByType<UIDocument>();
            session ??= SimulationSession.Instance;
            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            EnsureLayer();
        }

        private void LateUpdate()
        {
            if (Time.unscaledTime < nextUpdateAt)
            {
                return;
            }

            nextUpdateAt = Time.unscaledTime + UpdateInterval;
            Refresh();
        }

        private void EnsureLayer()
        {
            if (layer != null)
            {
                return;
            }

            document ??= GetComponent<UIDocument>();
            VisualElement root = document != null ? document.rootVisualElement : null;
            if (root == null)
            {
                return;
            }

            layer = root.Q<VisualElement>("nameplate-layer");
            if (layer != null)
            {
                return;
            }

            layer = new VisualElement { name = "nameplate-layer" };
            layer.pickingMode = PickingMode.Ignore;
            layer.style.position = Position.Absolute;
            layer.style.left = 0;
            layer.style.right = 0;
            layer.style.top = 0;
            layer.style.bottom = 0;
            root.Add(layer);
        }

        private void Refresh()
        {
            EnsureLayer();
            layer?.BringToFront();
            if (layer == null || session == null || document == null)
            {
                return;
            }

            Camera cam = Camera.main;
            IPanel panel = document.rootVisualElement?.panel;
            if (cam == null || panel == null)
            {
                return;
            }

            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            var seen = new HashSet<string>();
            string selectedId = session.SelectedAgentId;

            foreach (KeyValuePair<string, SimAgentState> pair in session.Agents)
            {
                if (pair.Value == null || string.IsNullOrEmpty(pair.Key))
                {
                    continue;
                }

                if (!TryWorldPos(pair.Key, out Vector3 world))
                {
                    continue;
                }

                Vector3 head = world + Vector3.up * HeadHeight;
                float distance = Vector3.Distance(cam.transform.position, head);
                if (pair.Key != selectedId && distance > TownWatchPerf.NameplateHideDistance)
                {
                    continue;
                }

                Vector2 panelPos = RuntimePanelUtils.CameraTransformWorldToPanel(panel, head, cam);
                if (float.IsNaN(panelPos.x) || float.IsNaN(panelPos.y))
                {
                    continue;
                }

                // Behind camera → utility may still return a point; skip far-behind.
                Vector3 view = cam.WorldToViewportPoint(head);
                if (view.z <= 0.05f || view.x < -0.15f || view.x > 1.15f || view.y < -0.15f || view.y > 1.15f)
                {
                    continue;
                }

                string display = string.IsNullOrEmpty(pair.Value.Name) ? pair.Key : pair.Value.Name;
                Label label = GetOrCreate(pair.Key);
                label.text = display;
                label.style.left = panelPos.x - 50f;
                label.style.top = panelPos.y - 22f;
                label.EnableInClassList("nameplate--selected", pair.Key == selectedId);
                label.style.display = DisplayStyle.Flex;
                seen.Add(pair.Key);
            }

            // Seed from personas if snapshot agents not yet applied (boot frame).
            if (seen.Count == 0)
            {
                foreach (LocalPersona persona in TownPersonas.All)
                {
                    if (persona == null || string.IsNullOrEmpty(persona.AgentId))
                    {
                        continue;
                    }

                    if (!TryWorldPos(persona.AgentId, out Vector3 world))
                    {
                        continue;
                    }

                    Vector3 head = world + Vector3.up * HeadHeight;
                    Vector3 view = cam.WorldToViewportPoint(head);
                    if (view.z <= 0.05f || view.x < -0.05f || view.x > 1.05f || view.y < -0.05f || view.y > 1.05f)
                    {
                        continue;
                    }

                    Vector2 panelPos = RuntimePanelUtils.CameraTransformWorldToPanel(panel, head, cam);
                    Label label = GetOrCreate(persona.AgentId);
                    label.text = string.IsNullOrEmpty(persona.Name) ? persona.AgentId : persona.Name;
                    label.style.left = panelPos.x - 50f;
                    label.style.top = panelPos.y - 22f;
                    label.style.display = DisplayStyle.Flex;
                    seen.Add(persona.AgentId);
                }
            }

            foreach (KeyValuePair<string, Label> pair in labels)
            {
                if (!seen.Contains(pair.Key))
                {
                    pair.Value.style.display = DisplayStyle.None;
                }
            }
        }

        private Label GetOrCreate(string agentId)
        {
            if (labels.TryGetValue(agentId, out Label existing) && existing != null)
            {
                return existing;
            }

            var label = new Label { name = $"nameplate-{agentId}" };
            label.AddToClassList("npc-nameplate");
            label.pickingMode = PickingMode.Ignore;
            // Runtime-created elements don't reliably inherit the USS class in the WebGL
            // build, so pin the chip's visual style inline — otherwise the label carries
            // its text but paints no background/glyphs on-panel.
            label.style.position = Position.Absolute;
            label.style.paddingLeft = 8;
            label.style.paddingRight = 8;
            label.style.paddingTop = 3;
            label.style.paddingBottom = 3;
            label.style.minWidth = 44;
            label.style.backgroundColor = new Color(0.04f, 0.05f, 0.07f, 0.78f);
            label.style.color = new Color(0.96f, 0.97f, 0.99f, 1f);
            label.style.fontSize = 14;
            label.style.unityFontStyleAndWeight = FontStyle.Bold;
            label.style.unityTextAlign = TextAnchor.MiddleCenter;
            label.style.whiteSpace = WhiteSpace.NoWrap;
            label.style.borderTopLeftRadius = 4;
            label.style.borderTopRightRadius = 4;
            label.style.borderBottomLeftRadius = 4;
            label.style.borderBottomRightRadius = 4;
            layer.Add(label);
            labels[agentId] = label;
            return label;
        }

        private bool TryWorldPos(string agentId, out Vector3 world)
        {
            world = default;
            if (npcManager != null && npcManager.TryGetLiveWorldPosition(agentId, out world))
            {
                return true;
            }

            if (session != null
                && session.AgentUnityPositions.TryGetValue(agentId, out Vector3 wire))
            {
                world = wire + TownPersonas.UnitySpawnOffset(agentId);
                return true;
            }

            return false;
        }
    }
}
