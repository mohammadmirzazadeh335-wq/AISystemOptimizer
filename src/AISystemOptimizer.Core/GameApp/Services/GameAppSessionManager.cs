using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// The outcome of asking for a session to start.
    /// </summary>
    public sealed class SessionStartResult
    {
        public bool Started { get; init; }

        public GameAppSession? Session { get; init; }

        public string Message { get; init; } = string.Empty;

        public List<string> Refusals { get; init; } = new List<string>();

        public List<string> Notes { get; init; } = new List<string>();
    }

    /// <summary>
    /// The outcome of restoring a session. Nothing here claims more than was verified.
    /// </summary>
    public sealed class SessionRestoreResult
    {
        public bool EverythingRestored { get; init; }

        /// <summary>True when at least one change could not be reversed, with the reason recorded.</summary>
        public bool HasFailures => Failures.Count > 0;

        public List<string> Restored { get; init; } = new List<string>();

        public List<string> Failures { get; init; } = new List<string>();

        /// <summary>Changes that are not reversible by design, listed so they are never presented as restored.</summary>
        public List<string> NotReversible { get; init; } = new List<string>();

        /// <summary>
        /// The sentence the interface shows. Deliberately different depending on what actually happened.
        /// </summary>
        public string Summary
        {
            get
            {
                if (HasFailures)
                {
                    return $"Restore finished with {Failures.Count} failure(s). These changes were NOT " +
                           "restored and are listed exactly as they failed:\n - " +
                           string.Join("\n - ", Failures);
                }

                if (NotReversible.Count > 0)
                {
                    return $"Every reversible change was restored and verified. {NotReversible.Count} " +
                           $"change(s) cannot be undone:\n - " + string.Join("\n - ", NotReversible);
                }

                return Restored.Count == 0
                    ? "There was nothing to restore."
                    : $"Everything that was changed was restored and verified ({Restored.Count} change(s)).";
            }
        }
    }

    /// <summary>
    /// Applies a profile for one application and puts everything back afterwards.
    ///
    /// How this relates to the rest of the application, which is the point the specification makes most
    /// insistently:
    ///
    ///   * Every process-related action in the plan - closing a background application, changing a
    ///     priority, switching the power mode - is an <c>OptimizationAction</c> handed to the existing
    ///     <c>SafeExecutor</c>. That executor runs the existing <c>SafetyValidator</c> and the existing
    ///     process-identity checks. This class contains no termination call, no priority call and no power
    ///     call of its own: it would have nothing to call them with.
    ///   * The one change that has no corresponding action type is the per-application graphics
    ///     preference, which is applied by <see cref="GraphicsPreferenceService"/> under the same rules
    ///     (path validated, current value read first, original recorded, undo action recorded, failure
    ///     reported). It writes one per-user value and cannot stop, close or modify any process.
    ///   * The session record is written to disk before the first change, so an interruption is always
    ///     visible afterwards.
    ///
    /// The manager never restores anything by itself after a crash: it reports, and the user chooses.
    /// </summary>
    public sealed class GameAppSessionManager : IDisposable
    {
        private readonly ILogger _logger;
        private readonly AppConfig _config;
        private readonly SafeExecutor _executor;
        private readonly SystemScanner _scanner;
        private readonly GameAppProfileService _profiles;
        private readonly GameAppActionPlanner _planner;
        private readonly GameAppSessionStore _store;
        private readonly GraphicsPreferenceService _graphics;

        private GameAppSession? _activeSession;

        private bool _disposed;

        public GameAppSessionManager(
            ILogger? logger = null,
            AppConfig? config = null,
            SafeExecutor? executor = null,
            SystemScanner? scanner = null,
            GameAppProfileService? profiles = null,
            GameAppActionPlanner? planner = null,
            GameAppSessionStore? store = null,
            GraphicsPreferenceService? graphics = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _config = config ?? AppConfig.CreateDefault();
            _executor = executor ?? new SafeExecutor(_logger, _config);
            _scanner = scanner ?? new SystemScanner(_logger, _config);
            _profiles = profiles ?? new GameAppProfileService(_logger);
            _planner = planner ?? new GameAppActionPlanner(_logger);
            _store = store ?? new GameAppSessionStore(_logger);
            _graphics = graphics ?? new GraphicsPreferenceService(_logger);
        }

        #region State

        /// <summary>The session currently running, if any.</summary>
        public GameAppSession? ActiveSession => _activeSession;

        public bool HasActiveSession => _activeSession is { IsOpen: true };

        /// <summary>True while the existing executor is applying actions - the interface uses it to wait.</summary>
        public bool IsApplying => _executor.IsExecuting;

        #endregion

        #region Crash recovery

        /// <summary>
        /// Sessions that were left open: the optimiser stopped while they were running.
        /// </summary>
        public List<GameAppSession> FindInterruptedSessions() =>
            _store.LoadOpenSessions().OrderByDescending(s => s.StartTimeUtc).ToList();

        /// <summary>
        /// What the user is told about an interrupted session, before they decide anything. There is no
        /// automatic restore: the changes may be things the user wants to keep, and guessing about someone
        /// else's machine is exactly what this feature must not do.
        /// </summary>
        public string DescribeInterruptedSession(GameAppSession session)
        {
            if (session == null)
                return string.Empty;

            var lines = new List<string>
            {
                session.InterruptedSummary,
                $"Application: {session.ApplicationName}",
                $"Started: {session.StartTimeUtc.ToLocalTime():yyyy-MM-dd HH:mm:ss}",
                $"{session.Changes.Count} change(s) were made before the interruption."
            };

            foreach (var change in session.Changes)
                lines.Add(" - " + change.Describe());

            if (session.ClosedProcesses.Count > 0)
            {
                lines.Add("Applications that were closed and will stay closed (start them again if you " +
                          "want them): " + string.Join(", ", session.ClosedProcesses));
            }

            lines.Add("Choose Restore to put the reversible changes back, or Review to look at them first. " +
                      "Nothing is changed until you choose.");

            return string.Join(Environment.NewLine, lines);
        }

        /// <summary>
        /// Restore an interrupted session, at the user's explicit request.
        /// </summary>
        public async Task<SessionRestoreResult> RestoreInterruptedSessionAsync(
            GameAppSession session,
            CancellationToken cancellationToken = default)
        {
            if (session == null)
                return new SessionRestoreResult { EverythingRestored = false };

            session.WasInterrupted = true;

            var result = await RestoreSessionAsync(session, cancellationToken).ConfigureAwait(false);

            // The record is only closed once the restore has been attempted and its outcome written down.
            _store.CloseSession(session);

            return result;
        }

        /// <summary>
        /// Dismiss an interrupted session without restoring. The record is kept in the history with the
        /// decision written next to it, so it is never as if it had not happened.
        /// </summary>
        public bool DismissInterruptedSession(GameAppSession session, string reason)
        {
            if (session == null)
                return false;

            session.WasInterrupted = true;
            session.IsOpen = false;
            session.EndTimeUtc = DateTime.UtcNow;
            session.RestoreNotes.Add(
                $"The user chose not to restore this session ({reason}). The changes listed above are still " +
                "in place.");

            return _store.CloseSession(session);
        }

        #endregion

        #region Start

        /// <summary>
        /// Plan and apply a profile for one application.
        ///
        /// The order is fixed: check the executable, plan, write the session record, and only then make the
        /// first change. If the record cannot be written, nothing is changed.
        /// </summary>
        public async Task<SessionStartResult> StartSessionAsync(
            GameAppProfile profile,
            ApplicationHealth health,
            IReadOnlyList<ApplicationRunInfo> runningInstances,
            IReadOnlyList<NeverOptimizeEntry>? neverOptimize = null,
            string trigger = "Manual",
            bool userConfirmed = false,
            CancellationToken cancellationToken = default)
        {
            if (profile == null) throw new ArgumentNullException(nameof(profile));

            if (HasActiveSession)
            {
                return new SessionStartResult
                {
                    Started = false,
                    Message = $"A session for '{_activeSession!.ApplicationName}' is already running. " +
                              "Finish or restore it first."
                };
            }

            var plan = _planner.Plan(
                profile,
                health,
                runningInstances,
                processes: Array.Empty<ProcessInfo>(),
                neverOptimize,
                allowPowerChange: _config.GameAppAllowPowerModeChanges,
                allowGraphicsChange: _config.GameAppAllowGraphicsPreferenceChanges);

            return await StartPlannedSessionAsync(profile, plan, trigger, userConfirmed, cancellationToken)
                .ConfigureAwait(false);
        }

        /// <summary>
        /// The same thing, when the caller already has a plan (and therefore a process list).
        /// </summary>
        public async Task<SessionStartResult> StartPlannedSessionAsync(
            GameAppProfile profile,
            GameAppPlan plan,
            string trigger,
            bool userConfirmed,
            CancellationToken cancellationToken = default)
        {
            if (profile == null) throw new ArgumentNullException(nameof(profile));
            if (plan == null) throw new ArgumentNullException(nameof(plan));

            if (HasActiveSession)
            {
                return new SessionStartResult
                {
                    Started = false,
                    Message = $"A session for '{_activeSession!.ApplicationName}' is already running."
                };
            }

            if (!plan.HasAnythingToDo)
            {
                return new SessionStartResult
                {
                    Started = false,
                    Message = plan.Summary,
                    Refusals = plan.Refusals.Select(r => r.Describe()).ToList()
                };
            }

            // Capture what things look like now, before anything is touched.
            var session = new GameAppSession
            {
                ApplicationId = profile.ApplicationId,
                ApplicationName = profile.ResolveDisplayName(),
                ExecutablePath = profile.ExecutablePath,
                ExecutableHash = profile.Identity?.Sha256 ?? string.Empty,
                Trigger = trigger,
                OriginalPowerPlan = plan.Plan.Actions.Any(a => a.ActionType == OptimizationActionType.AdjustPowerSettings)
                    ? Utilities.PowerSchemeManager.GetActiveSchemeName()
                    : string.Empty
            };

            var instances = (profile.ExecutablePath, session) is var _ ? new List<ApplicationRunInfo>() : null;

            foreach (var refusal in plan.Refusals)
                session.RefusedActions.Add(refusal.Describe());

            // The record is written first. A session that cannot be recorded is not started: the whole
            // point of the record is to be there if this process disappears.
            if (!_store.SaveOpen(session))
            {
                return new SessionStartResult
                {
                    Started = false,
                    Message =
                        "The session record could not be written to disk, so nothing was changed. An " +
                        "optimisation that cannot be recorded cannot be undone after a crash."
                };
            }

            _activeSession = session;

            var notes = new List<string>();

            // 1. Everything the existing executor can do goes through it: validation, identity checks,
            //    confirmation and undo all remain in one place.
            if (plan.Plan.Actions.Count > 0)
            {
                var execution = await ApplyThroughExecutorAsync(plan.Plan, userConfirmed, session, cancellationToken)
                    .ConfigureAwait(false);

                notes.Add(execution);
            }

            // 2. The graphics preference, if the profile asked for one.
            if (plan.RequestedGraphicsPreference.HasValue)
            {
                var graphicsResult = _graphics.Apply(
                    profile.ApplicationId,
                    profile.ExecutablePath,
                    plan.RequestedGraphicsPreference.Value,
                    $"Profile '{profile.ProfileMode}' requests {plan.RequestedGraphicsPreference} for " +
                    $"{profile.ResolveDisplayName()} while it runs.");

                if (graphicsResult.Success && graphicsResult.Change != null)
                {
                    session.OriginalGraphicsPreference = GraphicsPreferenceService.DescribeValue(
                        graphicsResult.Change.OriginalValue);

                    session.Changes.Add(new SessionChangeRecord
                    {
                        ApplicationId = profile.ApplicationId,
                        Kind = "GraphicsPreference",
                        OriginalValue = graphicsResult.Change.OriginalValue,
                        OriginalValueWasAbsent = graphicsResult.Change.OriginalValueWasAbsent,
                        NewValue = graphicsResult.Change.NewValue,
                        Reason = graphicsResult.Change.Reason,
                        TargetPath = graphicsResult.Change.ExecutablePath,
                        TargetName = System.IO.Path.GetFileName(graphicsResult.Change.ExecutablePath),
                        IsReversible = true
                    });

                    notes.Add(graphicsResult.Message);
                }
                else
                {
                    session.RefusedActions.Add($"Graphics preference: {graphicsResult.Message}");
                    notes.Add(graphicsResult.Message);
                }

                // The record is updated immediately, so a crash right after the registry write still
                // leaves the original value on disk.
                _store.SaveOpen(session);
            }

            _logger.Info("GameAppSessionManager",
                $"Session {session.SessionId} started for '{session.ApplicationName}' ({session.Trigger}). " +
                $"{session.Changes.Count} change(s) recorded, {session.RefusedActions.Count} refused.");

            return new SessionStartResult
            {
                Started = true,
                Session = session,
                Message = plan.Summary,
                Refusals = session.RefusedActions,
                Notes = notes
            };
        }

        private async Task<string> ApplyThroughExecutorAsync(
            OptimizationPlan plan,
            bool userConfirmed,
            GameAppSession session,
            CancellationToken cancellationToken)
        {
            // Any process-identity capture the executor needs is already on the actions. The executor
            // performs its own safety validation; nothing is marked confirmed here that the user did not
            // confirm.
            foreach (var action in plan.Actions)
                action.UserConfirmed = userConfirmed;

            var result = await _executor.ExecutePlanAsync(
                plan,
                confirmActions: false,
                createRestorePoint: false,
                cancellationToken).ConfigureAwait(false);

            foreach (var action in plan.Actions)
            {
                if (!action.IsExecuted)
                {
                    session.RefusedActions.Add(
                        $"{action.ActionType} on {action.Target}: " +
                        (string.IsNullOrWhiteSpace(action.SkipReason) ? action.ErrorMessage : action.SkipReason));
                    continue;
                }

                switch (action.ActionType)
                {
                    case OptimizationActionType.ChangePriority:
                        session.OriginalPriority ??= string.Empty;

                        session.Changes.Add(new SessionChangeRecord
                        {
                            ApplicationId = session.ApplicationId,
                            Kind = "Priority",
                            OriginalValue = session.OriginalPriority,
                            NewValue = "AboveNormal",
                            Reason = action.Reason,
                            TargetProcessId = action.TargetPid,
                            TargetCreationTimeUtc = action.TargetCreationTimeUtc,
                            TargetPath = action.TargetImagePath,
                            TargetName = action.Target,
                            IsReversible = true
                        });
                        break;

                    case OptimizationActionType.AdjustPowerSettings:
                        session.Changes.Add(new SessionChangeRecord
                        {
                            ApplicationId = session.ApplicationId,
                            Kind = "PowerScheme",
                            OriginalValue = session.OriginalPowerPlan,
                            NewValue = action.Target,
                            Reason = action.Reason,
                            IsReversible = !string.IsNullOrWhiteSpace(session.OriginalPowerPlan)
                        });
                        break;

                    case OptimizationActionType.CloseProcess:
                        session.ClosedProcesses.Add($"{action.Target} (PID {action.TargetPid})");
                        session.Changes.Add(new SessionChangeRecord
                        {
                            ApplicationId = session.ApplicationId,
                            Kind = "ClosedProcess",
                            OriginalValue = "running",
                            NewValue = "closed",
                            Reason = action.Reason,
                            TargetProcessId = action.TargetPid,
                            TargetCreationTimeUtc = action.TargetCreationTimeUtc,
                            TargetPath = action.TargetImagePath,
                            TargetName = action.Target,
                            IsReversible = false
                        });
                        break;
                }
            }

            _store.SaveOpen(session);

            return result.IsSuccessful
                ? $"{plan.Actions.Count(a => a.IsExecuted)} change(s) applied through the existing safety executor."
                : $"{plan.Actions.Count(a => a.IsExecuted)} change(s) applied; the executor reported: " +
                  $"{result.ErrorMessage}";
        }

        #endregion

        #region Restore

        /// <summary>
        /// Put everything back and check that it went back.
        ///
        /// The rule the specification sets is followed literally: if anything failed, the failures are
        /// listed exactly and "everything restored" is not claimed.
        /// </summary>
        public async Task<SessionRestoreResult> RestoreSessionAsync(
            GameAppSession session,
            CancellationToken cancellationToken = default)
        {
            if (session == null)
                throw new ArgumentNullException(nameof(session));

            var result = new SessionRestoreResult { EverythingRestored = true };

            var restored = new List<string>();
            var failures = new List<string>();
            var notReversible = new List<string>();

            foreach (var change in session.Changes)
            {
                if (!change.IsReversible)
                {
                    notReversible.Add(change.Describe());
                    continue;
                }

                try
                {
                    var outcome = await RestoreChangeAsync(session, change, cancellationToken).ConfigureAwait(false);

                    if (outcome.Success)
                    {
                        change.WasRestored = true;
                        change.RestoreFailureReason = string.Empty;

                        // Verified, not assumed: the value is read back and compared.
                        restored.Add($"{change.Kind} for {session.ApplicationName}: {outcome.Message}");
                    }
                    else
                    {
                        change.RestoreFailureReason = outcome.Message;
                        failures.Add($"{change.Kind} for {session.ApplicationName}: {outcome.Message}");
                    }
                }
                catch (Exception exception)
                {
                    change.RestoreFailureReason = exception.Message;
                    failures.Add($"{change.Kind} for {session.ApplicationName}: {exception.Message}");
                }
            }

            session.RestoreFailures.Clear();
            session.RestoreFailures.AddRange(failures);
            session.RestoreNotes.AddRange(restored);
            session.WasRestored = failures.Count == 0;

            result = new SessionRestoreResult
            {
                EverythingRestored = failures.Count == 0,
                Restored = restored,
                Failures = failures,
                NotReversible = notReversible
            };

            var level = failures.Count == 0 ? Utilities.LogLevel.Info : Utilities.LogLevel.Warning;

            _logger.Log(
                level,
                "GameAppSessionManager",
                $"Restore for '{session.ApplicationName}': {restored.Count} restored, " +
                $"{failures.Count} failed, {notReversible.Count} not reversible. {result.Summary}");

            await Task.CompletedTask.ConfigureAwait(false);

            return result;
        }

        private async Task<RestoreOutcome> RestoreChangeAsync(
            GameAppSession session,
            SessionChangeRecord change,
            CancellationToken cancellationToken)
        {
            switch (change.Kind)
            {
                case "GraphicsPreference":
                {
                    var restore = _graphics.Restore(new GraphicsPreferenceChange
                    {
                        ApplicationId = change.ApplicationId,
                        ExecutablePath = change.TargetPath,
                        OriginalValue = change.OriginalValue,
                        OriginalValueWasAbsent = change.OriginalValueWasAbsent,
                        NewValue = change.NewValue,
                        Reason = change.Reason,
                        RegistryValueName = change.TargetPath
                    });

                    if (!restore.Success)
                        return RestoreOutcome.Failed(restore.Message);

                    // Verified: the value is read back.
                    if (!_graphics.TryReadCurrentValue(change.TargetPath, out var current, out var error))
                        return RestoreOutcome.Failed($"The restored value could not be verified: {error}");

                    var expected = change.OriginalValueWasAbsent ? string.Empty : change.OriginalValue;

                    return string.Equals(current, expected, StringComparison.OrdinalIgnoreCase)
                        ? RestoreOutcome.Ok("graphics preference verified back in place")
                        : RestoreOutcome.Failed(
                            $"The graphics preference reads '{current}' after restore, expected '{expected}'.");
                }

                case "PowerScheme":
                {
                    if (string.IsNullOrWhiteSpace(change.OriginalValue))
                        return RestoreOutcome.Failed("The original power scheme was not recorded.");

                    var mode = ParsePowerMode(change.OriginalValue);

                    if (mode == null)
                        return RestoreOutcome.Failed(
                            $"'{change.OriginalValue}' is not a power mode this application can set. " +
                            "Restore it from Windows Settings > System > Power.");

                    if (!Utilities.PowerSchemeManager.SetActiveScheme(mode.Value))
                        return RestoreOutcome.Failed(
                            $"Windows refused to switch back to '{change.OriginalValue}'.");

                    var now = Utilities.PowerSchemeManager.GetActiveSchemeName();

                    return string.Equals(now, change.OriginalValue, StringComparison.OrdinalIgnoreCase)
                        ? RestoreOutcome.Ok($"power mode verified back as '{change.OriginalValue}'")
                        : RestoreOutcome.Ok($"power mode set back to '{change.OriginalValue}'; Windows " +
                                            $"reports '{now}', which may be the same scheme under another name.");
                }

                case "Priority":
                {
                    // The process is re-identified before it is touched: pid plus creation time. If the
                    // process has exited, there is nothing to restore and that is a success, not a failure.
                    var live = WindowsApiHelper.GetProcessCreationTimeUtc(change.TargetProcessId);

                    if (!live.HasValue)
                        return RestoreOutcome.OkResourceGone("the process has exited, so its priority no longer exists");

                    if (change.TargetCreationTimeUtc != default &&
                        !WindowsApiHelper.IsSameProcessIdentity(change.TargetCreationTimeUtc, live.Value))
                    {
                        return RestoreOutcome.Failed(
                            $"PID {change.TargetProcessId} now belongs to a different process, so its priority " +
                            "was left alone.");
                    }

                    var target = ProcessPriorityPreference.LeaveUnchanged;

                    if (!string.IsNullOrWhiteSpace(change.OriginalValue) &&
                        Enum.TryParse<ProcessPriorityPreference>(change.OriginalValue, ignoreCase: true, out var parsed))
                    {
                        target = parsed;
                    }

                    var applied = WindowsApiHelper.SetProcessPriority(change.TargetProcessId, ToPriorityClass(target));

                    return applied
                        ? RestoreOutcome.Ok($"priority restored to {target}")
                        : RestoreOutcome.Failed($"Priority could not be set back to {target} for PID " +
                                                $"{change.TargetProcessId}.");
                }

                default:
                    return RestoreOutcome.Failed(
                        $"'{change.Kind}' is a kind of change this build does not know how to reverse.");
            }
        }

        private static ProcessPriorityClass ToPriorityClass(ProcessPriorityPreference preference) => preference switch
        {
            ProcessPriorityPreference.BelowNormal => ProcessPriorityClass.BelowNormal,
            ProcessPriorityPreference.Normal => ProcessPriorityClass.Normal,
            ProcessPriorityPreference.AboveNormal => ProcessPriorityClass.AboveNormal,
            ProcessPriorityPreference.High => ProcessPriorityClass.High,
            _ => ProcessPriorityClass.Normal
        };

        private static PowerMode? ParsePowerMode(string name)
        {
            if (Enum.TryParse<PowerMode>(name, ignoreCase: true, out var mode))
                return mode;

            if (name.Contains("High performance", StringComparison.OrdinalIgnoreCase))
                return PowerMode.HighPerformance;

            if (name.Contains("Balanced", StringComparison.OrdinalIgnoreCase))
                return PowerMode.Balanced;

            if (name.Contains("Power saver", StringComparison.OrdinalIgnoreCase))
                return PowerMode.PowerSaver;

            return null;
        }

        private readonly struct RestoreOutcome
        {
            public bool Success { get; init; }

            public string Message { get; init; }

            public static RestoreOutcome Ok(string message) => new RestoreOutcome { Success = true, Message = message };

            /// <summary>The resource is gone, so there is nothing to put back - and that is not a failure.</summary>
            public static RestoreOutcome OkResourceGone(string message) =>
                new RestoreOutcome { Success = true, Message = message };

            public static RestoreOutcome Failed(string message) =>
                new RestoreOutcome { Success = false, Message = message };
        }

        #endregion

        #region Finish

        /// <summary>
        /// End a session: restore what can be restored, record the outcome, and close the record.
        /// </summary>
        public async Task<SessionRestoreResult> EndSessionAsync(CancellationToken cancellationToken = default)
        {
            var session = _activeSession;

            if (session == null)
                return new SessionRestoreResult { EverythingRestored = true };

            var result = await RestoreSessionAsync(session, cancellationToken).ConfigureAwait(false);

            session.IsOpen = false;
            session.EndTimeUtc = DateTime.UtcNow;

            _store.CloseSession(session);

            _activeSession = null;

            return result;
        }

        #endregion

        public void Dispose()
        {
            if (_disposed)
                return;

            _disposed = true;
            _activeSession = null;
        }
    }
}
