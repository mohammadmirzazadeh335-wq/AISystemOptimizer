using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One thing the planner wanted to do and will not, with the reason. Kept so the interface can say
    /// "this was considered and refused, here is why" instead of quietly doing less.
    /// </summary>
    public sealed class RefusedAction
    {
        public string What { get; init; } = string.Empty;

        public string Why { get; init; } = string.Empty;

        public string Describe() => $"{What}: {Why}";
    }

    /// <summary>
    /// The result of planning a session for one application.
    /// </summary>
    public sealed class GameAppPlan
    {
        public GameAppProfile? Profile { get; init; }

        /// <summary>The actions that will go through the existing validator and executor.</summary>
        public OptimizationPlan Plan { get; init; } = new OptimizationPlan();

        public List<RefusedAction> Refusals { get; init; } = new List<RefusedAction>();

        /// <summary>
        /// The graphics preference the planner wants applied, if any. Applied by
        /// <see cref="GraphicsPreferenceService"/>, recorded with its original value and undone by the
        /// session's restore step.
        /// </summary>
        public GraphicsPreference? RequestedGraphicsPreference { get; init; }

        public bool HasAnythingToDo =>
            Plan.Actions.Count > 0 || RequestedGraphicsPreference.HasValue;

        /// <summary>A sentence for the user, and for the log.</summary>
        public string Summary
        {
            get
            {
                if (!HasAnythingToDo)
                {
                    return "No action was planned: nothing this profile may change would improve this " +
                           "application's running conditions right now.";
                }

                var parts = new List<string>();

                var closes = Plan.Actions.Count(a => a.ActionType == OptimizationActionType.CloseProcess);
                var priority = Plan.Actions.Any(a => a.ActionType == OptimizationActionType.ChangePriority);
                var power = Plan.Actions.Any(a => a.ActionType == OptimizationActionType.AdjustPowerSettings);

                if (closes > 0) parts.Add($"close {closes} approved background application(s)");
                if (priority) parts.Add("raise the application's priority");
                if (power) parts.Add("switch the power mode while it runs");
                if (RequestedGraphicsPreference.HasValue) parts.Add($"set its graphics preference to {RequestedGraphicsPreference}");

                return $"Planned: {string.Join(", ", parts)}. Every one of these is recorded and reversible.";
            }
        }
    }

    /// <summary>
    /// Builds the list of changes for one application from its profile and the current state of the
    /// machine.
    ///
    /// This class only plans. It does not execute, and it has no way to execute: every planned action is
    /// an <see cref="OptimizationAction"/> that the existing <c>SafetyValidator</c> must approve and the
    /// existing <c>SafeExecutor</c> must perform. The planner's job is to be conservative in what it even
    /// proposes - a profile that allows five closes proposes the five whose working set actually matters,
    /// and one that allows none proposes nothing at all.
    ///
    /// Refusals are returned as data rather than dropped, so the user can see that the optimiser
    /// considered something and declined it.
    /// </summary>
    public sealed class GameAppActionPlanner
    {
        private readonly ILogger _logger;

        public GameAppActionPlanner(ILogger? logger = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
        }

        /// <summary>
        /// Plan a session.
        /// </summary>
        /// <param name="profile">The profile being applied. A suspended profile plans nothing.</param>
        /// <param name="health">The result of checking the executable against the profile.</param>
        /// <param name="runningInstances">The confirmed instances of the application, with creation times.</param>
        /// <param name="processes">The current process list, from the existing scanner.</param>
        /// <param name="neverOptimize">The user's never-optimise list.</param>
        /// <param name="allowPowerChange">Whether the application configuration permits power changes.</param>
        /// <param name="allowGraphicsChange">Whether the application configuration permits graphics changes.</param>
        public GameAppPlan Plan(
            GameAppProfile profile,
            ApplicationHealth health,
            IReadOnlyList<ApplicationRunInfo> runningInstances,
            IReadOnlyList<ProcessInfo> processes,
            IReadOnlyList<NeverOptimizeEntry>? neverOptimize,
            bool allowPowerChange,
            bool allowGraphicsChange)
        {
            if (profile == null) throw new ArgumentNullException(nameof(profile));

            var refusals = new List<RefusedAction>();
            var plan = new OptimizationPlan
            {
                Name = $"Game & App Optimizer: {profile.ResolveDisplayName()}",
                Description = $"Profile '{profile.ProfileMode}' for {profile.ResolveDisplayName()}"
            };

            // 1. A profile whose executable does not match what is on disk plans nothing at all. This is
            //    the guard that stops a profile being applied to a different program.
            if (health is { IsUsable: false })
            {
                refusals.Add(new RefusedAction
                {
                    What = "Apply this profile",
                    Why = health.Summary + " " + string.Join(" ", health.Findings)
                });

                return new GameAppPlan { Profile = profile, Plan = plan, Refusals = refusals };
            }

            if (!profile.Enabled)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Apply this profile",
                    Why = "The profile is switched off."
                });

                return new GameAppPlan { Profile = profile, Plan = plan, Refusals = refusals };
            }

            // 2. Priority. Only ever for the application's own confirmed instances.
            PlanPriority(profile, runningInstances, plan, refusals);

            // 3. Closing background applications - the only memory mechanism, and only through the
            //    existing pipeline, with the categoriser deciding what is even a candidate.
            PlanBackgroundClosures(profile, processes, neverOptimize, plan, refusals);

            // 4. Power mode. Refused outright when the original scheme cannot be read, because a change
            //    that cannot be undone must not be made.
            PlanPower(profile, allowPowerChange, plan, refusals);

            // 5. Graphics preference.
            GraphicsPreference? graphicsRequest = PlanGraphics(profile, allowGraphicsChange, refusals);

            // 6. Sections that are on but have nothing to do are listed, so "nothing happened" is explained.
            if (profile.Disk.Enabled && profile.Disk.CleanupScope == DiskCleanupScope.None)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Disk cleanup",
                    Why = "This profile identifies disk activity but removes nothing. Deleting files is only " +
                          "ever offered with a warning, per application, never as part of a session."
                });
            }

            _logger.Info("GameAppActionPlanner",
                $"Planned {plan.Actions.Count} action(s) for '{profile.ResolveDisplayName()}', " +
                $"{refusals.Count} item(s) considered and refused.");

            return new GameAppPlan
            {
                Profile = profile,
                Plan = plan,
                Refusals = refusals,
                RequestedGraphicsPreference = graphicsRequest
            };
        }

        private void PlanPriority(
            GameAppProfile profile,
            IReadOnlyList<ApplicationRunInfo> runningInstances,
            OptimizationPlan plan,
            List<RefusedAction> refusals)
        {
            if (!profile.Cpu.Enabled)
            {
                refusals.Add(new RefusedAction { What = "CPU priority", Why = "The CPU section is off for this profile." });
                return;
            }

            if (profile.Cpu.Priority == ProcessPriorityPreference.LeaveUnchanged)
                return;

            var confirmed = (runningInstances ?? Array.Empty<ApplicationRunInfo>())
                .Where(i => i != null && i.IsConfirmedMatch && i.CreationTimeUtc != default)
                .ToList();

            if (confirmed.Count == 0)
            {
                refusals.Add(new RefusedAction
                {
                    What = "CPU priority",
                    Why = "The application is not running, or its running instance could not be confirmed, " +
                          "so there is no process to raise the priority of."
                });

                return;
            }

            var applicationProcessName = ExecutablePathValidator.NormaliseExecutableName(profile.FileName);

            foreach (var instance in confirmed)
            {
                var action = new OptimizationAction
                {
                    ActionType = OptimizationActionType.ChangePriority,
                    Target = profile.FileName,
                    TargetPid = instance.ProcessId,
                    TargetCreationTimeUtc = instance.CreationTimeUtc,
                    TargetImagePath = instance.Path,
                    TargetProcessName = applicationProcessName,
                    ResourceType = ResourceType.CPU,
                    RiskLevel = RiskLevel.Low,
                    Priority = 8,
                    Description = $"Set priority to {profile.Cpu.Priority} for {profile.ResolveDisplayName()}",
                    Reason =
                        $"The profile '{profile.ProfileMode}' raises this application's priority while it runs. " +
                        $"The original priority is recorded and restored when it exits.",
                    CanUndo = true,
                    RequiresAdmin = false
                };

                action.CaptureProcessIdentity(new ProcessInfo
                {
                    Id = instance.ProcessId,
                    Name = applicationProcessName,
                    Path = instance.Path,
                    CreationTimeUtc = instance.CreationTimeUtc,
                    WorkingSet = instance.WorkingSet
                });

                action.UndoAction = new OptimizationAction
                {
                    ActionType = OptimizationActionType.ChangePriority,
                    Target = profile.FileName,
                    TargetPid = instance.ProcessId,
                    TargetCreationTimeUtc = instance.CreationTimeUtc,
                    TargetImagePath = instance.Path,
                    Reason = "Restore the priority the process had before this session.",
                    CanUndo = false,
                    RiskLevel = RiskLevel.Low
                };

                plan.Actions.Add(action);
            }

            // Affinity is never planned, in any mode. Said out loud so that its absence is not mistaken
            // for an oversight.
            if (profile.Cpu.Priority != ProcessPriorityPreference.LeaveUnchanged)
            {
                refusals.Add(new RefusedAction
                {
                    What = "CPU affinity",
                    Why = "Cores are never restricted by this feature. Forcing affinity usually makes an " +
                          "application slower on a machine that is doing anything else, so the value is " +
                          "read and shown, never set."
                });
            }
        }

        private void PlanBackgroundClosures(
            GameAppProfile profile,
            IReadOnlyList<ProcessInfo> processes,
            IReadOnlyList<NeverOptimizeEntry>? neverOptimize,
            OptimizationPlan plan,
            List<RefusedAction> refusals)
        {
            if (!profile.Ram.Enabled || !profile.Ram.CloseBackgroundProcesses)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Background applications",
                    Why = profile.Ram.Enabled
                        ? "This profile is set not to close background applications."
                        : "The memory section is off for this profile."
                });

                return;
            }

            if (profile.Ram.MaxBackgroundProcessesPerSession <= 0)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Background applications",
                    Why = "This profile allows no background application to be closed in a session."
                });

                return;
            }

            var assessments = BackgroundProcessCategorizer.AssessAll(processes, profile, neverOptimize);

            var candidates = BackgroundProcessCategorizer.SelectCandidates(assessments, profile);

            if (candidates.Count == 0)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Background applications",
                    Why = "No background application this profile may close is holding enough memory to be " +
                          "worth closing."
                });

                return;
            }

            var byId = (processes ?? Array.Empty<ProcessInfo>())
                .GroupBy(p => p.Id)
                .ToDictionary(g => g.Key, g => g.First());

            foreach (var candidate in candidates)
            {
                if (!byId.TryGetValue(candidate.ProcessId, out var process))
                {
                    // The process list moved between the scan and the planning. Skipping is correct: the
                    // identity cannot be established from a stale snapshot.
                    refusals.Add(new RefusedAction
                    {
                        What = $"Close {candidate.ProcessName}",
                        Why = "The process is no longer in the current scan, so it is not acted on."
                    });

                    continue;
                }

                if (process.CreationTimeUtc == default)
                {
                    refusals.Add(new RefusedAction
                    {
                        What = $"Close {candidate.ProcessName}",
                        Why = "The process's creation time could not be read, so its identity cannot be " +
                              "confirmed. A process id alone is not an identity."
                    });

                    continue;
                }

                var action = new OptimizationAction
                {
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = process.Name,
                    TargetPid = process.Id,
                    TargetCreationTimeUtc = process.CreationTimeUtc,
                    TargetImagePath = process.Path,
                    TargetProcessName = process.Name,
                    ResourceType = ResourceType.RAM,
                    RiskLevel = RiskLevel.Low,
                    Priority = 5,
                    EstimatedResourceRecovery = candidate.WorkingSet / 2,
                    Description = $"Close {candidate.ProcessName} (PID {candidate.ProcessId})",
                    Reason =
                        $"Approved for this profile while {profile.ResolveDisplayName()} runs: " +
                        candidate.Reason,
                    CanUndo = false,
                    RequiresAdmin = false
                };

                action.CaptureProcessIdentity(process);

                var confirmation = new OptimizationAction
                {
                    ActionType = OptimizationActionType.CloseProcess,
                    Target = process.Name,
                    TargetPid = process.Id,
                    TargetCreationTimeUtc = process.CreationTimeUtc,
                    TargetImagePath = process.Path,
                    Reason = "A closed background application cannot be restarted; the session records that " +
                             "it was closed so the user can start it again if they want it.",
                    CanUndo = false,
                    RiskLevel = RiskLevel.Low
                };

                // The close is not reversible, so the plan carries the honest statement of that instead
                // of an undo action that would pretend otherwise.
                action.UndoAction = null;
                action.Description += " (cannot be undone; recorded so you can start it again)";

                plan.Actions.Add(action);
                _ = confirmation;
            }
        }

        private void PlanPower(
            GameAppProfile profile,
            bool allowPowerChange,
            OptimizationPlan plan,
            List<RefusedAction> refusals)
        {
            if (!profile.Power.Enabled)
            {
                refusals.Add(new RefusedAction { What = "Power mode", Why = "The power section is off for this profile." });
                return;
            }

            if (profile.Power.ModeWhileRunning == PowerPreference.LeaveUnchanged)
                return;

            if (!allowPowerChange)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Power mode",
                    Why = "Power changes are switched off in this application's settings."
                });

                return;
            }

            // A power change is only planned when the current scheme can be read: without it, the original
            // cannot be restored, and an unrestorable change is not made.
            var activeScheme = Utilities.PowerSchemeManager.GetActiveSchemeName();

            if (string.IsNullOrWhiteSpace(activeScheme))
            {
                refusals.Add(new RefusedAction
                {
                    What = "Power mode",
                    Why = "The current power scheme could not be read, so the original could not be restored " +
                          "afterwards. No power change was planned."
                });

                return;
            }

            if (activeScheme.Contains("High performance", StringComparison.OrdinalIgnoreCase) &&
                profile.Power.ModeWhileRunning == PowerPreference.HighPerformance)
            {
                // Already what the profile wants; nothing to change, and saying so is more useful than a
                // no-op action that would appear in the history as if it had done something.
                refusals.Add(new RefusedAction
                {
                    What = "Power mode",
                    Why = $"The machine is already using '{activeScheme}'."
                });

                return;
            }

            plan.Actions.Add(new OptimizationAction
            {
                ActionType = OptimizationActionType.AdjustPowerSettings,
                Target = profile.Power.ModeWhileRunning.ToString(),
                ResourceType = ResourceType.CPU,
                RiskLevel = RiskLevel.Low,
                Priority = 6,
                Description = $"Use the {profile.Power.ModeWhileRunning} power mode while this application runs",
                Reason =
                    $"The profile requests it, the original scheme ('{activeScheme}') was recorded, and it is " +
                    "restored when the application exits.",
                CanUndo = true,
                RequiresAdmin = false,
                UndoAction = new OptimizationAction
                {
                    ActionType = OptimizationActionType.AdjustPowerSettings,
                    Target = activeScheme,
                    Reason = $"Restore the power scheme that was active before this session ('{activeScheme}').",
                    RiskLevel = RiskLevel.Low,
                    CanUndo = false
                }
            });
        }

        private GraphicsPreference? PlanGraphics(
            GameAppProfile profile,
            bool allowGraphicsChange,
            List<RefusedAction> refusals)
        {
            if (!profile.Gpu.Enabled)
            {
                refusals.Add(new RefusedAction { What = "Graphics preference", Why = "The GPU section is off for this profile." });
                return null;
            }

            if (profile.Gpu.GraphicsPreference == GraphicsPreference.LetWindowsDecide)
                return null;

            if (!allowGraphicsChange)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Graphics preference",
                    Why = "Graphics preference changes are switched off in this application's settings."
                });

                return null;
            }

            if (!GraphicsPreferenceService.IsSupported)
            {
                refusals.Add(new RefusedAction
                {
                    What = "Graphics preference",
                    Why = "Storing a graphics preference requires Windows."
                });

                return null;
            }

            return profile.Gpu.GraphicsPreference;
        }
    }
}
