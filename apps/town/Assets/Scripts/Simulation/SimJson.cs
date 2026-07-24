using Newtonsoft.Json;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Shared Newtonsoft configuration + safe deserialization for simulation wire types.
    /// Tolerates the known contract drift in §6.7: unknown fields are ignored and missing
    /// optional fields fall back to their C# defaults.
    /// </summary>
    public static class SimJson
    {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings
        {
            NullValueHandling = NullValueHandling.Ignore,
            MissingMemberHandling = MissingMemberHandling.Ignore,
            DateParseHandling = DateParseHandling.None,
        };

        public static readonly JsonSerializer Serializer = JsonSerializer.Create(Settings);

        /// <summary>Deserialize <paramref name="json"/> into <typeparamref name="T"/>; returns false on failure.</summary>
        public static bool TryDeserialize<T>(string json, out T value) where T : class
        {
            value = null;
            if (string.IsNullOrEmpty(json))
            {
                return false;
            }

            try
            {
                value = JsonConvert.DeserializeObject<T>(json, Settings);
                return value != null;
            }
            catch (JsonException e)
            {
                Debug.LogWarning($"[AgentTown] JSON parse failed for {typeof(T).Name}: {e.Message}");
                return false;
            }
        }

        public static string Serialize(object value) => JsonConvert.SerializeObject(value, Settings);
    }
}
