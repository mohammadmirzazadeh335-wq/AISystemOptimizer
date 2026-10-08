using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Low level Windows API helper.
    ///
    /// Everything in here is a thin, defensive wrapper around a documented Windows API.
    /// No method in this class performs a destructive operation on its own - the Safety
    /// Layer (SafetyValidator) decides whether a caller is allowed to use them.
    /// </summary>
    public static class WindowsApiHelper
    {
        #region Native constants

        private const int PROCESS_QUERY_INFORMATION = 0x0400;
        private const int PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
        private const int PROCESS_TERMINATE = 0x0001;
        private const int PROCESS_SET_INFORMATION = 0x0200;
        private const int PROCESS_VM_READ = 0x0010;

        private const uint TOKEN_QUERY = 0x0008;
        private const uint SC_MANAGER_ALL_ACCESS = 0x000F003F;
        private const uint SERVICE_ALL_ACCESS = 0x000F01FF;
        private const uint SERVICE_QUERY_STATUS = 0x00000004;
        private const uint SERVICE_CONTROL_STOP = 0x00000001;
        private const uint SERVICE_NO_CHANGE = 0xFFFFFFFF;
        private const uint SERVICE_AUTO_START = 0x00000002;
        private const uint SERVICE_DEMAND_START = 0x00000003;
        private const uint SERVICE_DISABLED = 0x00000004;

        private const int STATUS_SUCCESS = 0;

        #endregion

        #region Native interop

        [StructLayout(LayoutKind.Sequential)]
        private struct MEMORYSTATUSEX
        {
            public uint dwLength;
            public uint dwMemoryLoad;
            public ulong ullTotalPhys;
            public ulong ullAvailPhys;
            public ulong ullTotalPageFile;
            public ulong ullAvailPageFile;
            public ulong ullTotalVirtual;
            public ulong ullAvailVirtual;
            public ulong ullAvailExtendedVirtual;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct LASTINPUTINFO
        {
            public uint cbSize;
            public uint dwTime;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SERVICE_STATUS
        {
            public uint dwServiceType;
            public uint dwCurrentState;
            public uint dwControlsAccepted;
            public uint dwWin32ExitCode;
            public uint dwServiceSpecificExitCode;
            public uint dwCheckPoint;
            public uint dwWaitHint;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct RESTOREPOINTINFO
        {
            public int dwEventType;
            public int dwRestorePtType;
            public long llSequenceNumber;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
            public string szDescription;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct STATEMGRSTATUS
        {
            public int nStatus;
            public long llSequenceNumber;
        }

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenProcess(int dwDesiredAccess, bool bInheritHandle, int dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool TerminateProcess(IntPtr hProcess, uint uExitCode);

        /// <summary>
        /// GetProcessTimes. Used as the authoritative PID-reuse discriminator:
        /// the process creation timestamp can never be reused by a recycled PID.
        /// </summary>
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetProcessTimes(
            IntPtr hProcess,
            out long lpCreationTime,
            out long lpExitTime,
            out long lpKernelTime,
            out long lpUserTime);

        /// <summary>
        /// QueryFullProcessImageNameW: the only reliable way to read the image path of a
        /// 64-bit process from anything other than an equally-wide process without elevation.
        /// </summary>
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool QueryFullProcessImageNameW(
            IntPtr hProcess,
            int dwFlags,
            StringBuilder lpExeName,
            ref int lpdwSize);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ProcessIdToSessionId(uint dwProcessId, out uint pSessionId);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern int GetSystemMetrics(int nIndex);

        private const int SM_CXSCREEN = 0;
        private const int SM_CYSCREEN = 1;

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct WINDOWPLACEMENT
        {
            public int length;
            public int flags;
            public int showCmd;
            public POINT ptMinPosition;
            public POINT ptMaxPosition;
            public RECT rcNormalPosition;
        }

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern int GetWindowTextLength(IntPtr hWnd);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetProcessDPIAware();

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetProcessDpiAwarenessContext(IntPtr value);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenThread(uint dwDesiredAccess, bool bInheritHandle, uint dwThreadId);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint SuspendThread(IntPtr hThread);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint ResumeThread(IntPtr hThread);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr OpenSCManager(string? lpMachineName, string? lpDatabaseName, uint dwDesiredAccess);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool OpenService(IntPtr hSCManager, string lpServiceName, uint dwDesiredAccess, out IntPtr phService);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseServiceHandle(IntPtr hSCObject);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ChangeServiceConfig(
            IntPtr hService, uint nServiceType, uint nStartType, uint nErrorControl,
            string? lpBinaryPathName, string? lpLoadOrderGroup, IntPtr lpdwTagId,
            string? lpDependencies, string? lpServiceStartName, string? lpPassword, string? lpDisplayName);

        [DllImport("srclient.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern int SRSetRestorePointW(ref RESTOREPOINTINFO pRestorePtSpec, out STATEMGRSTATUS pSMgrStatus);

        #endregion

        #region Privileges / identity

        /// <summary>
        /// True when the current process is elevated (Administrator).
        /// The application never tries to bypass UAC - it simply reports this.
        /// </summary>
        public static bool IsAdministrator()
        {
            try
            {
                using (var identity = WindowsIdentity.GetCurrent())
                {
                    var principal = new WindowsPrincipal(identity);
                    return principal.IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Get the session id a process runs in (0 = services / system session).
        /// </summary>
        public static int GetProcessSessionId(int processId)
        {
            try
            {
                if (ProcessIdToSessionId((uint)processId, out var sessionId))
                    return (int)sessionId;
            }
            catch { }
            return -1;
        }

        #endregion

        #region Physical memory

        /// <summary>
        /// Total installed physical memory in bytes (GlobalMemoryStatusEx).
        /// Returns 0 when the API call fails, so callers can distinguish "unknown" from "empty".
        /// </summary>
        public static long GetTotalPhysicalMemory()
        {
            var status = GetMemoryStatus();
            return status.HasValue ? (long)status.Value.ullTotalPhys : 0;
        }

        /// <summary>
        /// Currently available (free + standby-reclaimable) physical memory in bytes.
        /// </summary>
        public static long GetAvailablePhysicalMemory()
        {
            var status = GetMemoryStatus();
            return status.HasValue ? (long)status.Value.ullAvailPhys : 0;
        }

        /// <summary>
        /// Memory load reported by Windows (percentage, 0-100).
        /// </summary>
        public static float GetMemoryLoadPercentage()
        {
            var status = GetMemoryStatus();
            return status.HasValue ? status.Value.dwMemoryLoad : 0f;
        }

        /// <summary>
        /// Page file totals in bytes (total, available).
        /// </summary>
        public static (long Total, long Available) GetPageFileBytes()
        {
            var status = GetMemoryStatus();
            if (!status.HasValue)
                return (0, 0);

            return ((long)status.Value.ullTotalPageFile, (long)status.Value.ullAvailPageFile);
        }

        private static MEMORYSTATUSEX? GetMemoryStatus()
        {
            try
            {
                var status = new MEMORYSTATUSEX();
                status.dwLength = (uint)Marshal.SizeOf<MEMORYSTATUSEX>();
                if (GlobalMemoryStatusEx(ref status))
                    return status;
            }
            catch { }
            return null;
        }

        #endregion

        #region Process operations

        /// <summary>
        /// Get a live <see cref="Process"/> by id, or null when it no longer exists / is inaccessible.
        /// </summary>
        public static Process? GetProcessById(int processId)
        {
            try
            {
                return Process.GetProcessById(processId);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// All running processes. Processes that terminate while enumerating are skipped.
        /// </summary>
        public static Process[] GetAllProcesses()
        {
            try
            {
                return Process.GetProcesses();
            }
            catch
            {
                return Array.Empty<Process>();
            }
        }

        /// <summary>
        /// Check whether a process id is still alive.
        /// </summary>
        public static bool IsProcessRunning(int processId)
        {
            if (processId <= 0) return false;

            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return !process.HasExited;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Check whether at least one process with the given name (without extension) is running.
        /// </summary>
        public static bool IsProcessRunning(string processName)
        {
            if (string.IsNullOrWhiteSpace(processName)) return false;

            try
            {
                var name = Path.GetFileNameWithoutExtension(processName);
                return Process.GetProcessesByName(name).Length > 0;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Number of running instances of a process name.
        /// </summary>
        public static int GetProcessInstanceCount(string processName)
        {
            try
            {
                var name = Path.GetFileNameWithoutExtension(processName);
                return Process.GetProcessesByName(name).Length;
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Terminate a process by pid. Returns true only if the process was actually gone afterwards.
        /// Callers must run this through the Safety Layer first.
        ///
        /// When <paramref name="expectedCreationTimeUtc"/> is supplied the process identity is verified
        /// against it first. This closes the TOCTOU / PID-reuse window: if the original process exited
        /// and Windows handed the same pid to a different process, the mismatch is detected and nothing
        /// is terminated. A null expected value means "no identity was recorded" and the caller is
        /// expected to have performed its own verification.
        /// </summary>
        public static bool TerminateProcess(
            int processId,
            int exitCode = 0,
            int timeoutMs = 5000,
            DateTime? expectedCreationTimeUtc = null)
        {
            if (processId <= 0) return false;

            if (expectedCreationTimeUtc.HasValue &&
                !VerifyProcessIdentity(processId, expectedCreationTimeUtc.Value, null, out _))
            {
                return false;
            }

            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    if (process.HasExited)
                        return true;

                    process.Kill();
                    return process.WaitForExit(timeoutMs);
                }
            }
            catch (ArgumentException)
            {
                // Process already gone.
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Creation timestamp of a process, read with GetProcessTimes.
        /// This value is unique-enough to act as the identity of a running process: a recycled pid
        /// always has a different creation time. Returns null when the process is gone or protected.
        /// </summary>
        public static DateTime? GetProcessCreationTimeUtc(int processId)
        {
            if (processId <= 0) return null;

            IntPtr handle = IntPtr.Zero;

            try
            {
                handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, processId);
                if (handle == IntPtr.Zero)
                    return null;

                if (!GetProcessTimes(handle, out var creation, out _, out _, out _))
                    return null;

                if (creation <= 0)
                    return null;

                return DateTime.FromFileTimeUtc(creation);
            }
            catch
            {
                return null;
            }
            finally
            {
                if (handle != IntPtr.Zero)
                    CloseHandle(handle);
            }
        }

        /// <summary>
        /// Executable image path of a process. Prefers QueryFullProcessImageNameW (works for
        /// protected and cross-bitness processes), then falls back to <see cref="Process.MainModule"/>.
        /// Returns an empty string when the path cannot be read (which callers must treat as "unknown",
        /// not as "safe").
        /// </summary>
        public static string GetProcessExecutablePath(int processId)
        {
            if (processId <= 0) return string.Empty;

            IntPtr handle = IntPtr.Zero;

            try
            {
                handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, processId);
                if (handle != IntPtr.Zero)
                {
                    var capacity = 1024;
                    var buffer = new StringBuilder(capacity);
                    if (QueryFullProcessImageNameW(handle, 0, buffer, ref capacity))
                    {
                        var value = buffer.ToString();
                        if (!string.IsNullOrWhiteSpace(value))
                            return value;
                    }
                }
            }
            catch { }
            finally
            {
                if (handle != IntPtr.Zero)
                    CloseHandle(handle);
            }

            // Fallback: accessible managed property. Not available for protected processes.
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.MainModule?.FileName ?? string.Empty;
                }
            }
            catch
            {
                return string.Empty;
            }
        }

        /// <summary>
        /// Verify that the process currently owning <paramref name="processId"/> is still the same
        /// process that was observed when the action was planned.
        ///
        /// Mismatch on creation time is treated as a recycled pid and blocks the caller.
        /// A name mismatch also blocks. A path mismatch blocks only when both the expected and the
        /// observed path are known - an unreadable path is never a reason to allow the action, but it
        /// is also not evidence of tampering, so the caller decides via <paramref name="reason"/>.
        /// </summary>
        public static bool VerifyProcessIdentity(
            int processId,
            DateTime expectedCreationTimeUtc,
            string? expectedName,
            out string reason)
        {
            reason = string.Empty;

            if (processId <= 0)
            {
                reason = "Invalid pid.";
                return false;
            }

            var actualCreation = GetProcessCreationTimeUtc(processId);
            if (!actualCreation.HasValue)
            {
                reason = $"Process {processId} is no longer running (identity could not be read), so it was not touched.";
                return false;
            }

            if (!IsSameProcessIdentity(expectedCreationTimeUtc, actualCreation.Value))
            {
                reason =
                    $"Pid {processId} now belongs to a different process " +
                    $"(expected start {expectedCreationTimeUtc:O}, found {actualCreation.Value:O}). " +
                    "The original process exited and its pid was reused, so the action was rejected.";
                return false;
            }

            if (!string.IsNullOrWhiteSpace(expectedName))
            {
                try
                {
                    using (var process = Process.GetProcessById(processId))
                    {
                        var actualName = process.ProcessName;
                        if (!string.Equals(
                                NormalizeProcessName(actualName),
                                NormalizeProcessName(expectedName!),
                                StringComparison.OrdinalIgnoreCase))
                        {
                            reason =
                                $"Process name changed under pid {processId} " +
                                $"(expected '{expectedName}', found '{actualName}'). Action rejected.";
                            return false;
                        }
                    }
                }
                catch
                {
                    reason = $"Process {processId} disappeared while its identity was being verified.";
                    return false;
                }
            }

            return true;
        }

        /// <summary>
        /// The PID-reuse discriminator, as a pure function with no Windows dependency so that it can
        /// be unit tested on any platform.
        ///
        /// Two creation timestamps identify the same process incarnation when they are within
        /// <paramref name="toleranceSeconds"/> of each other. The tolerance absorbs the rounding that
        /// can occur when a timestamp is serialised into a history file and read back; it is far
        /// smaller than the interval at which Windows recycles a pid, so it cannot mask a real reuse.
        ///
        /// An unset (<see cref="DateTime.MinValue"/>) expected value is never a match: "no identity
        /// recorded" must not be silently treated as "identity confirmed".
        /// </summary>
        public static bool IsSameProcessIdentity(
            DateTime expectedCreationTimeUtc,
            DateTime actualCreationTimeUtc,
            double toleranceSeconds = 1.0)
        {
            if (expectedCreationTimeUtc == DateTime.MinValue ||
                actualCreationTimeUtc == DateTime.MinValue)
            {
                return false;
            }

            var difference = Math.Abs((actualCreationTimeUtc - expectedCreationTimeUtc).TotalSeconds);

            return difference <= toleranceSeconds;
        }

        /// <summary>
        /// Strip a directory and the .exe extension so "svchost", "svchost.exe" and
        /// "C:\\Windows\\System32\\svchost.exe" all compare equal.
        /// </summary>
        public static string NormalizeProcessName(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            var name = value!.Trim().Trim('"');

            var separator = name.LastIndexOfAny(new[] { '\\', '/' });
            if (separator >= 0)
                name = name[(separator + 1)..];

            if (name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                name = name[..^4];

            return name;
        }

        /// <summary>
        /// Terminate every instance of a process name.
        ///
        /// OBSOLETE AND DELIBERATELY UNUSED: killing by name cannot distinguish two instances of the
        /// same executable and therefore cannot satisfy the identity requirement of the safety model.
        /// It is retained only so that existing external callers fail to compile rather than silently
        /// regress; the production pipeline must use <see cref="TerminateProcess(int,int,int,System.DateTime?)"/>
        /// with a verified identity.
        /// </summary>
        [Obsolete("Killing by process name cannot satisfy the pid+identity safety model. Use TerminateProcess with a verified identity instead.")]
        public static int TerminateProcessesByName(string processName, int timeoutMs = 5000)
        {
            if (string.IsNullOrWhiteSpace(processName))
                return 0;

            int terminated = 0;

            try
            {
                var name = NormalizeProcessName(processName);
                if (name.Length == 0)
                    return 0;

                foreach (var process in Process.GetProcessesByName(name))
                {
                    try
                    {
                        using (process)
                        {
                            if (process.HasExited)
                                continue;

                            var creationTime = GetProcessCreationTimeUtc(process.Id);
                            if (!creationTime.HasValue)
                                continue;

                            if (TerminateProcess(process.Id, 0, timeoutMs, creationTime))
                                terminated++;
                        }
                    }
                    catch { }
                }
            }
            catch { }

            return terminated;
        }

        /// <summary>
        /// Current CPU usage (percent of one core, normalized to all cores) for a process.
        /// Uses delta of TotalProcessorTime, which is the only reliable method without ETW.
        /// </summary>
        public static float GetProcessCpuUsage(int processId, int sampleMilliseconds = 250)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    var startCpu = process.TotalProcessorTime;
                    var startTime = DateTime.UtcNow;

                    System.Threading.Thread.Sleep(sampleMilliseconds);

                    process.Refresh();
                    var endCpu = process.TotalProcessorTime;
                    var endTime = DateTime.UtcNow;

                    var cpuMs = (endCpu - startCpu).TotalMilliseconds;
                    var elapsedMs = (endTime - startTime).TotalMilliseconds;

                    if (elapsedMs <= 0) return 0f;

                    var cores = Environment.ProcessorCount > 0 ? Environment.ProcessorCount : 1;
                    var usage = cpuMs / (elapsedMs * cores) * 100.0;

                    return (float)Math.Max(0, Math.Min(100, usage));
                }
            }
            catch
            {
                return 0f;
            }
        }

        /// <summary>
        /// Get the approximate working set of a process in bytes (0 when inaccessible).
        /// </summary>
        public static long GetProcessWorkingSet(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.WorkingSet64;
                }
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Get the command line of a process via WMI (falls back to empty string).
        /// </summary>
        public static string GetProcessCommandLine(int processId)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT CommandLine FROM Win32_Process WHERE ProcessId = {processId}"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var commandLine = obj["CommandLine"]?.ToString();
                        if (!string.IsNullOrEmpty(commandLine))
                            return commandLine!;
                    }
                }
            }
            catch { }

            return string.Empty;
        }

        /// <summary>
        /// Get the parent process id via WMI (0 when unavailable).
        /// </summary>
        public static int GetParentProcessId(int processId)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT ParentProcessId FROM Win32_Process WHERE ProcessId = {processId}"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return Convert.ToInt32(obj["ParentProcessId"]);
                    }
                }
            }
            catch { }

            return 0;
        }

        /// <summary>
        /// Get the owning user (DOMAIN\user) of a process via WMI.
        /// </summary>
        public static string GetProcessOwner(int processId)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    $"SELECT * FROM Win32_Process WHERE ProcessId = {processId}"))
                {
                    foreach (var baseObject in searcher.Get())
                    {
                        if (baseObject is not System.Management.ManagementObject obj)
                            continue;

                        var outParams = obj.InvokeMethod("GetOwner", null, null);
                        if (outParams != null)
                        {
                            var user = outParams["User"]?.ToString() ?? string.Empty;
                            var domain = outParams["Domain"]?.ToString() ?? string.Empty;
                            return string.IsNullOrEmpty(domain) ? user : $"{domain}\\{user}";
                        }
                    }
                }
            }
            catch { }

            return string.Empty;
        }

        /// <summary>
        /// Suspend every thread of a process (used by the "pause" feature, never automatically).
        /// </summary>
        public static bool SuspendProcess(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    foreach (ProcessThread thread in process.Threads)
                    {
                        var handle = OpenThread((uint)ThreadAccess.SUSPEND_RESUME, false, (uint)thread.Id);
                        if (handle == IntPtr.Zero) continue;

                        try
                        {
                            SuspendThread(handle);
                        }
                        finally
                        {
                            CloseHandle(handle);
                        }
                    }
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Resume every thread of a process.
        /// </summary>
        public static bool ResumeProcess(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    foreach (ProcessThread thread in process.Threads)
                    {
                        var handle = OpenThread((uint)ThreadAccess.SUSPEND_RESUME, false, (uint)thread.Id);
                        if (handle == IntPtr.Zero) continue;

                        try
                        {
                            ResumeThread(handle);
                        }
                        finally
                        {
                            CloseHandle(handle);
                        }
                    }
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Change the priority class of a process.
        /// </summary>
        public static bool SetProcessPriority(int processId, ProcessPriorityClass priority)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    process.PriorityClass = priority;
                    return process.PriorityClass == priority;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Read the current priority class of a process (null when inaccessible).
        /// </summary>
        public static ProcessPriorityClass? GetProcessPriority(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.PriorityClass;
                }
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Build a CPU affinity mask covering every logical processor.
        /// </summary>
        public static long GetAllCoresAffinityMask()
        {
            var cores = Environment.ProcessorCount;
            if (cores >= 64) return unchecked((long)0xFFFFFFFFFFFFFFFF);
            return (1L << cores) - 1;
        }

        /// <summary>
        /// Set the affinity mask of a process.
        /// </summary>
        public static bool SetProcessAffinityMask(int processId, long affinityMask)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    process.ProcessorAffinity = new IntPtr(affinityMask);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Reset a process to use all logical processors.
        /// </summary>
        public static bool ResetProcessAffinityToAllCores(int processId)
        {
            return SetProcessAffinityMask(processId, GetAllCoresAffinityMask());
        }

        /// <summary>
        /// Read the current affinity mask of a process (0 when inaccessible).
        /// </summary>
        public static long GetProcessAffinityMask(int processId)
        {
            try
            {
                using (var process = Process.GetProcessById(processId))
                {
                    return process.ProcessorAffinity.ToInt64();
                }
            }
            catch
            {
                return 0;
            }
        }

        #endregion

        #region Window operations

        /// <summary>
        /// Foreground window handle (IntPtr.Zero when none).
        /// </summary>
        public static IntPtr GetForegroundWindowHandle()
        {
            try
            {
                return GetForegroundWindow();
            }
            catch
            {
                return IntPtr.Zero;
            }
        }

        /// <summary>
        /// Process id that currently owns the foreground window (0 when none).
        /// </summary>
        public static int GetForegroundProcessId()
        {
            try
            {
                var hwnd = GetForegroundWindow();
                if (hwnd == IntPtr.Zero) return 0;

                GetWindowThreadProcessId(hwnd, out var pid);
                return (int)pid;
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// True when the process owns at least one visible top-level window.
        /// A process with a visible window is considered "in use" and is never closed automatically.
        ///
        /// The check deliberately does <b>not</b> require the window to have a title. An earlier version
        /// skipped untitled windows, which meant an exclusive-fullscreen game (whose window is often
        /// created before the title is set, or with an empty caption) was reported as having no window
        /// at all - and was therefore treated as safe to close. Treating an untitled visible window as
        /// "in use" fails in the safe direction: at worst the optimiser declines to close something it
        /// could have closed.
        /// </summary>
        public static bool HasVisibleWindow(int processId)
        {
            try
            {
                bool found = false;

                EnumWindows((hWnd, _) =>
                {
                    GetWindowThreadProcessId(hWnd, out var pid);
                    if (pid != (uint)processId) return true;
                    if (!IsWindowVisible(hWnd)) return true;

                    found = true;
                    return false; // stop enumeration
                }, IntPtr.Zero);

                return found;
            }
            catch
            {
                // Fail safe: if the window list cannot be read we must not conclude "no window".
                return true;
            }
        }

        /// <summary>
        /// True when the process currently owns the foreground window (the window receiving input).
        /// This is the strongest "the user is using it right now" signal.
        /// </summary>
        public static bool IsForegroundProcess(int processId)
        {
            if (processId <= 0) return false;

            try
            {
                return GetForegroundProcessId() == processId;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Fullscreen state of the foreground window.
        /// Returns false when unknown - an unknown state is never reported as fullscreen, because the
        /// caller uses this only to raise the protection level, never to lower it.
        /// </summary>
        public static bool IsForegroundWindowFullscreen()
        {
            try
            {
                var hwnd = GetForegroundWindow();
                if (hwnd == IntPtr.Zero)
                    return false;

                var placement = new WINDOWPLACEMENT
                {
                    length = Marshal.SizeOf<WINDOWPLACEMENT>()
                };

                if (!GetWindowPlacement(hwnd, ref placement))
                    return false;

                // SW_SHOWMINIMIZED == 2
                if (placement.showCmd == 2)
                    return false;

                if (!GetClientRect(hwnd, out var clientRect))
                    return false;

                GetWindowRect(hwnd, out var windowRect);

                var width = clientRect.Right - clientRect.Left;
                var height = clientRect.Bottom - clientRect.Top;

                if (width <= 0 || height <= 0)
                    return false;

                var screenWidth = GetSystemMetrics(SM_CXSCREEN);
                var screenHeight = GetSystemMetrics(SM_CYSCREEN);

                if (screenWidth <= 0 || screenHeight <= 0)
                    return false;

                // Borderless / exclusive fullscreen covers the whole primary display.
                return width >= screenWidth - 2 && height >= screenHeight - 2 &&
                       windowRect.Left <= 0 && windowRect.Top <= 0;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// All visible windows owned by a process.
        /// </summary>
        public static List<IntPtr> GetProcessWindows(int processId)
        {
            var windows = new List<IntPtr>();

            try
            {
                EnumWindows((hWnd, _) =>
                {
                    GetWindowThreadProcessId(hWnd, out var pid);
                    if (pid == (uint)processId && IsWindowVisible(hWnd))
                        windows.Add(hWnd);

                    return true;
                }, IntPtr.Zero);
            }
            catch { }

            return windows;
        }

        /// <summary>
        /// Title of a window (empty when unknown).
        /// </summary>
        public static string GetWindowTitle(IntPtr hWnd)
        {
            try
            {
                var length = GetWindowTextLength(hWnd);
                if (length <= 0) return string.Empty;

                var builder = new StringBuilder(length + 1);
                GetWindowText(hWnd, builder, builder.Capacity);
                return builder.ToString();
            }
            catch
            {
                return string.Empty;
            }
        }

        /// <summary>
        /// How long since the last keyboard/mouse input.
        /// </summary>
        public static TimeSpan GetIdleTime()
        {
            try
            {
                var info = new LASTINPUTINFO
                {
                    cbSize = (uint)Marshal.SizeOf<LASTINPUTINFO>()
                };

                if (GetLastInputInfo(ref info))
                {
                    var elapsed = unchecked((uint)Environment.TickCount - info.dwTime);
                    return TimeSpan.FromMilliseconds(elapsed);
                }
            }
            catch { }

            return TimeSpan.Zero;
        }

        /// <summary>
        /// True when the user has been idle longer than <paramref name="thresholdSeconds"/>.
        /// </summary>
        public static bool IsSystemIdle(int thresholdSeconds = 60)
        {
            return GetIdleTime().TotalSeconds >= thresholdSeconds;
        }

        #endregion

        #region Service operations

        /// <summary>
        /// Change the start type of a service. Requires elevation.
        /// </summary>
        public static bool SetServiceStartType(string serviceName, System.ServiceProcess.ServiceStartMode startType)
        {
            if (string.IsNullOrWhiteSpace(serviceName))
                return false;

            uint nativeStartType = startType switch
            {
                System.ServiceProcess.ServiceStartMode.Automatic => SERVICE_AUTO_START,
                System.ServiceProcess.ServiceStartMode.Manual => SERVICE_DEMAND_START,
                System.ServiceProcess.ServiceStartMode.Disabled => SERVICE_DISABLED,
                _ => SERVICE_NO_CHANGE
            };

            if (nativeStartType == SERVICE_NO_CHANGE)
                return false;

            var scManager = IntPtr.Zero;
            var serviceHandle = IntPtr.Zero;

            try
            {
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                    return false;

                if (!OpenService(scManager, serviceName, SERVICE_ALL_ACCESS, out serviceHandle))
                    return false;

                var result = ChangeServiceConfig(
                    serviceHandle,
                    SERVICE_NO_CHANGE,   // service type
                    nativeStartType,     // start type
                    SERVICE_NO_CHANGE,   // error control
                    null, null, IntPtr.Zero, null, null, null, null);

                return result;
            }
            catch
            {
                return false;
            }
            finally
            {
                if (serviceHandle != IntPtr.Zero) CloseServiceHandle(serviceHandle);
                if (scManager != IntPtr.Zero) CloseServiceHandle(scManager);
            }
        }

        /// <summary>
        /// Read the configured start type of a service.
        /// </summary>
        public static System.ServiceProcess.ServiceStartMode GetServiceStartType(string serviceName)
        {
            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    return service.StartType;
                }
            }
            catch
            {
                return System.ServiceProcess.ServiceStartMode.Manual;
            }
        }

        /// <summary>
        /// Start a service and wait for it to reach the Running state.
        /// </summary>
        public static bool StartService(string serviceName, int timeoutSeconds = 30)
        {
            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    if (service.Status == System.ServiceProcess.ServiceControllerStatus.Running)
                        return true;

                    if (service.Status == System.ServiceProcess.ServiceControllerStatus.StartPending)
                        return true;

                    service.Start();
                    service.WaitForStatus(System.ServiceProcess.ServiceControllerStatus.Running,
                        TimeSpan.FromSeconds(timeoutSeconds));

                    return service.Status == System.ServiceProcess.ServiceControllerStatus.Running;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Stop a service and wait for it to reach the Stopped state.
        /// </summary>
        public static bool StopService(string serviceName, int timeoutSeconds = 30)
        {
            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    if (service.Status == System.ServiceProcess.ServiceControllerStatus.Stopped)
                        return true;

                    if (!service.CanStop)
                        return false;

                    service.Stop();
                    service.WaitForStatus(System.ServiceProcess.ServiceControllerStatus.Stopped,
                        TimeSpan.FromSeconds(timeoutSeconds));

                    return service.Status == System.ServiceProcess.ServiceControllerStatus.Stopped;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Names of the services that depend on <paramref name="serviceName"/>.
        ///
        /// Returns null when the dependency graph could not be read. Null means "unknown" and callers
        /// must treat it as "assume there are dependents" - failing closed is the only acceptable
        /// behaviour when the consequence of being wrong is breaking a service the system needs.
        /// </summary>
        public static IReadOnlyList<string>? GetDependentServiceNames(string serviceName)
        {
            if (string.IsNullOrWhiteSpace(serviceName))
                return Array.Empty<string>();

            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    var dependents = service.DependentServices;

                    if (dependents == null || dependents.Length == 0)
                        return Array.Empty<string>();

                    var names = new List<string>(dependents.Length);

                    foreach (var dependent in dependents)
                    {
                        try
                        {
                            names.Add(dependent.ServiceName);
                        }
                        finally
                        {
                            dependent.Dispose();
                        }
                    }

                    return names;
                }
            }
            catch (InvalidOperationException)
            {
                // The service does not exist or is not registered on this machine.
                return Array.Empty<string>();
            }
            catch (System.ComponentModel.Win32Exception)
            {
                // Access denied / the service database could not be queried - unknown, not "none".
                return null;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// True when a service is currently running.
        /// </summary>
        public static bool IsServiceRunning(string serviceName)
        {
            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    return service.Status == System.ServiceProcess.ServiceControllerStatus.Running;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// True when a service exists on this machine.
        /// </summary>
        public static bool ServiceExists(string serviceName)
        {
            try
            {
                using (var service = new System.ServiceProcess.ServiceController(serviceName))
                {
                    _ = service.Status;
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Disable a service (sets start type to Disabled). The caller must stop it separately.
        /// </summary>
        public static bool DisableService(string serviceName)
        {
            return SetServiceStartType(serviceName, System.ServiceProcess.ServiceStartMode.Disabled);
        }

        /// <summary>
        /// Re-enable a service with automatic start.
        /// </summary>
        public static bool EnableService(string serviceName, bool autoStart = true)
        {
            return SetServiceStartType(serviceName,
                autoStart ? System.ServiceProcess.ServiceStartMode.Automatic
                          : System.ServiceProcess.ServiceStartMode.Manual);
        }

        /// <summary>
        /// Number of running services.
        /// </summary>
        public static int GetRunningServiceCount()
        {
            try
            {
                return System.ServiceProcess.ServiceController.GetServices()
                    .Count(s => s.Status == System.ServiceProcess.ServiceControllerStatus.Running);
            }
            catch
            {
                return 0;
            }
        }

        #endregion

        #region Startup operations

        /// <summary>
        /// Enumerate startup items from the registry Run keys, the Startup folders,
        /// scheduled tasks and the Win32_StartupCommand WMI class.
        /// </summary>
        public static List<Models.SystemInfo.StartupItem> GetStartupItems()
        {
            var items = new List<Models.SystemInfo.StartupItem>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            CollectRegistryStartupItems(Registry.LocalMachine,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM Run", items, seen);

            CollectRegistryStartupItems(Registry.LocalMachine,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM RunOnce", items, seen);

            CollectRegistryStartupItems(Registry.LocalMachine,
                @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM Run (32-bit)", items, seen);

            CollectRegistryStartupItems(Registry.CurrentUser,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU Run", items, seen);

            CollectRegistryStartupItems(Registry.CurrentUser,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU RunOnce", items, seen);

            CollectFolderStartupItems(Environment.GetFolderPath(Environment.SpecialFolder.Startup),
                "Startup Folder", items, seen);

            CollectFolderStartupItems(Environment.GetFolderPath(Environment.SpecialFolder.CommonStartup),
                "Common Startup Folder", items, seen);

            CollectWmiStartupItems(items, seen);

            return items
                .OrderBy(i => i.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private static void CollectRegistryStartupItems(
            RegistryKey root, string subKeyPath, string sourceLabel,
            List<Models.SystemInfo.StartupItem> items, HashSet<string> seen)
        {
            try
            {
                using (var key = root.OpenSubKey(subKeyPath))
                {
                    if (key == null) return;

                    foreach (var valueName in key.GetValueNames())
                    {
                        try
                        {
                            var value = key.GetValue(valueName)?.ToString();
                            if (string.IsNullOrWhiteSpace(valueName) || string.IsNullOrWhiteSpace(value))
                                continue;

                            var identity = $"{sourceLabel}|{valueName}";
                            if (!seen.Add(identity)) continue;

                            items.Add(new Models.SystemInfo.StartupItem
                            {
                                Name = valueName,
                                Path = value!,
                                Source = $"Registry ({sourceLabel})",
                                IsEnabled = true,
                                IsWindowsItem = LooksLikeWindowsComponent(valueName, value!),
                                RegistryPath = subKeyPath,
                                CommandLine = value!
                            });
                        }
                        catch { }
                    }
                }
            }
            catch { }
        }

        private static void CollectFolderStartupItems(
            string folder, string sourceLabel,
            List<Models.SystemInfo.StartupItem> items, HashSet<string> seen)
        {
            try
            {
                if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;

                foreach (var file in Directory.GetFiles(folder))
                {
                    try
                    {
                        var name = Path.GetFileNameWithoutExtension(file);
                        if (string.IsNullOrWhiteSpace(name)) continue;

                        var identity = $"{sourceLabel}|{name}";
                        if (!seen.Add(identity)) continue;

                        items.Add(new Models.SystemInfo.StartupItem
                        {
                            Name = name,
                            Path = file,
                            Source = sourceLabel,
                            IsEnabled = true,
                            IsWindowsItem = LooksLikeWindowsComponent(name, file)
                        });
                    }
                    catch { }
                }
            }
            catch { }
        }

        private static void CollectWmiStartupItems(
            List<Models.SystemInfo.StartupItem> items, HashSet<string> seen)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT Name, Command, Location, User FROM Win32_StartupCommand"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        try
                        {
                            var name = obj["Name"]?.ToString();
                            var command = obj["Command"]?.ToString();
                            var location = obj["Location"]?.ToString() ?? string.Empty;

                            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(command))
                                continue;

                            var identity = $"WMI|{name}";
                            if (!seen.Add(identity)) continue;

                            items.Add(new Models.SystemInfo.StartupItem
                            {
                                Name = name!,
                                Path = command!,
                                Source = $"WMI ({location})",
                                IsEnabled = true,
                                IsWindowsItem = LooksLikeWindowsComponent(name!, command!),
                                CommandLine = command!
                            });
                        }
                        catch { }
                    }
                }
            }
            catch { }
        }

        /// <summary>
        /// Heuristic: does this startup entry belong to Windows / a hardware vendor
        /// (i.e. is it something we should keep our hands off by default)?
        /// </summary>
        private static bool LooksLikeWindowsComponent(string name, string path)
        {
            var haystack = $"{name} {path}".ToLowerInvariant();

            var indicators = new[]
            {
                "\\windows\\", "\\system32\\", "\\syswow64\\", "\\microsoft\\",
                "windows defender", "securityhealth", "onedrive",
                "windows security", "windows update", "xbox"
            };

            foreach (var indicator in indicators)
            {
                if (haystack.Contains(indicator))
                    return true;
            }

            return false;
        }

        /// <summary>
        /// Remove a startup entry (registry value or shortcut). The original value is returned so
        /// the caller can store it for Undo.
        ///
        /// The removal is only performed once the exact value that is about to be deleted has been
        /// written to durable storage by <see cref="StartupItemBackupStore"/>. Deleting a registry
        /// value destroys it, so "this change is reversible" has to be true of a later session too -
        /// an in-memory copy would make the promise expire as soon as the application closes. If the
        /// record cannot be written, nothing is removed.
        /// </summary>
        public static bool DisableStartupItem(Models.SystemInfo.StartupItem item, out string removedValue)
        {
            removedValue = string.Empty;

            if (item == null) return false;

            try
            {
                if (!string.IsNullOrEmpty(item.RegistryPath) && item.Source.Contains("Registry"))
                {
                    RegistryKey? root = null;

                    if (item.Source.Contains("HKLM"))
                        root = Registry.LocalMachine;
                    else if (item.Source.Contains("HKCU"))
                        root = Registry.CurrentUser;

                    if (root == null) return false;

                    using (var key = root.OpenSubKey(item.RegistryPath, writable: true))
                    {
                        if (key == null) return false;

                        removedValue = key.GetValue(item.Name)?.ToString() ?? item.Path ?? string.Empty;

                        // Back up first. A removal that cannot be recorded is not performed.
                        if (!StartupItemBackupStore.Save(item, removedValue))
                            return false;

                        key.DeleteValue(item.Name, throwOnMissingValue: false);
                        return true;
                    }
                }

                if (item.Source.Contains("Startup Folder"))
                {
                    if (File.Exists(item.Path))
                    {
                        removedValue = item.Path;

                        // Move instead of delete so the user can restore it manually.
                        var backupFolder = Path.Combine(Constants.AppConstants.BackupDirectoryPath, "StartupItems");
                        Directory.CreateDirectory(backupFolder);
                        var target = Path.Combine(backupFolder, Path.GetFileName(item.Path));

                        if (File.Exists(target)) File.Delete(target);
                        File.Move(item.Path, target);

                        // The moved file is already the durable copy; the record only carries the
                        // metadata that lets the entry be listed and restored from the interface.
                        StartupItemBackupStore.Save(item, removedValue);

                        return true;
                    }
                }
            }
            catch { }

            return false;
        }

        /// <summary>
        /// Restore a start-up entry from its durable record. Used when the entry is no longer present
        /// in the system - which is exactly the state a previous session left it in - so that the
        /// change can still be undone.
        /// </summary>
        public static bool RestoreStartupItemFromBackup(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return false;

            if (!StartupItemBackupStore.TryLoad(name, out var record))
                return false;

            var item = record.ToStartupItem();

            return RestoreStartupItem(item, record.OriginalValue);
        }

        /// <summary>
        /// Restore a previously removed startup entry.
        /// </summary>
        public static bool RestoreStartupItem(Models.SystemInfo.StartupItem item, string originalValue)
        {
            if (item == null) return false;

            try
            {
                if (!string.IsNullOrEmpty(item.RegistryPath) && item.Source.Contains("Registry"))
                {
                    RegistryKey? root = null;

                    if (item.Source.Contains("HKLM"))
                        root = Registry.LocalMachine;
                    else if (item.Source.Contains("HKCU"))
                        root = Registry.CurrentUser;

                    if (root == null) return false;

                    using (var key = root.OpenSubKey(item.RegistryPath, writable: true))
                    {
                        if (key == null) return false;

                        key.SetValue(item.Name, string.IsNullOrEmpty(originalValue) ? item.Path : originalValue);
                        return true;
                    }
                }

                if (item.Source.Contains("Startup Folder"))
                {
                    var backupFolder = Path.Combine(Constants.AppConstants.BackupDirectoryPath, "StartupItems");
                    var fileName = Path.GetFileName(item.Path);
                    var backupFile = Path.Combine(backupFolder, fileName);

                    if (File.Exists(backupFile))
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(item.Path)!);
                        if (File.Exists(item.Path)) File.Delete(item.Path);
                        File.Move(backupFile, item.Path);
                        return true;
                    }
                }
            }
            catch { }

            return false;
        }

        #endregion

        #region Security status (read only)

        /// <summary>
        /// True when Windows Defender real time protection appears to be ON.
        /// This is read-only telemetry: the application never changes it.
        /// </summary>
        public static bool IsDefenderRealTimeProtectionEnabled()
        {
            try
            {
                // Preferred source: the Defender PowerShell/WMI provider.
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    @"root\Microsoft\Windows\Defender", "SELECT RealTimeProtectionEnabled FROM MSFT_MpComputerStatus"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var value = obj["RealTimeProtectionEnabled"];
                        if (value != null)
                            return Convert.ToBoolean(value);
                    }
                }
            }
            catch { }

            // Fallback: policy registry value (1 = disabled).
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows Defender\Real-Time Protection"))
                {
                    if (key != null)
                    {
                        var disabled = key.GetValue("DisableRealtimeMonitoring");
                        if (disabled != null && Convert.ToInt32(disabled) == 1)
                            return false;
                    }
                }

                using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows Defender"))
                {
                    if (key != null)
                    {
                        var disabled = key.GetValue("DisableAntiSpyware");
                        if (disabled != null && Convert.ToInt32(disabled) == 1)
                            return false;
                    }
                }
            }
            catch { }

            // If we cannot determine the state, assume protected (never assume disabled).
            return true;
        }

        /// <summary>
        /// True when the Windows Firewall service is running.
        /// </summary>
        public static bool IsFirewallEnabled()
        {
            try
            {
                if (!IsServiceRunning("MpsSvc"))
                    return false;

                using (var key = Registry.LocalMachine.OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile"))
                {
                    if (key != null)
                    {
                        var enable = key.GetValue("EnableFirewall");
                        if (enable != null)
                            return Convert.ToInt32(enable) == 1;
                    }
                }

                return true;
            }
            catch
            {
                return true;
            }
        }

        /// <summary>
        /// True when User Account Control is enabled (EnableLUA = 1).
        /// </summary>
        public static bool IsUacEnabled()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"))
                {
                    if (key != null)
                    {
                        var enableLua = key.GetValue("EnableLUA");
                        if (enableLua != null)
                            return Convert.ToInt32(enableLua) == 1;
                    }
                }
            }
            catch { }

            return true; // Never claim UAC is off when unsure.
        }

        #endregion

        #region Power

        [StructLayout(LayoutKind.Sequential)]
        private struct SYSTEM_POWER_STATUS
        {
            public byte ACLineStatus;
            public byte BatteryFlag;
            public byte BatteryLifePercent;
            public byte SystemStatusFlag;
            public int BatteryLifeTime;
            public int BatteryFullLifeTime;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetSystemPowerStatus(out SYSTEM_POWER_STATUS lpSystemPowerStatus);

        private static SYSTEM_POWER_STATUS? ReadSystemPowerStatus()
        {
            try
            {
                if (GetSystemPowerStatus(out var status))
                    return status;
            }
            catch { }

            return null;
        }

        /// <summary>
        /// True when the machine runs on battery (AC line status 0 = offline).
        /// </summary>
        public static bool IsOnBattery()
        {
            var status = ReadSystemPowerStatus();
            return status.HasValue && status.Value.ACLineStatus == 0;
        }

        /// <summary>
        /// Battery charge in percent, or -1 when unknown (typical for desktops).
        /// </summary>
        public static int GetBatteryPercentage()
        {
            var status = ReadSystemPowerStatus();
            if (!status.HasValue) return -1;

            // 255 (0xFF) means "unknown".
            var percent = status.Value.BatteryLifePercent;
            return percent <= 100 ? percent : -1;
        }

        /// <summary>
        /// Remaining battery runtime in minutes, or -1 when unknown.
        /// </summary>
        public static int GetBatteryLifeRemainingMinutes()
        {
            var status = ReadSystemPowerStatus();
            if (!status.HasValue) return -1;

            var seconds = status.Value.BatteryLifeTime;
            return seconds < 0 ? -1 : seconds / 60;
        }

        /// <summary>
        /// Battery state flags (charging / critical / no battery).
        /// </summary>
        public static string GetBatteryStatusText()
        {
            var status = ReadSystemPowerStatus();
            if (!status.HasValue) return "Unknown";

            var flags = status.Value.BatteryFlag;

            if (flags == 128) return "No battery (desktop)";
            if (flags == 255) return "Unknown";

            var parts = new List<string>();

            if ((flags & 1) != 0) parts.Add("High");
            if ((flags & 2) != 0) parts.Add("Low");
            if ((flags & 4) != 0) parts.Add("Critical");
            if ((flags & 8) != 0) parts.Add("Charging");

            return parts.Count == 0 ? "Discharging" : string.Join(", ", parts);
        }

        /// <summary>
        /// Active power scheme recorded in the registry (GUID string, empty when unknown).
        /// </summary>
        public static string GetActivePowerSchemeGuid()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"))
                {
                    var active = key?.GetValue("ActivePowerScheme")?.ToString();
                    if (!string.IsNullOrEmpty(active))
                        return active!;
                }
            }
            catch { }

            return string.Empty;
        }

        /// <summary>
        /// True when the value is exactly a GUID in the form Windows uses for power schemes
        /// (<c>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</c>), optionally wrapped in braces.
        /// </summary>
        public static bool IsValidPowerSchemeGuid(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return false;

            var candidate = value!.Trim().Trim('{', '}');

            return Guid.TryParseExact(candidate, "D", out _);
        }

        /// <summary>
        /// Activate a Windows power scheme by GUID. Requires elevation.
        /// </summary>
        public static bool SetActivePowerScheme(string schemeGuid)
        {
            if (string.IsNullOrWhiteSpace(schemeGuid))
                return false;

            // A power scheme is identified by a GUID, so only a GUID is accepted. The value can come
            // from configuration, and interpolating an unchecked string into a command line is how
            // argument injection starts - there is no reason to accept anything but the exact format.
            if (!IsValidPowerSchemeGuid(schemeGuid))
                return false;

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "powercfg.exe",
                    Arguments = $"/setactive {schemeGuid}",
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                using (var process = Process.Start(psi))
                {
                    if (process == null) return false;

                    process.WaitForExit(15000);
                    return process.HasExited && process.ExitCode == 0;
                }
            }
            catch
            {
                return false;
            }
        }

        #endregion

        #region System restore

        /// <summary>
        /// Create a System Restore point (requires elevation and System Protection enabled).
        /// Returns false when Windows does not allow it - the caller must degrade gracefully.
        /// </summary>
        public static bool CreateRestorePoint(string description, int timeoutMs = 60000)
        {
            try
            {
                if (!IsAdministrator())
                    return false;

                var restorePoint = new RESTOREPOINTINFO
                {
                    dwEventType = 100,      // BEGIN_SYSTEM_CHANGE
                    dwRestorePtType = 0,    // APPLICATION_INSTALL
                    llSequenceNumber = 0,
                    szDescription = TruncateForRestorePoint(description)
                };

                var startResult = SRSetRestorePointW(ref restorePoint, out var status);
                if (startResult != STATUS_SUCCESS || status.nStatus != 0)
                    return false;

                // Close the change so the restore point becomes permanent.
                var endPoint = new RESTOREPOINTINFO
                {
                    dwEventType = 101,      // END_SYSTEM_CHANGE
                    dwRestorePtType = 0,
                    llSequenceNumber = status.llSequenceNumber,
                    szDescription = TruncateForRestorePoint(description)
                };

                var endResult = SRSetRestorePointW(ref endPoint, out _);
                return endResult == STATUS_SUCCESS;
            }
            catch
            {
                return false;
            }
        }

        private static string TruncateForRestorePoint(string description)
        {
            if (string.IsNullOrWhiteSpace(description))
                return "AI System Optimizer";

            // The API limits descriptions to 255 characters.
            return description.Length <= 255 ? description : description.Substring(0, 255);
        }

        #endregion

        #region DPI

        /// <summary>
        /// Opt into per-monitor DPI awareness so the WPF window stays sharp on scaled displays.
        /// </summary>
        public static void SetDpiAwareness()
        {
            // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            try
            {
                if (SetProcessDpiAwarenessContext(new IntPtr(-4)) != IntPtr.Zero)
                    return;
            }
            catch { }

            try
            {
                SetProcessDPIAware();
            }
            catch { }
        }

        #endregion
    }

    /// <summary>
    /// Thread access rights used by suspend/resume.
    /// </summary>
    [Flags]
    public enum ThreadAccess
    {
        TERMINATE = 0x0001,
        SUSPEND_RESUME = 0x0002,
        GET_CONTEXT = 0x0008,
        SET_CONTEXT = 0x0010,
        SET_INFORMATION = 0x0020,
        QUERY_INFORMATION = 0x0040,
        SET_THREAD_TOKEN = 0x0080,
        IMPERSONATE = 0x0100,
        DIRECT_IMPERSONATION = 0x0200,
        THREAD_ALL_ACCESS = 0x1F03FF
    }
}
