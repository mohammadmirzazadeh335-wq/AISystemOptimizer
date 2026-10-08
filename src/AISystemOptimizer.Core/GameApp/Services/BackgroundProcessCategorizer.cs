using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// What the optimiser is allowed to do with one background process, and why.
    /// </summary>
    public sealed class BackgroundProcessAssessment
    {
        public int ProcessId { get; init; }

        public string ProcessName { get; init; } = string.Empty;

        public BackgroundProcessCategory Category { get; init; } = BackgroundProcessCategory.NeverClose;

        /// <summary>The reason, in the words the interface shows. Never empty.</summary>
        public string Reason { get; init; } = string.Empty;

        /// <summary>Working set in bytes, when it could be read.</summary>
        public long WorkingSet { get; init; }

        /// <summary>
        /// True when closing this process would be permitted by the safety layer. It is still only a
        /// permission: the actual close goes through the existing planner, validator and executor, and
        /// needs the user's confirmation where the policy requires it.
        /// </summary>
        public bool MayBeClosed => Category is BackgroundProcessCategory.SafeToClose
                                            or BackgroundProcessCategory.UsuallySafe;

        /// <summary>True when the optimiser will ask before doing anything.</summary>
        public bool RequiresConfirmation => Category == BackgroundProcessCategory.UserConfirmationRequired;

        /// <summary>One line for the log and the interface.</summary>
        public string Describe() =>
            $"{ProcessName} (PID {ProcessId}): {Category} - {Reason}" +
            (WorkingSet > 0 ? $", {WorkingSet / (1024.0 * 1024.0):F0} MB" : string.Empty);
    }

    /// <summary>
    /// Where a background process belongs, per the specification:
    ///
    ///   * Safe to close      - closing it cannot lose work: no window, no user session, not required.
    ///   * Usually safe       - a known background helper of the kind a user recognises, still checked.
    ///   * User confirmation  - everything the optimiser is not certain about.
    ///   * Never close        - Windows components, security software, drivers, shell, anything in use.
    ///
    /// The one rule that matters most: a familiar name is not evidence. "Known helper" here never means
    /// "I have seen this name before", because that is exactly how a malicious or merely unknown program
    /// gets waved through. A process reaches <see cref="BackgroundProcessCategory.UsuallySafe"/> only when
    /// the existing process analysis already classifies it as safe background work AND it is not in use,
    /// has no window, and is not on any protected list.
    ///
    /// Everything that changes the machine is still executed by the existing safety layer; this class only
    /// sorts.
    /// </summary>
    public static class BackgroundProcessCategorizer
    {
        /// <summary>
        /// Processes the optimiser will not close under any circumstances, whatever a profile says.
        /// These are checked after the existing critical-process list, not instead of it.
        /// </summary>
        private static readonly string[] HardProtectedNames =
        {
            // Shell and session
            "explorer", "sihost", "shellexperiencehost", "startmenuexperiencehost", "searchhost",
            "textinputhost", "ctfmon", "dwm", "fontdrvhost", "runtimebroker", "applicationframehost",
            "lockapp", "logonui", "useroobebroker", "windowsapplauncher",

            // Security: never touched, not even as administrator
            "msmpeng", "nissrv", "securityhealthservice", "securityhealthsystray", "mpdefendercoreservice",
            "windefend", "smartscreen", "mpsvc", "mpcmdrun", "firewall", "wscbroker", "wscsvc",
            "sense", "mssecflt", "hips", "avastsvc", "avp", "ekrn", "bdservicehost", "sophossps",

            // Input, audio, printers, display - closing these breaks the session
            "audiodg", "spoolsv", "printisolationhost", "wlanext", "tabtip", "inputmethod",

            // Sync clients that hold unsaved work in memory
            "onedrive", "dropbox", "googledrivesync", "backup",
        };

        /// <summary>
        /// Helpers that are, in the existing analysis, background work with no user-facing state. Being
        /// on this list is still not enough on its own: the process must also pass the checks below.
        /// </summary>
        private static readonly string[] TypicallySafeBackgroundNames =
        {
            "widgets", "gamebarwidgets", "xboxgamebarwidgets", "yourphone", "phoneexperiencehost",
            "cortana", "teamsmachinewideinstaller", "microsoftedgeupdate",
            "adobearm", "creativecloud", "ccxprocess", "node", "msedge_webview",
            "unrealcefsubprocess", "epicwebhelper", "steamwebhelper",
        };

        /// <summary>
        /// Categorise every process the existing analysis considers optimisable, plus everything that must
        /// never be touched so that the interface can show it.
        /// </summary>
        public static List<BackgroundProcessAssessment> AssessAll(
            IEnumerable<ProcessInfo> processes,
            GameAppProfile? profile = null,
            IEnumerable<NeverOptimizeEntry>? neverOptimize = null)
        {
            var assessments = new List<BackgroundProcessAssessment>();

            if (processes == null)
                return assessments;

            foreach (var process in processes.Where(p => p != null))
                assessments.Add(Assess(process, profile, neverOptimize));

            return assessments;
        }

        /// <summary>
        /// Categorise one process.
        /// </summary>
        public static BackgroundProcessAssessment Assess(
            ProcessInfo process,
            GameAppProfile? profile = null,
            IEnumerable<NeverOptimizeEntry>? neverOptimize = null)
        {
            if (process == null)
            {
                return new BackgroundProcessAssessment
                {
                    Category = BackgroundProcessCategory.NeverClose,
                    Reason = "No process was supplied."
                };
            }

            var name = ExecutablePathValidator.NormaliseExecutableName(process.Name);
            var workingSet = process.WorkingSet;

            BackgroundProcessAssessment Never(string reason) => new BackgroundProcessAssessment
            {
                ProcessId = process.Id,
                ProcessName = name,
                Category = BackgroundProcessCategory.NeverClose,
                Reason = reason,
                WorkingSet = workingSet
            };

            // 1. The existing hard protections come first and cannot be overridden by anything below.
            if (AISystemOptimizer.Core.Constants.CriticalProcesses.IsCritical(process.Name, process.Path, process.IsService))
                return Never("Protected Windows component.");

            if (HardProtectedNames.Contains(name, StringComparer.OrdinalIgnoreCase))
            {
                return name.ToLowerInvariant() switch
                {
                    "explorer" => Never("The Windows shell. Restarting it is offered as a separate action, never as an optimisation."),
                    "dwm" or "fontdrvhost" => Never("Part of the Windows display system."),
                    "audiodg" or "spoolsv" => Never("Handles a device other programs are using."),
                    "onedrive" or "dropbox" or "googledrivesync" or "backup" => Never("It may hold unsaved changes."),
                    _ => Never("Windows component or security software, which this application never closes."),
                };
            }

            // 2. Its own profile's binary says it must not be touched.
            if (ProcessHelper.IsGameProcess(process.Name, process.Path))
                return Never("It looks like a game; closing another game is never part of an optimisation.");

            // 3. The user's own never-optimise list. It can only add restrictions.
            if (neverOptimize != null && neverOptimize.Any(entry => entry != null && entry.Matches(
                    process.Name, process.Path, process.Publisher, null)))
            {
                return Never("You added it to the never-optimise list.");
            }

            // 4. In use, or showing a window: nothing with unsaved work is ever closed automatically.
            if (process.HasVisibleWindow)
                return Never("It has an open window, so it may have unsaved work.");

            if (process.IsActive || process.IsForeground)
            {
                // "In use" is never inferred from a name or a window handle alone: the scanner sets
                // IsActive, and IsForeground is read from the live foreground window.
                return Never("It appears to be in use.");
            }

            // 5. A profile rule for this exact executable overrides the default, in the restrictive
            //    direction only: NeverOptimize always wins, and Allow merely permits the checks below.
            var decision = BackgroundProcessRule.Resolve(
                profile?.BackgroundRules, process.Name, process.Path);

            if (decision == BackgroundProcessDecision.NeverOptimize)
                return Never("Your rule for this profile says never to close it.");

            // 6. System and service processes are never touched here: they are managed, if at all, by the
            //    service and start-up pages, which have their own rules and their own undo.
            if (process.IsService || process.IsWindowsProcess || process.Category == ProcessCategory.System)
                return Never("A system process or service. Those are managed from the Services page.");

            if (process.IsSecurity || process.Category == ProcessCategory.Security)
                return Never("Security software. Never closed, not even when running as administrator.");

            if (!process.CanBeTerminated)
                return Never("Windows does not allow this process to be terminated.");

            // 7. Memory: closing a process that holds almost nothing achieves nothing, and every closed
            //    process is a small risk, so the trivial ones are left alone rather than reported as wins.
            var minimumBytes = (profile?.Ram.MinimumWorkingSetMegabytes ?? 50) * 1024L * 1024L;

            if (workingSet > 0 && workingSet < minimumBytes)
            {
                return new BackgroundProcessAssessment
                {
                    ProcessId = process.Id,
                    ProcessName = name,
                    Category = BackgroundProcessCategory.UserConfirmationRequired,
                    Reason =
                        $"It holds only {workingSet / (1024.0 * 1024.0):F0} MB, so closing it would free " +
                        $"almost nothing. Your profile only considers processes above " +
                        $"{minimumBytes / (1024 * 1024)} MB.",
                    WorkingSet = workingSet
                };
            }

            // 8. Its own profile's mode decides the rest.
            if (profile != null && !profile.Ram.CloseBackgroundProcesses)
            {
                return new BackgroundProcessAssessment
                {
                    ProcessId = process.Id,
                    ProcessName = name,
                    Category = BackgroundProcessCategory.UserConfirmationRequired,
                    Reason = "This profile is set not to close background applications.",
                    WorkingSet = workingSet
                };
            }

            if (decision == BackgroundProcessDecision.AllowOptimization)
            {
                return new BackgroundProcessAssessment
                {
                    ProcessId = process.Id,
                    ProcessName = name,
                    Category = BackgroundProcessCategory.UsuallySafe,
                    Reason = "You approved closing this application when this profile runs.",
                    WorkingSet = workingSet
                };
            }

            // 9. The existing analysis classifies background work; that classification - not the name - is
            //    what allows a process into the "usually safe" group, and only when it is not the
            //    application being optimised and holds nothing.
            var isKnownBackground = TypicallySafeBackgroundNames.Contains(name, StringComparer.OrdinalIgnoreCase)
                                    || process.Category == ProcessCategory.BackgroundApplication
                                    || process.RiskLevel == RiskLevel.Low;

            if (isKnownBackground && !process.IsActive && !process.HasVisibleWindow)
            {
                return new BackgroundProcessAssessment
                {
                    ProcessId = process.Id,
                    ProcessName = name,
                    Category = BackgroundProcessCategory.UsuallySafe,
                    Reason =
                        "Background work with no window and no user session, classified as low risk by the " +
                        "existing analysis. It is still only closed after confirmation unless your profile " +
                        "approved it.",
                    WorkingSet = workingSet
                };
            }

            // 10. Anything else: the user decides, every time.
            return new BackgroundProcessAssessment
            {
                ProcessId = process.Id,
                ProcessName = name,
                Category = BackgroundProcessCategory.UserConfirmationRequired,
                Reason =
                    "The optimiser is not certain what this program is doing, so it will not close it " +
                    "without asking you first.",
                WorkingSet = workingSet
            };
        }

        /// <summary>
        /// The candidates a profile may act on, ordered by what closing them would actually achieve.
        /// </summary>
        public static List<BackgroundProcessAssessment> SelectCandidates(
            IEnumerable<BackgroundProcessAssessment> assessments,
            GameAppProfile profile,
            int? maximumCount = null)
        {
            if (assessments == null || profile == null)
                return new List<BackgroundProcessAssessment>();

            var limit = maximumCount
                        ?? Math.Max(0, profile.Ram.MaxBackgroundProcessesPerSession);

            if (limit <= 0)
                return new List<BackgroundProcessAssessment>();

            return assessments
                .Where(a => a.MayBeClosed)
                .OrderByDescending(a => a.WorkingSet)
                .Take(limit)
                .ToList();
        }

        /// <summary>
        /// A short summary of an assessment set, for the interface.
        /// </summary>
        public static string Summarise(IEnumerable<BackgroundProcessAssessment> assessments)
        {
            var list = assessments?.ToList() ?? new List<BackgroundProcessAssessment>();

            if (list.Count == 0)
                return "No process was examined.";

            var freed = list.Where(a => a.MayBeClosed).Sum(a => a.WorkingSet);

            return
                $"{list.Count} process(es) examined: " +
                $"{list.Count(a => a.Category == BackgroundProcessCategory.SafeToClose)} safe to close, " +
                $"{list.Count(a => a.Category == BackgroundProcessCategory.UsuallySafe)} usually safe, " +
                $"{list.Count(a => a.Category == BackgroundProcessCategory.UserConfirmationRequired)} need " +
                $"your confirmation, {list.Count(a => a.Category == BackgroundProcessCategory.NeverClose)} " +
                $"never closed. Closing the candidates would free about {freed / (1024.0 * 1024.0):F0} MB.";
        }
    }
}
