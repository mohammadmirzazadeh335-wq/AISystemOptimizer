using System;
using System.Collections.Generic;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Utilities;
using Microsoft.Win32;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One recorded change to the Windows graphics preference, with everything needed to put it back.
    /// The fields the specification requires are all here: the original value, the new value, when, for
    /// which application, why, and what the rollback is.
    /// </summary>
    public sealed class GraphicsPreferenceChange
    {
        public Guid ApplicationId { get; set; }

        public string ExecutablePath { get; set; } = string.Empty;

        /// <summary>The value found in the registry before the change, or an empty string when none existed.</summary>
        public string OriginalValue { get; set; } = string.Empty;

        public string NewValue { get; set; } = string.Empty;

        public DateTime ChangedAtUtc { get; set; } = DateTime.UtcNow;

        public string Reason { get; set; } = string.Empty;

        /// <summary>True when there was no value before, so restoring means removing the value again.</summary>
        public bool OriginalValueWasAbsent { get; set; }

        public string RegistryPath { get; set; } = GraphicsPreferenceService.RegistryPath;

        public string RegistryValueName { get; set; } = string.Empty;

        /// <summary>The exact steps taken to undo this change, in words.</summary>
        public string RollbackDescription =>
            OriginalValueWasAbsent
                ? $"Remove '{RegistryValueName}' from HKCU\\{RegistryPath}."
                : $"Set '{RegistryValueName}' back to '{OriginalValue}' in HKCU\\{RegistryPath}.";

        public string Describe() =>
            $"{System.IO.Path.GetFileName(ExecutablePath)}: '{OriginalValue}' -> '{NewValue}' " +
            $"({RegistryValueName}) at {ChangedAtUtc.ToLocalTime():HH:mm:ss}";
    }

    /// <summary>Outcome of applying or restoring a graphics preference.</summary>
    public sealed class GraphicsPreferenceResult
    {
        public bool Success { get; init; }

        public bool Applied => Success;

        public string Message { get; init; } = string.Empty;

        public GraphicsPreferenceChange? Change { get; init; }

        /// <summary>True when nothing needed to be done (the value was already what the profile wants).</summary>
        public bool NothingToDo { get; init; }

        public static GraphicsPreferenceResult Failed(string message) =>
            new GraphicsPreferenceResult { Success = false, Message = message };

        public static GraphicsPreferenceResult Unchanged(string message) =>
            new GraphicsPreferenceResult { Success = true, NothingToDo = true, Message = message };
    }

    /// <summary>
    /// The Windows graphics preference for one application.
    ///
    /// Scope, deliberately limited:
    ///   * Per user (HKEY_CURRENT_USER). No administrator rights, no machine-wide change, nothing that
    ///     affects another user account.
    ///   * One documented value under
    ///     HKCU\Software\Microsoft\DirectX\UserGpuPreferences, which is the same place Windows' own
    ///     Settings &gt; Display &gt; Graphics page writes. It is not an undocumented tweak.
    ///   * The value name is the executable's full path, so it is validated with the same path validator
    ///     the rest of the feature uses. The registry value is written with Registry.SetValue, never
    ///     through a shell command and never through a string built for a command line.
    ///   * The preference is one of a fixed set of three. Nothing else can be expressed.
    ///   * The original value is captured before the write, and it is restored afterwards - including
    ///     when the original state was "no value at all", in which case the value is removed again.
    ///
    /// What this class never does: overclocking, voltage, driver installation, vendor control-panel
    /// settings, registry edits anywhere else, or a change without a recorded rollback.
    /// </summary>
    public sealed class GraphicsPreferenceService
    {
        public const string RegistryPath = @"Software\Microsoft\DirectX\UserGpuPreferences";

        /// <summary>The value names Windows itself uses.</summary>
        private const string HighPerformanceToken = "GpuPreference=2;";
        private const string PowerSavingToken = "GpuPreference=1;";

        private readonly ILogger _logger;

        public GraphicsPreferenceService(ILogger? logger = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
        }

        /// <summary>True when the platform can store a graphics preference at all.</summary>
        public static bool IsSupported => OperatingSystem.IsWindows();

        /// <summary>
        /// The value Windows currently holds for an executable, or an empty string when there is none.
        /// </summary>
        public string ReadCurrentValue(string executablePath)
        {
            if (!IsSupported || string.IsNullOrWhiteSpace(executablePath))
                return string.Empty;

            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(RegistryPath, writable: false);

                var value = key?.GetValue(executablePath)?.ToString();

                return value ?? string.Empty;
            }
            catch (Exception exception)
            {
                _logger.Warning("GraphicsPreferenceService",
                    $"The current graphics preference could not be read: {exception.Message}");

                // Empty means "not known". The caller must not treat that as "no value existed", which is
                // why Apply refuses to change anything when the original cannot be read.
                return string.Empty;
            }
        }

        /// <summary>
        /// Whether a value could be read at all. Distinguishes "no preference set" from "could not read".
        /// </summary>
        public bool TryReadCurrentValue(string executablePath, out string value, out string error)
        {
            value = string.Empty;
            error = string.Empty;

            if (!IsSupported)
            {
                error = "Storing a graphics preference requires Windows.";
                return false;
            }

            var validation = ExecutablePathValidator.Validate(executablePath);

            if (!validation.IsValid)
            {
                error = validation.ErrorMessage;
                return false;
            }

            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(RegistryPath, writable: false);

                value = key?.GetValue(validation.CanonicalPath)?.ToString() ?? string.Empty;
                return true;
            }
            catch (Exception exception)
            {
                error = $"The current graphics preference could not be read: {exception.Message}";
                return false;
            }
        }

        /// <summary>
        /// Apply a preference. Nothing is written unless the original state was read first: a change that
        /// cannot be undone is not made.
        /// </summary>
        public GraphicsPreferenceResult Apply(
            Guid applicationId,
            string executablePath,
            GraphicsPreference preference,
            string reason)
        {
            if (preference == GraphicsPreference.LetWindowsDecide)
            {
                // "Let Windows decide" is expressed by the absence of a value, so applying it means
                // restoring whatever was there before rather than writing a fourth token.
                return GraphicsPreferenceResult.Failed(
                    "'Let Windows decide' means no stored preference. Use Restore to remove the value " +
                    "instead of applying one.");
            }

            var validation = ExecutablePathValidator.Validate(executablePath);

            if (!validation.IsValid)
                return GraphicsPreferenceResult.Failed(validation.ErrorMessage);

            if (!IsSupported)
            {
                return GraphicsPreferenceResult.Failed(
                    "Storing a graphics preference requires Windows. Nothing was changed.");
            }

            if (!TryReadCurrentValue(validation.CanonicalPath, out var original, out var readError))
                return GraphicsPreferenceResult.Failed(readError + " Nothing was changed.");

            var token = preference switch
            {
                GraphicsPreference.HighPerformance => HighPerformanceToken,
                GraphicsPreference.PowerSaving => PowerSavingToken,
                _ => string.Empty
            };

            if (string.IsNullOrEmpty(token))
            {
                return GraphicsPreferenceResult.Failed(
                    $"'{preference}' is not a preference this application can store.");
            }

            if (string.Equals(original, token, StringComparison.OrdinalIgnoreCase))
            {
                return GraphicsPreferenceResult.Unchanged(
                    $"This application is already set to {preference}. Nothing was changed.");
            }

            try
            {
                using var key = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true);

                if (key == null)
                    return GraphicsPreferenceResult.Failed("The graphics preference key could not be opened.");

                // Registry.SetValue takes the name and value as data. Nothing here is ever a shell string.
                Registry.SetValue(
                    $@"HKEY_CURRENT_USER\{RegistryPath}",
                    validation.CanonicalPath,
                    token,
                    RegistryValueKind.String);

                var change = new GraphicsPreferenceChange
                {
                    ApplicationId = applicationId,
                    ExecutablePath = validation.CanonicalPath,
                    OriginalValue = original,
                    OriginalValueWasAbsent = string.IsNullOrEmpty(original),
                    NewValue = token,
                    Reason = reason,
                    RegistryValueName = validation.CanonicalPath
                };

                _logger.Info("GraphicsPreferenceService",
                    $"Graphics preference set for '{validation.CanonicalPath}': " +
                    $"'{original}' -> '{token}'. Original value recorded for rollback. Reason: {reason}");

                return new GraphicsPreferenceResult
                {
                    Success = true,
                    Change = change,
                    Message = $"Graphics preference set to {preference} for this application."
                };
            }
            catch (Exception exception)
            {
                _logger.Error("GraphicsPreferenceService",
                    $"The graphics preference for '{validation.CanonicalPath}' could not be set", null, exception);

                return GraphicsPreferenceResult.Failed(
                    $"The graphics preference could not be set: {exception.Message}");
            }
        }

        /// <summary>
        /// Put back exactly what was there before, from the recorded change.
        /// </summary>
        public GraphicsPreferenceResult Restore(GraphicsPreferenceChange change)
        {
            if (change == null)
                return GraphicsPreferenceResult.Failed("No recorded change was supplied.");

            if (!IsSupported)
                return GraphicsPreferenceResult.Failed("Restoring a graphics preference requires Windows.");

            var validation = ExecutablePathValidator.Validate(change.ExecutablePath, requireExists: false);

            if (!validation.IsValid)
            {
                return GraphicsPreferenceResult.Failed(
                    $"The recorded path is no longer valid, so it was not written to the registry: " +
                    $"{validation.ErrorMessage}");
            }

            try
            {
                if (change.OriginalValueWasAbsent)
                {
                    using var key = Registry.CurrentUser.OpenSubKey(RegistryPath, writable: true);

                    if (key == null)
                        return GraphicsPreferenceResult.Unchanged("There was no preference to remove.");

                    if (key.GetValue(validation.CanonicalPath) == null)
                        return GraphicsPreferenceResult.Unchanged("The preference was already absent.");

                    key.DeleteValue(validation.CanonicalPath, throwOnMissingValue: false);

                    _logger.Info("GraphicsPreferenceService",
                        $"Graphics preference removed for '{validation.CanonicalPath}': there was none before.");

                    return new GraphicsPreferenceResult
                    {
                        Success = true,
                        Message = "Graphics preference restored (removed)."
                    };
                }

                Registry.SetValue(
                    $@"HKEY_CURRENT_USER\{RegistryPath}",
                    validation.CanonicalPath,
                    change.OriginalValue,
                    RegistryValueKind.String);

                _logger.Info("GraphicsPreferenceService",
                    $"Graphics preference restored for '{validation.CanonicalPath}' to '{change.OriginalValue}'.");

                return new GraphicsPreferenceResult
                {
                    Success = true,
                    Message = $"Graphics preference restored to '{change.OriginalValue}'."
                };
            }
            catch (Exception exception)
            {
                _logger.Error("GraphicsPreferenceService",
                    $"The graphics preference for '{validation.CanonicalPath}' could not be restored", null, exception);

                // A failure to restore is reported exactly, never swallowed and never reported as success.
                return GraphicsPreferenceResult.Failed(
                    $"The graphics preference could not be restored: {exception.Message}. " +
                    $"{change.RollbackDescription}");
            }
        }

        /// <summary>
        /// What the registry value means, in words. Used to show the user the current state.
        /// </summary>
        public static GraphicsPreference DescribeValue(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return GraphicsPreference.LetWindowsDecide;

            if (value!.Contains("GpuPreference=2", StringComparison.OrdinalIgnoreCase))
                return GraphicsPreference.HighPerformance;

            if (value.Contains("GpuPreference=1", StringComparison.OrdinalIgnoreCase))
                return GraphicsPreference.PowerSaving;

            return GraphicsPreference.LetWindowsDecide;
        }
    }
}
