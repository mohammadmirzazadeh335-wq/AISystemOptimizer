using System;
using System.Collections.Generic;
using AISystemOptimizer.Core.GameApp.Models;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One line explaining what a mode did or did not enable. Shown to the user, so that a mode is never
    /// a black box.
    /// </summary>
    public sealed class PresetExplanation
    {
        public string Setting { get; init; } = string.Empty;

        public string Value { get; init; } = string.Empty;

        public string Why { get; init; } = string.Empty;
    }

    /// <summary>
    /// What each profile mode means, as data rather than as scattered special cases.
    ///
    /// The three built-in modes are fixed. "Custom" keeps whatever the user chose. There is no mode that
    /// reaches outside the safety model: the aggressive end of this scale is still only priority, power
    /// mode and closing background applications that the existing safety layer already permits.
    ///
    /// Every preset is expressed as a starting point for the user's own settings - the user can change
    /// anything afterwards, and nothing here overrides a profile's own values.
    /// </summary>
    public static class ProfileModePresets
    {
        /// <summary>
        /// Apply a mode's starting settings to a profile. Custom returns the profile untouched, because
        /// "Custom" is the user's own choice by definition.
        /// </summary>
        public static void Apply(GameAppProfile profile, GameAppProfileMode mode)
        {
            if (profile == null)
                throw new ArgumentNullException(nameof(profile));

            profile.ProfileMode = mode;

            switch (mode)
            {
                case GameAppProfileMode.Safe:
                    ApplySafe(profile);
                    break;

                case GameAppProfileMode.Balanced:
                    ApplyBalanced(profile);
                    break;

                case GameAppProfileMode.Performance:
                    ApplyPerformance(profile);
                    break;

                case GameAppProfileMode.Custom:
                    // Nothing is changed: the user is in charge of every switch.
                    break;
            }

            profile.NormalizeToSupportedRanges();
        }

        /// <summary>
        /// Safe: the smallest set of changes that is worth making at all, and everything reversible.
        /// No background application is closed, no power mode is switched, nothing is written anywhere.
        /// </summary>
        private static void ApplySafe(GameAppProfile profile)
        {
            profile.Cpu.Enabled = true;
            profile.Cpu.Priority = ProcessPriorityPreference.LeaveUnchanged;

            profile.Ram.Enabled = true;
            profile.Ram.CloseBackgroundProcesses = false;
            profile.Ram.MaxBackgroundProcessesPerSession = 0;

            profile.Gpu.Enabled = false;
            profile.Gpu.CloseGpuHeavyBackgroundApplications = false;
            profile.Gpu.GraphicsPreference = GraphicsPreference.LetWindowsDecide;

            profile.Disk.Enabled = false;
            profile.Disk.CleanupScope = DiskCleanupScope.None;

            profile.Power.Enabled = false;
            profile.Power.ModeWhileRunning = PowerPreference.LeaveUnchanged;
            profile.Power.RestoreAfterExit = true;

            profile.Network.ReportActivity = false;
        }

        /// <summary>
        /// Balanced: the default. A conservative priority change while the application runs, and
        /// background applications closed only when the user has already approved them one by one.
        /// </summary>
        private static void ApplyBalanced(GameAppProfile profile)
        {
            profile.Cpu.Enabled = true;
            profile.Cpu.Priority = ProcessPriorityPreference.AboveNormal;

            profile.Ram.Enabled = true;
            profile.Ram.CloseBackgroundProcesses = true;
            profile.Ram.MaxBackgroundProcessesPerSession = 2;
            profile.Ram.MinimumWorkingSetMegabytes = 100;

            profile.Gpu.Enabled = true;
            profile.Gpu.CloseGpuHeavyBackgroundApplications = false;
            profile.Gpu.GraphicsPreference = GraphicsPreference.LetWindowsDecide;

            profile.Disk.Enabled = true;
            profile.Disk.CleanupScope = DiskCleanupScope.IdentifyOnly;
            profile.Disk.ReportRuntimeActivity = true;

            profile.Power.Enabled = true;
            profile.Power.ModeWhileRunning = PowerPreference.HighPerformance;
            profile.Power.RestoreAfterExit = true;

            profile.Network.ReportActivity = false;
        }

        /// <summary>
        /// Performance: the most that is safe. Still inside the model - above-normal priority rather than
        /// high, the existing power plan rather than a new one, and only background applications the user
        /// has approved or that are on the safe list.
        /// </summary>
        private static void ApplyPerformance(GameAppProfile profile)
        {
            profile.Cpu.Enabled = true;
            profile.Cpu.Priority = ProcessPriorityPreference.High;

            profile.Ram.Enabled = true;
            profile.Ram.CloseBackgroundProcesses = true;
            profile.Ram.MaxBackgroundProcessesPerSession = 5;
            profile.Ram.MinimumWorkingSetMegabytes = 150;

            profile.Gpu.Enabled = true;
            profile.Gpu.CloseGpuHeavyBackgroundApplications = true;
            profile.Gpu.GraphicsPreference = GraphicsPreference.HighPerformance;

            profile.Disk.Enabled = true;
            profile.Disk.CleanupScope = DiskCleanupScope.IdentifyOnly;
            profile.Disk.ReportRuntimeActivity = true;

            profile.Power.Enabled = true;
            profile.Power.ModeWhileRunning = PowerPreference.HighPerformance;
            profile.Power.RestoreAfterExit = true;

            profile.Network.ReportActivity = true;
        }

        /// <summary>
        /// A description of what a mode sets, for the interface and for the log. The interface shows this
        /// so that choosing "Performance" is an informed choice rather than a label.
        /// </summary>
        public static List<PresetExplanation> Explain(GameAppProfileMode mode)
        {
            var explanation = new List<PresetExplanation>();

            switch (mode)
            {
                case GameAppProfileMode.Safe:
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Process priority",
                        Value = "Unchanged",
                        Why = "The smallest change set: the application's priority is left as Windows set it."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Background applications",
                        Value = "Not closed",
                        Why = "Closing another program is a change to that program, so Safe does not do it."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Power mode",
                        Value = "Unchanged",
                        Why = "The machine's power settings are left exactly as they are."
                    });
                    break;

                case GameAppProfileMode.Balanced:
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Process priority",
                        Value = "Above normal, restored afterwards",
                        Why = "Enough to stop the application being starved by background work, without " +
                              "taking processing time from everything else."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Background applications",
                        Value = "Up to 2, only ones you approved",
                        Why = "Nothing is closed on the strength of its name; the rule for each application " +
                              "is yours."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Power mode",
                        Value = "High performance while running, restored after exit",
                        Why = "The original mode is recorded before the change and put back when the " +
                              "application exits - including after a crash."
                    });
                    break;

                case GameAppProfileMode.Performance:
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Process priority",
                        Value = "High, restored afterwards",
                        Why = "High (never Realtime) is the highest priority this application will set. " +
                              "Realtime can starve input and audio, so it is not offered at all."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Background applications",
                        Value = "Up to 5, from the safe and approved lists",
                        Why = "Still refuses anything in use, anything with a window, and everything on " +
                              "the protected lists."
                    });
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Graphics preference",
                        Value = "High performance",
                        Why = "Applied to this application only, in your own user settings, and put back " +
                              "when the session ends."
                    });
                    break;

                case GameAppProfileMode.Custom:
                    explanation.Add(new PresetExplanation
                    {
                        Setting = "Everything",
                        Value = "Your settings",
                        Why = "A custom profile keeps exactly the switches you set. The safety layer still " +
                              "applies: it cannot be switched off from here."
                    });
                    break;
            }

            return explanation;
        }

        /// <summary>
        /// The sentence the interface shows under the mode selector.
        /// </summary>
        public static string Describe(GameAppProfileMode mode) => mode switch
        {
            GameAppProfileMode.Safe =>
                "Minimal and fully reversible: no background application is closed and no system setting is changed.",
            GameAppProfileMode.Balanced =>
                "The default: a conservative priority change and a temporary power mode, both restored when the application exits.",
            GameAppProfileMode.Performance =>
                "The most this application will do: higher priority, more background applications closed - still only ones you approved, still fully reversible.",
            GameAppProfileMode.Custom =>
                "Your own settings. The safety layer still applies and cannot be turned off here.",
            _ => "Unknown mode."
        };
    }
}
