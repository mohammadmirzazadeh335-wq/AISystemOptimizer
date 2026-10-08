using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.RegularExpressions;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Reads and (only when the user enabled it) changes the active Windows power scheme.
    ///
    /// The application never invents a power plan: if "Ultimate Performance" is not present
    /// on the machine, asking for it returns false instead of silently doing something else.
    /// </summary>
    public static class PowerSchemeManager
    {
        #region Well known GUIDs

        /// <summary>Balanced (always present).</summary>
        public static readonly Guid Balanced = new Guid("381b4222-f694-41f0-9685-ff5bb260df2e");

        /// <summary>High performance (always present).</summary>
        public static readonly Guid HighPerformance = new Guid("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c");

        /// <summary>Power saver (always present).</summary>
        public static readonly Guid PowerSaver = new Guid("a1841308-3541-4fab-bc81-f71556f20b4a");

        /// <summary>Ultimate performance (must be unlocked explicitly by the user, we never do that).</summary>
        public static readonly Guid UltimatePerformance = new Guid("e9a42b02-d566-4728-953a-8d77ad888086");

        #endregion

        #region Public API

        /// <summary>
        /// The active power scheme GUID parsed from the registry (Guid.Empty when unknown).
        /// </summary>
        public static Guid GetActiveScheme()
        {
            var raw = WindowsApiHelper.GetActivePowerSchemeGuid();

            if (string.IsNullOrWhiteSpace(raw))
                return Guid.Empty;

            return Guid.TryParse(raw, out var guid) ? guid : Guid.Empty;
        }

        /// <summary>
        /// The active power scheme mapped to our enum.
        /// </summary>
        public static PowerMode GetActivePowerMode()
        {
            var active = GetActiveScheme();

            if (active == Guid.Empty) return PowerMode.Balanced;
            if (active == HighPerformance) return PowerMode.HighPerformance;
            if (active == PowerSaver) return PowerMode.PowerSaver;
            if (active == UltimatePerformance) return PowerMode.UltimatePerformance;

            // An OEM supplied plan is active - report Balanced rather than guessing.
            return PowerMode.Balanced;
        }

        /// <summary>
        /// Friendly name of the active plan ("Balanced", or the OEM plan's name).
        /// </summary>
        public static string GetActiveSchemeName()
        {
            var active = GetActiveScheme();
            if (active == Guid.Empty) return "Unknown";

            var name = QuerySchemeName(active.ToString());
            return string.IsNullOrEmpty(name) ? MapToDisplayName(GetActivePowerMode()) : name;
        }

        /// <summary>
        /// Is the requested scheme installed on this machine?
        /// </summary>
        public static bool IsSchemeAvailable(Guid schemeGuid)
        {
            return ListAvailableSchemes().Exists(s => s.Guid == schemeGuid);
        }

        /// <summary>
        /// Switch the active power scheme. Requires elevation - returns false otherwise.
        /// </summary>
        public static bool SetActiveScheme(PowerMode mode)
        {
            var guid = MapToGuid(mode);

            if (guid == Guid.Empty)
                return false;

            // Refuse to "upgrade" to a scheme that does not exist on this machine,
            // instead of quietly switching to a different one.
            if (!IsSchemeAvailable(guid))
                return false;

            return WindowsApiHelper.SetActivePowerScheme(guid.ToString());
        }

        /// <summary>
        /// All power schemes installed on this machine.
        /// </summary>
        public static List<PowerSchemeInfo> ListAvailableSchemes()
        {
            var schemes = new List<PowerSchemeInfo>();

            try
            {
                var output = RunPowerCfg("/list");
                if (string.IsNullOrEmpty(output))
                    return schemes;

                // Lines look like:
                //   Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
                var regex = new Regex(
                    @"Power Scheme GUID:\s*(?<guid>[0-9a-fA-F\-]{36})\s*(\((?<name>[^)]*)\))?",
                    RegexOptions.Compiled);

                foreach (Match match in regex.Matches(output))
                {
                    if (!Guid.TryParse(match.Groups["guid"].Value, out var guid))
                        continue;

                    var name = match.Groups["name"].Success
                        ? match.Groups["name"].Value.Trim()
                        : string.Empty;

                    schemes.Add(new PowerSchemeInfo
                    {
                        Guid = guid,
                        Name = string.IsNullOrEmpty(name) ? guid.ToString() : name,
                        IsActive = guid == GetActiveScheme(),
                        IsWellKnown = guid == Balanced || guid == HighPerformance ||
                                      guid == PowerSaver || guid == UltimatePerformance
                    });
                }
            }
            catch { }

            return schemes;
        }

        /// <summary>
        /// Recommended scheme based on the power source.
        /// </summary>
        public static PowerMode GetRecommendedMode(AppConfig? config = null)
        {
            var onBattery = WindowsApiHelper.IsOnBattery();

            if (onBattery)
                return config?.PreferredPowerModeOnBattery ?? PowerMode.PowerSaver;

            return config?.PreferredPowerModeOnAc ?? PowerMode.Balanced;
        }

        #endregion

        #region Private helpers

        private static Guid MapToGuid(PowerMode mode)
        {
            switch (mode)
            {
                case PowerMode.Balanced: return Balanced;
                case PowerMode.HighPerformance: return HighPerformance;
                case PowerMode.PowerSaver: return PowerSaver;
                case PowerMode.UltimatePerformance: return UltimatePerformance;
                default: return Guid.Empty;
            }
        }

        private static string MapToDisplayName(PowerMode mode)
        {
            switch (mode)
            {
                case PowerMode.Balanced: return "Balanced";
                case PowerMode.HighPerformance: return "High performance";
                case PowerMode.PowerSaver: return "Power saver";
                case PowerMode.UltimatePerformance: return "Ultimate performance";
                default: return "Unknown";
            }
        }

        private static string QuerySchemeName(string schemeGuid)
        {
            try
            {
                var output = RunPowerCfg($"/query {schemeGuid}");
                if (string.IsNullOrEmpty(output)) return string.Empty;

                var match = Regex.Match(output, @"Power Scheme GUID:.*?\((?<name>[^)]*)\)");
                return match.Success ? match.Groups["name"].Value.Trim() : string.Empty;
            }
            catch
            {
                return string.Empty;
            }
        }

        private static string RunPowerCfg(string arguments)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "powercfg.exe",
                    Arguments = arguments,
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                using (var process = Process.Start(psi))
                {
                    if (process == null) return string.Empty;

                    var output = process.StandardOutput.ReadToEnd();
                    process.WaitForExit(10000);
                    return output;
                }
            }
            catch
            {
                return string.Empty;
            }
        }

        #endregion
    }

    /// <summary>Information about an installed power scheme.</summary>
    public class PowerSchemeInfo
    {
        public Guid Guid { get; set; }
        public string Name { get; set; } = string.Empty;
        public bool IsActive { get; set; }
        public bool IsWellKnown { get; set; }

        public override string ToString() =>
            IsActive ? $"{Name} (active)" : Name;
    }
}
