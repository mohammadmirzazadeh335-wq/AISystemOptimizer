using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography.X509Certificates;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Process level helpers: classification, inspection, and *guarded* termination.
    ///
    /// Any method that ends a process or changes a service is written so that it refuses
    /// to act on critical/protected targets even if the caller asks it to. The Safety Layer
    /// is the primary defence; these checks are the second line of defence.
    /// </summary>
    public static class ProcessHelper
    {
        #region Inspection

        /// <summary>
        /// Build a fully populated <see cref="ProcessInfo"/> for a live process.
        /// </summary>
        public static ProcessInfo GetProcessInfo(Process process)
        {
            var info = new ProcessInfo(process);
            Enrich(info);
            return info;
        }

        /// <summary>
        /// Build a <see cref="ProcessInfo"/> from a pid (null when the process is gone).
        /// </summary>
        public static ProcessInfo? GetProcessInfo(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return GetProcessInfo(process);
                }
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// All instances of a process name (without the .exe extension).
        /// </summary>
        public static List<ProcessInfo> GetProcessesByName(string processName)
        {
            var result = new List<ProcessInfo>();

            try
            {
                var name = Path.GetFileNameWithoutExtension(processName);

                foreach (var process in Process.GetProcessesByName(name))
                {
                    try
                    {
                        result.Add(GetProcessInfo(process));
                    }
                    catch { }
                    finally
                    {
                        try { process.Dispose(); } catch { }
                    }
                }
            }
            catch { }

            return result;
        }

        /// <summary>
        /// Snapshot of every process on the machine.
        /// </summary>
        public static List<ProcessInfo> GetAllProcesses()
        {
            var result = new List<ProcessInfo>();

            foreach (var process in Process.GetProcesses())
            {
                try
                {
                    result.Add(GetProcessInfo(process));
                }
                catch { }
                finally
                {
                    try { process.Dispose(); } catch { }
                }
            }

            return result;
        }

        /// <summary>
        /// Fill in the derived properties that require extra API calls.
        /// </summary>
        private static void Enrich(ProcessInfo info)
        {
            try
            {
                info.IsService = IsServiceProcess(info.Id);

                if (info.IsService)
                    info.ServiceName = GetServiceNameFromProcessId(info.Id) ?? string.Empty;

                info.Category = CriticalProcesses.GetProcessCategory(info.Name, info.Path, info.IsService);
                info.RiskLevel = CriticalProcesses.GetProcessRiskLevel(info.Name, info.Category);
                info.IsWindowsProcess = CriticalProcesses.IsWindowsSystemProcess(info.Name);
                info.IsDriver = CriticalProcesses.IsDriverProcess(info.Name);
                info.IsSecurity = CriticalProcesses.IsSecurityProcess(info.Name) ||
                                  info.Category == ProcessCategory.Security;
                info.HasVisibleWindow = WindowsApiHelper.HasVisibleWindow(info.Id);
                info.IsForeground = WindowsApiHelper.IsForegroundProcess(info.Id);

                // A process counts as "in use" when it owns a visible window, owns the foreground
                // window, or is a fullscreen foreground window (an exclusive-fullscreen game).
                info.IsActive = info.HasVisibleWindow || info.IsForeground;
                info.SignatureStatus = GetSignatureStatus(info.Path);
                info.SessionId = WindowsApiHelper.GetProcessSessionId(info.Id);
                info.UserName = WindowsApiHelper.GetProcessOwner(info.Id);
                info.CommandLine = WindowsApiHelper.GetProcessCommandLine(info.Id);

                if (info.ParentId <= 0)
                {
                    info.ParentId = WindowsApiHelper.GetParentProcessId(info.Id);
                    if (info.ParentId > 0)
                    {
                        var parent = WindowsApiHelper.GetProcessById(info.ParentId);
                        if (parent != null)
                        {
                            info.ParentProcessName = parent.ProcessName;
                        }
                    }
                }

                info.ThreadCount = GetProcessThreadCount(info.Id);
                info.HandleCount = GetProcessHandleCount(info.Id);
                info.Is64Bit = Is64BitProcess(info.Id);
            }
            catch { }
        }

        #endregion

        #region Classification

        /// <summary>
        /// Is the process a game (used by Game Mode detection)?
        /// </summary>
        public static bool IsGameProcess(ProcessInfo info)
        {
            if (info == null) return false;
            return info.Category == ProcessCategory.Game || IsGameProcess(info.Name, info.Path);
        }

        /// <summary>
        /// Name/path based game detection using the configurable keyword list.
        /// </summary>
        public static bool IsGameProcess(string name, string path)
        {
            var haystack = $"{name} {path}".ToLowerInvariant();

            var genericKeywords = new[]
            {
                "game", "shipping", "binaries", "win64", "-win64", "unityplayer",
                "unreal", "engine\\binaries", "\\games\\", "gamelauncher"
            };

            foreach (var keyword in genericKeywords)
            {
                if (haystack.Contains(keyword))
                    return true;
            }

            return false;
        }

        /// <summary>
        /// Is the process a game launcher / store client?
        /// </summary>
        public static bool IsLauncherProcess(ProcessInfo info)
        {
            if (info == null) return false;

            var launchers = new[]
            {
                "steam", "epicgameslauncher", "epicwebhelper", "origin", "eadesktop",
                "uplay", "ubisoftconnect", "battle.net", "blizzard", "galaxyclient",
                "gog", "riotclient", "bethesdalauncher", "rockstar", "socialclub"
            };

            var name = info.Name.ToLowerInvariant();
            return launchers.Any(l => name.Contains(l));
        }

        /// <summary>
        /// Is the process an updater / background patcher?
        /// </summary>
        public static bool IsUpdaterProcess(ProcessInfo info)
        {
            if (info == null) return false;

            var updaters = new[]
            {
                "update", "updater", "upgrade", "autoupdate", "checkupdate",
                "patch", "splash", "preload", "installer", "setup"
            };

            var name = info.Name.ToLowerInvariant();
            return updaters.Any(u => name.Contains(u));
        }

        /// <summary>
        /// Is the process a cloud synchronisation client?
        /// </summary>
        public static bool IsCloudSyncProcess(ProcessInfo info)
        {
            if (info == null) return false;

            var syncClients = new[]
            {
                "onedrive", "dropbox", "googledrive", "googledrivesync", "nextcloud",
                "owncloud", "icloud", "mega", "box", "pcloud", "backblaze", "syncthing"
            };

            var haystack = $"{info.Name} {info.Path}".ToLowerInvariant();
            return syncClients.Any(s => haystack.Contains(s));
        }

        /// <summary>
        /// Is the process a telemetry / diagnostics component?
        /// </summary>
        public static bool IsTelemetryProcess(ProcessInfo info)
        {
            if (info == null) return false;

            var telemetry = new[]
            {
                "diagtrack", "dmwappushservice", "telemetry", "ceip", "wermgr",
                "feedback", "compattelrunner", "devicecensus"
            };

            var name = info.Name.ToLowerInvariant();
            return telemetry.Any(t => name.Contains(t));
        }

        #endregion

        #region State

        /// <summary>
        /// True when the user is currently interacting with the process
        /// (foreground window or any visible window). Such processes are never auto-closed.
        /// </summary>
        public static bool IsProcessActive(int processId)
        {
            try
            {
                if (WindowsApiHelper.GetForegroundProcessId() == processId)
                    return true;

                return WindowsApiHelper.HasVisibleWindow(processId);
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// True when the process responds to window messages.
        /// </summary>
        public static bool IsProcessResponding(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    if (process.HasExited) return false;

                    // Processes without a UI always report Responding == true.
                    return process.Responding;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Whether the process is a service host (svchost.exe and friends).
        /// </summary>
        public static bool IsServiceProcess(int processId)
        {
            try
            {
                return !string.IsNullOrEmpty(GetServiceNameFromProcessId(processId));
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Service name hosted by a process (null when it is not a service).
        /// </summary>
        public static string? GetServiceNameFromProcessId(int processId)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT Name FROM Win32_Service WHERE ProcessId = {processId}"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return obj["Name"]?.ToString();
                    }
                }
            }
            catch { }

            return null;
        }

        /// <summary>
        /// All service names hosted inside a process id.
        /// </summary>
        public static List<string> GetServiceNamesFromProcessId(int processId)
        {
            var names = new List<string>();

            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT Name FROM Win32_Service WHERE ProcessId = {processId}"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var name = obj["Name"]?.ToString();
                        if (!string.IsNullOrEmpty(name))
                            names.Add(name!);
                    }
                }
            }
            catch { }

            return names;
        }

        /// <summary>
        /// Process id currently hosting a service (0 when not running).
        /// </summary>
        public static int GetProcessIdFromServiceName(string serviceName)
        {
            if (string.IsNullOrWhiteSpace(serviceName)) return 0;

            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    // ServiceController does not expose the pid; query WMI instead.
                    service.Refresh();
                }
            }
            catch { }

            try
            {
                var escaped = serviceName.Replace("'", "''");

                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT ProcessId FROM Win32_Service WHERE Name = '{escaped}'"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return Convert.ToInt32(obj["ProcessId"]);
                    }
                }
            }
            catch { }

            return 0;
        }

        #endregion

        #region Termination (guarded)

        /// <summary>
        /// Terminate a process, refusing protected targets.
        /// Returns false and sets <paramref name="errorMessage"/> when refused or when it fails.
        /// </summary>
        /// <summary>
        /// Terminate a process, refusing protected targets.
        /// Returns false and sets <paramref name="errorMessage"/> when refused or when it fails.
        ///
        /// <paramref name="expectedCreationTimeUtc"/> is the identity the caller observed when it decided
        /// to close this process. It is required, not optional.
        ///
        /// WHY IT IS REQUIRED:
        /// this method used to read the process, apply a set of name- and state-based checks, and then
        /// terminate by pid. Every one of those checks is separated from the termination by a window in
        /// which the process can exit and its pid be reassigned - the classic check-to-use race. The
        /// guards made it look safe without making it safe. Supplying the creation timestamp closes that
        /// window, because a recycled pid cannot reproduce it.
        /// </summary>
        public static bool TerminateProcessSafely(
            int processId,
            DateTime expectedCreationTimeUtc,
            out string errorMessage)
        {
            errorMessage = string.Empty;

            if (expectedCreationTimeUtc == DateTime.MinValue)
            {
                errorMessage =
                    "No process identity was supplied, so it cannot be proven that the pid still refers " +
                    "to the process that was inspected. Refusing to close it.";
                return false;
            }

            if (!WindowsApiHelper.IsSameProcessIdentity(
                    expectedCreationTimeUtc,
                    WindowsApiHelper.GetProcessCreationTimeUtc(processId) ?? DateTime.MinValue))
            {
                errorMessage =
                    $"Pid {processId} no longer belongs to the process that was inspected " +
                    "(it exited, or the pid was reassigned). Refusing to close it.";
                return false;
            }

            var info = GetProcessInfo(processId);
            if (info == null)
            {
                errorMessage = "Process no longer exists.";
                return false;
            }

            if (CriticalProcesses.IsCritical(info.Name, info.Path, info.IsService))
            {
                errorMessage = $"'{info.DisplayName}' is a protected system process and will not be closed.";
                return false;
            }

            if (info.RiskLevel == RiskLevel.Critical || info.RiskLevel == RiskLevel.High)
            {
                errorMessage = $"'{info.DisplayName}' has risk level {info.RiskLevel}; refusing to close it.";
                return false;
            }

            if (info.IsActive)
            {
                errorMessage = $"'{info.DisplayName}' is currently in use and will not be closed.";
                return false;
            }

            if (info.IsService)
            {
                errorMessage = $"'{info.DisplayName}' hosts a Windows service; stop the service instead.";
                return false;
            }

            if (!windowsProcessIsClosable(info))
            {
                errorMessage = $"'{info.DisplayName}' cannot be closed safely.";
                return false;
            }

            // Pass the verified identity down as well, so the helper re-checks it at the last moment.
            if (WindowsApiHelper.TerminateProcess(
                    processId,
                    expectedCreationTimeUtc: expectedCreationTimeUtc))
            {
                return true;
            }

            errorMessage = $"Windows refused to close '{info.DisplayName}' (access denied or protected).";
            return false;
        }

        private static bool windowsProcessIsClosable(ProcessInfo info)
        {
            // Never close a process that would take Windows' shell or session down with it.
            return !CriticalProcesses.SystemCritical.Contains(info.Name);
        }

        /// <summary>
        /// Terminate every instance of a process name.
        ///
        /// OBSOLETE AND DELIBERATELY NOT IMPLEMENTED. Closing "every instance of a name" cannot satisfy
        /// the identity requirement of the safety model: two instances of the same executable are
        /// indistinguishable to the caller, and one of them may be the window the user is working in.
        /// The method now refuses and explains, rather than behaving the old way.
        /// </summary>
        [Obsolete("Closing by process name cannot satisfy the identity safety model. " +
                  "Use TerminateProcessSafely with an identity for one specific pid.")]
        public static int TerminateProcessesByName(string processName, out List<string> errors)
        {
            errors = new List<string>
            {
                "Closing processes by name is not supported: it cannot distinguish two instances of the " +
                "same program, so it could close one the user is working in."
            };

            return 0;
        }

        /// <summary>
        /// Terminate every process whose name matches a pattern.
        ///
        /// OBSOLETE AND DELIBERATELY NOT IMPLEMENTED, for the same reason as the by-name variant:
        /// a pattern match is not an identity. It refuses and explains.
        ///
        /// A substring pattern is in fact the most dangerous form of this operation - a pattern such as
        /// "svchost" or "host" would match processes that have nothing to do with the intended target.
        /// </summary>
        [Obsolete("Pattern matching is not an identity and cannot satisfy the safety model.")]
        public static int TerminateProcessesByPattern(
            string pattern,
            bool exactMatch,
            out List<string> errors)
        {
            errors = new List<string>
            {
                "Closing processes by name pattern is not supported: a pattern cannot identify one " +
                "specific process, so the action could not be proven safe."
            };

            return 0;
        }

        #endregion

        #region Priority / affinity

        /// <summary>
        /// Raise a process to AboveNormal, but only when it is currently Normal or lower.
        /// Deliberately never uses High/RealTime - that destabilises the whole system.
        /// </summary>
        public static bool BoostProcessPriority(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    switch (process.PriorityClass)
                    {
                        case ProcessPriorityClass.Normal:
                        case ProcessPriorityClass.BelowNormal:
                        case ProcessPriorityClass.Idle:
                            return WindowsApiHelper.SetProcessPriority(processId, ProcessPriorityClass.AboveNormal);

                        default:
                            // Already elevated (or above) - leave it alone.
                            return false;
                    }
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Restore a process to Normal priority.
        /// </summary>
        public static bool ResetProcessPriority(int processId)
        {
            return WindowsApiHelper.SetProcessPriority(processId, ProcessPriorityClass.Normal);
        }

        /// <summary>
        /// Reset a process to all cores.
        /// </summary>
        public static bool ResetProcessAffinity(int processId)
        {
            return WindowsApiHelper.ResetProcessAffinityToAllCores(processId);
        }

        #endregion

        #region Properties

        /// <summary>
        /// True when the process is running as 64-bit.
        /// </summary>
        public static bool Is64BitProcess(int processId)
        {
            try
            {
                // On a 64-bit OS, Environment.Is64BitOperatingSystem tells us the OS bitness;
                // Wow64 processes are reported through the module list.
                using (var process = Process.GetProcessById(processId))
                {
                    if (!Environment.Is64BitOperatingSystem)
                        return false;

                    // A Wow64 process has a main module under SysWOW64 in many cases, but the
                    // reliable check needs IsWow64Process via P/Invoke, which we avoid here to
                    // keep the utility dependency-free. Report best effort.
                    var moduleName = process.MainModule?.FileName ?? string.Empty;
                    return !moduleName.Contains("SysWOW64", StringComparison.OrdinalIgnoreCase);
                }
            }
            catch
            {
                return Environment.Is64BitProcess;
            }
        }

        /// <summary>
        /// Number of threads owned by a process (0 when inaccessible).
        /// </summary>
        public static int GetProcessThreadCount(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.Threads.Count;
                }
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Number of handles owned by a process (0 when inaccessible).
        /// </summary>
        public static int GetProcessHandleCount(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.HandleCount;
                }
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Process start time (null when inaccessible).
        /// </summary>
        public static DateTime? GetProcessStartTime(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.StartTime;
                }
            }
            catch
            {
                return null;
            }
        }

        #endregion

        #region Digital signature

        /// <summary>
        /// Classify the Authenticode signature of a file.
        ///
        /// NOTE: "Unsigned" is NOT the same as "malware". Many legitimate tools ship unsigned.
        /// The UI must present this as a hint, never as a verdict.
        /// </summary>
        public static SignatureStatus GetSignatureStatus(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
                return SignatureStatus.Unsigned;

            try
            {
                var certificate = X509Certificate.CreateFromSignedFile(filePath);
                if (certificate == null)
                    return SignatureStatus.Unsigned;

                var subject = certificate.Subject ?? string.Empty;
                var issuer = certificate.Issuer ?? string.Empty;
                var haystack = $"{subject} {issuer}";

                if (haystack.IndexOf("Microsoft", StringComparison.OrdinalIgnoreCase) >= 0 ||
                    haystack.IndexOf("Windows", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return SignatureStatus.MicrosoftSigned;
                }

                var knownVendors = new[]
                {
                    "Intel", "AMD", "Advanced Micro Devices", "NVIDIA", "Realtek", "Conexant",
                    "Dolby", "Creative", "Logitech", "Razer", "Corsair", "SteelSeries",
                    "Adobe", "Autodesk", "Google", "Mozilla", "Valve", "Electronic Arts",
                    "Ubisoft", "Activision", "Blizzard", "Discord", "Spotify", "Slack",
                    "Zoom", "Dropbox", "Samsung", "Synaptics", "Synaptics Incorporated"
                };

                foreach (var vendor in knownVendors)
                {
                    if (haystack.IndexOf(vendor, StringComparison.OrdinalIgnoreCase) >= 0)
                        return SignatureStatus.KnownVendor;
                }

                return SignatureStatus.KnownVendor;
            }
            catch (System.Security.Cryptography.CryptographicException)
            {
                // Signed file with a certificate we cannot parse, or an unsigned file.
                return SignatureStatus.Unsigned;
            }
            catch
            {
                return SignatureStatus.InvalidSignature;
            }
        }

        #endregion

        #region Sorting / filtering helpers

        /// <summary>
        /// Processes that may be offered for optimisation (safe candidates only).
        /// </summary>
        public static List<ProcessInfo> GetOptimizableProcesses(IEnumerable<ProcessInfo> processes)
        {
            return processes
                .Where(p => !p.IsBlacklisted)
                .Where(p => !p.IsUserWhitelisted)
                .Where(p => !p.IsActive)
                .Where(p => !p.HasVisibleWindow)
                .Where(p => !p.IsService)
                .Where(p => !CriticalProcesses.IsCritical(p.Name))
                .Where(p => p.RiskLevel == RiskLevel.Low || p.RiskLevel == RiskLevel.Medium)
                .Where(p => p.WorkingSet >= 10 * 1024 * 1024)
                .ToList();
        }

        /// <summary>
        /// Idle background applications - the primary optimisation target.
        /// </summary>
        public static List<ProcessInfo> GetBackgroundProcesses(IEnumerable<ProcessInfo> processes)
        {
            return processes
                .Where(p => p.Category == ProcessCategory.BackgroundApplication)
                .Where(p => !p.IsActive && !p.HasVisibleWindow)
                .ToList();
        }

        /// <summary>
        /// Sort by working set.
        /// </summary>
        public static List<ProcessInfo> SortByRamUsage(IEnumerable<ProcessInfo> processes, bool descending = true)
        {
            return descending
                ? processes.OrderByDescending(p => p.WorkingSet).ToList()
                : processes.OrderBy(p => p.WorkingSet).ToList();
        }

        /// <summary>
        /// Sort by CPU usage.
        /// </summary>
        public static List<ProcessInfo> SortByCpuUsage(IEnumerable<ProcessInfo> processes, bool descending = true)
        {
            return descending
                ? processes.OrderByDescending(p => p.CpuUsage).ToList()
                : processes.OrderBy(p => p.CpuUsage).ToList();
        }

        /// <summary>
        /// Sort by display name.
        /// </summary>
        public static List<ProcessInfo> SortByName(IEnumerable<ProcessInfo> processes, bool descending = false)
        {
            return descending
                ? processes.OrderByDescending(p => p.DisplayName, StringComparer.OrdinalIgnoreCase).ToList()
                : processes.OrderBy(p => p.DisplayName, StringComparer.OrdinalIgnoreCase).ToList();
        }

        /// <summary>
        /// Filter by category.
        /// </summary>
        public static List<ProcessInfo> GetProcessesByCategory(IEnumerable<ProcessInfo> processes, ProcessCategory category)
        {
            return processes.Where(p => p.Category == category).ToList();
        }

        /// <summary>
        /// Filter by risk level.
        /// </summary>
        public static List<ProcessInfo> GetProcessesByRiskLevel(IEnumerable<ProcessInfo> processes, RiskLevel riskLevel)
        {
            return processes.Where(p => p.RiskLevel == riskLevel).ToList();
        }

        #endregion
    }
}
