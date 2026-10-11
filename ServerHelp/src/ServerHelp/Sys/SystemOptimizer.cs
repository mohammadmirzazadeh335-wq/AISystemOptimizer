using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using ServerHelp.Core;

namespace ServerHelp.Sys
{
    public enum StepState { Pending, Done, Warn, Fail, Skip }

    public sealed class OptimizationStep
    {
        public string TitleFa = "";
        public string TitleEn = "";
        public StepState State = StepState.Pending;
        public string Detail = "";
        public int ElapsedMs;

        public string Title { get { return L.T(TitleFa, TitleEn); } }

        public string StateText
        {
            get
            {
                switch (State)
                {
                    case StepState.Done: return L.T("انجام شد", "done");
                    case StepState.Warn: return L.T("هشدار", "warning");
                    case StepState.Fail: return L.T("ناموفق", "failed");
                    case StepState.Skip: return L.T("رد شد", "skipped");
                    default: return L.T("در انتظار", "pending");
                }
            }
        }

        public string Line
        {
            get
            {
                string line = "• " + Title + " — " + StateText;
                if (!string.IsNullOrEmpty(Detail)) line += " (" + Detail + ")";
                return line;
            }
        }
    }

    /// <summary>
    /// Time critical, reversible system tuning. The whole set is meant to finish in a few seconds
    /// so the "one minute" budget for optimise + tunnel + launch holds.
    /// </summary>
    public sealed class SystemOptimizer
    {
        private readonly List<OptimizationStep> _steps = new List<OptimizationStep>();
        private readonly List<string> _firewallRulesAdded = new List<string>();
        private string _previousPowerPlan = "";
        private bool _timerRaised;

        public List<OptimizationStep> Steps { get { return _steps; } }
        public List<string> Notes = new List<string>();

        public string TunnelExePath = "";
        public string JavaExePath = "";

        // ------------------------------------------------------------- public API

        public void Run(AppSettings settings, Action<OptimizationStep> onStep)
        {
            if (!settings.OptimizeSystem)
            {
                Add(onStep, "بهینه‌سازی سیستم", "System tuning", StepState.Skip, L.T("در تنظیمات خاموش است", "disabled in settings"), 0);
                return;
            }

            if (settings.HighPerformancePowerPlan) ApplyPowerPlan(onStep);
            if (settings.TuneNetwork) ApplyNetworkTweaks(onStep);
            if (settings.AddFirewallRules) ApplyFirewall(onStep);
            if (settings.TrimMemory) TrimMemory(onStep);
            if (settings.CloseBackgroundApps) CloseBackgroundApps(onStep);
            RaiseTimerResolution(onStep);
        }

        /// <summary>Puts back everything this run changed.</summary>
        public void Restore(Action<string> report)
        {
            try
            {
                if (!string.IsNullOrEmpty(_previousPowerPlan))
                {
                    string error;
                    if (PowerPlan.Set(_previousPowerPlan, out error) && report != null)
                        report(L.T("طرح انرژی قبلی بازگردانده شد.", "previous power plan restored."));
                }
                if (_timerRaised)
                {
                    ProcessTuner.EndTimerResolution();
                    _timerRaised = false;
                }
                RegistryTweaks.Restore(report);
                foreach (string rule in _firewallRulesAdded)
                {
                    Tunnel.FirewallHelper.RemoveRule(rule);
                    Tunnel.FirewallHelper.RemoveRule(rule + " (in)");
                    Tunnel.FirewallHelper.RemoveRule(rule + " (out)");
                }
                _firewallRulesAdded.Clear();
            }
            catch (Exception ex) { Log.Warn("restore failed: " + ex.Message); }
        }

        // ---------------------------------------------------------------- steps

        private void ApplyPowerPlan(Action<OptimizationStep> onStep)
        {
            var watch = Stopwatch.StartNew();
            _previousPowerPlan = PowerPlan.ActiveScheme();
            string ultimate = PowerPlan.EnsureUltimate();
            string target = string.IsNullOrEmpty(ultimate) ? PowerPlan.HighPerformance : ultimate;
            string error;
            bool ok = PowerPlan.Set(target, out error);
            watch.Stop();
            Add(onStep, "طرح انرژی حداکثر کارایی", "High performance power plan",
                ok ? StepState.Done : StepState.Warn,
                ok ? L.T("طرح فعال: ", "active: ") + PowerPlan.ActiveSchemeName() : error,
                (int)watch.ElapsedMilliseconds);
        }

        private void ApplyNetworkTweaks(Action<OptimizationStep> onStep)
        {
            var watch = Stopwatch.StartNew();
            bool ok = RegistryTweaks.ApplyNetworkMultimedia();
            var flush = Shell.Run("ipconfig", "/flushdns", 10000);
            watch.Stop();
            string detail = ok
                ? L.T("کاهش throttle شبکه و اولویت بازی اعمال شد", "network throttling lowered, game priority raised")
                : L.T("دسترسی به رجیستری ممکن نشد", "registry access failed");
            if (flush.Ok) detail += L.T(" + کش DNS پاک شد", " + DNS cache flushed");
            Add(onStep, "بهینه‌سازی شبکه/چندرسانه", "Network and multimedia tuning",
                ok ? StepState.Done : StepState.Warn, detail, (int)watch.ElapsedMilliseconds);
        }

        private void ApplyFirewall(Action<OptimizationStep> onStep)
        {
            var watch = Stopwatch.StartNew();
            int done = 0;
            string lastError = "";
            if (!string.IsNullOrEmpty(TunnelExePath))
            {
                string error;
                if (Tunnel.FirewallHelper.EnsureProgramAllowed("ServerHelp sing-box", TunnelExePath, out error))
                {
                    _firewallRulesAdded.Add("ServerHelp sing-box");
                    done++;
                }
                else lastError = error;
            }
            if (!string.IsNullOrEmpty(JavaExePath))
            {
                string error;
                if (Tunnel.FirewallHelper.EnsureProgramAllowed("ServerHelp Java", JavaExePath, out error))
                {
                    _firewallRulesAdded.Add("ServerHelp Java");
                    done++;
                }
                else lastError = error;
            }
            watch.Stop();
            if (done == 0 && string.IsNullOrEmpty(lastError))
                Add(onStep, "قواعد فایروال", "Firewall rules", StepState.Skip,
                    L.T("برنامه‌ای برای مجاز کردن پیدا نشد", "no program to allow yet"), (int)watch.ElapsedMilliseconds);
            else
                Add(onStep, "قواعد فایروال", "Firewall rules",
                    done > 0 ? StepState.Done : StepState.Warn,
                    done > 0 ? L.T("اجازه عبور برای ", "allowed ") + L.N(done) + L.T(" برنامه", " program(s)") : lastError,
                    (int)watch.ElapsedMilliseconds);
        }

        private void TrimMemory(Action<OptimizationStep> onStep)
        {
            var watch = Stopwatch.StartNew();
            long freed = ProcessTuner.TrimBackgroundWorkingSets();
            watch.Stop();
            Add(onStep, "آزادسازی حافظه برنامه‌های بی‌کار", "Free idle applications' memory",
                StepState.Done,
                freed > 0 ? Shell.HumanSize(freed) + L.T(" آزاد شد", " released") : L.T("چیزی برای آزاد کردن نبود", "nothing to release"),
                (int)watch.ElapsedMilliseconds);
        }

        private void CloseBackgroundApps(Action<OptimizationStep> onStep)
        {
            var watch = Stopwatch.StartNew();
            List<string> closed = ProcessTuner.CloseBackgroundApps();
            watch.Stop();
            Add(onStep, "بستن برنامه‌های سنگین پس‌زمینه", "Close heavy background apps",
                closed.Count > 0 ? StepState.Done : StepState.Skip,
                closed.Count > 0 ? string.Join(", ", closed.ToArray()) : L.T("برنامه‌ای باز نبود", "nothing was open"),
                (int)watch.ElapsedMilliseconds);
        }

        private void RaiseTimerResolution(Action<OptimizationStep> onStep)
        {
            bool ok = ProcessTuner.BeginTimerResolution();
            _timerRaised = ok;
            Add(onStep, "دقت تایمر سیستم (کاهش لگ)", "System timer resolution (smoother ticks)",
                ok ? StepState.Done : StepState.Skip, ok ? "1 ms" : "", 0);
        }

        private void Add(Action<OptimizationStep> onStep, string fa, string en, StepState state, string detail, int ms)
        {
            var step = new OptimizationStep();
            step.TitleFa = fa;
            step.TitleEn = en;
            step.State = state;
            step.Detail = detail ?? "";
            step.ElapsedMs = ms;
            _steps.Add(step);
            Log.Info("optimise: " + step.Line);
            if (onStep != null) onStep(step);
        }
    }

    /// <summary>Windows registry tweaks with an automatic backup of the previous values.</summary>
    public static class RegistryTweaks
    {
        private const string SystemProfile = @"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile";
        private const string GamesTask = @"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games";
        private static string BackupFile { get { return Path.Combine(AppPaths.Backups, "registry-backup.json"); } }

        public static bool ApplyNetworkMultimedia()
        {
            try
            {
                AppPaths.EnsureAll();
                var backup = new Dictionary<string, string>();
                if (File.Exists(BackupFile))
                {
                    try
                    {
                        var existing = Json.ParseObject(File.ReadAllText(BackupFile));
                        foreach (var kv in existing) backup[kv.Key] = kv.Value == null ? "" : kv.Value.ToString();
                    }
                    catch { }
                }

                WriteDword(backup, SystemProfile, "NetworkThrottlingIndex", unchecked((int)0xFFFFFFFF));
                WriteDword(backup, SystemProfile, "SystemResponsiveness", 10);
                WriteDword(backup, GamesTask, "GPU Priority", 8);
                WriteDword(backup, GamesTask, "Priority", 6);
                WriteString(backup, GamesTask, "Scheduling Category", "High");
                WriteString(backup, GamesTask, "SFIO Priority", "High");

                var w = new JsonWriter(true);
                w.StartObject();
                foreach (var kv in backup) w.Prop(kv.Key, kv.Value);
                w.EndObject();
                File.WriteAllText(BackupFile, w.ToString());
                return true;
            }
            catch (Exception ex)
            {
                Log.Warn("registry tuning failed: " + ex.Message);
                return false;
            }
        }

        private static void WriteDword(Dictionary<string, string> backup, string path, string name, int value)
        {
            using (RegistryKey key = Registry.LocalMachine.CreateSubKey(path))
            {
                if (key == null) return;
                string id = path + "|" + name;
                if (!backup.ContainsKey(id))
                {
                    object old = key.GetValue(name);
                    backup[id] = old == null ? "MISSING" : ("DWORD:" + old.ToString());
                }
                key.SetValue(name, value, RegistryValueKind.DWord);
            }
        }

        private static void WriteString(Dictionary<string, string> backup, string path, string name, string value)
        {
            using (RegistryKey key = Registry.LocalMachine.CreateSubKey(path))
            {
                if (key == null) return;
                string id = path + "|" + name;
                if (!backup.ContainsKey(id))
                {
                    object old = key.GetValue(name);
                    backup[id] = old == null ? "MISSING" : ("SZ:" + old.ToString());
                }
                key.SetValue(name, value, RegistryValueKind.String);
            }
        }

        public static void Restore(Action<string> report)
        {
            try
            {
                if (!File.Exists(BackupFile)) return;
                var data = Json.ParseObject(File.ReadAllText(BackupFile));
                int restored = 0;
                foreach (var kv in data)
                {
                    string[] parts = kv.Key.Split('|');
                    if (parts.Length != 2) continue;
                    string path = parts[0];
                    string name = parts[1];
                    string value = kv.Value == null ? "MISSING" : kv.Value.ToString();
                    using (RegistryKey key = Registry.LocalMachine.OpenSubKey(path, true))
                    {
                        if (key == null) continue;
                        if (value == "MISSING") { try { key.DeleteValue(name, false); } catch { } }
                        else if (value.StartsWith("DWORD:"))
                        {
                            int number;
                            if (int.TryParse(value.Substring(6), out number)) key.SetValue(name, number, RegistryValueKind.DWord);
                        }
                        else if (value.StartsWith("SZ:"))
                        {
                            key.SetValue(name, value.Substring(3), RegistryValueKind.String);
                        }
                        restored++;
                    }
                }
                if (restored > 0 && report != null)
                    report(L.T("تنظیمات رجیستری به حالت قبل برگشت.", "registry tweaks reverted."));
            }
            catch (Exception ex) { Log.Warn("registry restore failed: " + ex.Message); }
        }
    }

    /// <summary>Process level tuning: priorities, working set trimming, timers, closing apps.</summary>
    public static class ProcessTuner
    {
        [DllImport("winmm.dll", EntryPoint = "timeBeginPeriod")]
        private static extern uint TimeBeginPeriod(uint milliseconds);

        [DllImport("winmm.dll", EntryPoint = "timeEndPeriod")]
        private static extern uint TimeEndPeriod(uint milliseconds);

        [DllImport("psapi.dll", SetLastError = true)]
        private static extern bool EmptyWorkingSet(IntPtr process);

        [DllImport("kernel32.dll")]
        private static extern IntPtr OpenProcess(int access, bool inheritHandle, int processId);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        private const int ProcessSetQuota = 0x0100;
        private const int ProcessQueryLimitedInformation = 0x1000;

        private static readonly string[] NeverTrim = new string[]
        {
            "system", "idle", "registry", "smss", "csrss", "wininit", "services", "lsass", "winlogon",
            "dwm", "explorer", "svchost", "audiodg", "memcompression", "msmpeng", "securityhealthservice",
            "serverhelp", "sing-box", "javaw", "java"
        };

        private static readonly string[] CloseCandidates = new string[]
        {
            "chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "iexplore",
            "discord", "telegram", "whatsapp", "skype", "slack", "zoom", "spotify",
            "onedrive", "dropbox", "googledrive", "teams", "ms-teams",
            "adobe creative cloud", "creative cloud", "galaxyclient", "epicgameslauncher",
            "battle.net", "utorrent", "qbittorrent", "thunder", "idman", "steamwebhelper"
        };

        public static bool BeginTimerResolution()
        {
            try { return TimeBeginPeriod(1) == 0; }
            catch { return false; }
        }

        public static void EndTimerResolution()
        {
            try { TimeEndPeriod(1); } catch { }
        }

        /// <summary>Frees the idle parts of background processes. Returns bytes that were trimmed.</summary>
        public static long TrimBackgroundWorkingSets()
        {
            long before = 0, after = 0;
            var self = Process.GetCurrentProcess().Id;
            foreach (Process process in SafeProcesses())
            {
                try
                {
                    if (process.Id == self) continue;
                    string name = process.ProcessName.ToLowerInvariant();
                    if (Array.IndexOf(NeverTrim, name) >= 0) continue;
                    if (process.SessionId != Process.GetCurrentProcess().SessionId) continue;
                    if (process.MainWindowHandle != IntPtr.Zero) continue;   // the user is looking at it
                    long working = process.WorkingSet64;
                    if (working < 60L * 1024 * 1024) continue;
                    IntPtr handle = OpenProcess(ProcessSetQuota | ProcessQueryLimitedInformation, false, process.Id);
                    if (handle == IntPtr.Zero) continue;
                    try
                    {
                        if (EmptyWorkingSet(handle))
                        {
                            process.Refresh();
                            before += working;
                            after += process.WorkingSet64;
                        }
                    }
                    finally { CloseHandle(handle); }
                }
                catch { }
            }
            long freed = before - after;
            if (freed > 0) Log.Info("trimmed " + Shell.HumanSize(freed) + " of idle working sets");
            return freed > 0 ? freed : 0;
        }

        /// <summary>Sends WM_CLOSE to well known heavy background apps. Returns the names closed.</summary>
        public static List<string> CloseBackgroundApps()
        {
            var closed = new List<string>();
            foreach (Process process in SafeProcesses())
            {
                try
                {
                    string name = process.ProcessName.ToLowerInvariant();
                    if (Array.IndexOf(CloseCandidates, name) < 0) continue;
                    if (process.MainWindowHandle == IntPtr.Zero) continue;
                    if (process.CloseMainWindow(1))
                    {
                        closed.Add(process.ProcessName);
                        Log.Info("asked " + process.ProcessName + " to close");
                    }
                }
                catch { }
            }
            return closed;
        }

        public static bool SetPriority(string processName, ProcessPriorityClass priority)
        {
            bool any = false;
            foreach (Process process in SafeProcesses())
            {
                try
                {
                    if (!string.Equals(process.ProcessName, processName, StringComparison.OrdinalIgnoreCase)) continue;
                    process.PriorityClass = priority;
                    any = true;
                }
                catch { }
            }
            return any;
        }

        public static bool SetPriorityById(int pid, ProcessPriorityClass priority)
        {
            try
            {
                using (Process process = Process.GetProcessById(pid))
                {
                    process.PriorityClass = priority;
                    return true;
                }
            }
            catch (Exception ex)
            {
                Log.Debug("priority for pid " + pid + " failed: " + ex.Message);
                return false;
            }
        }

        public static List<Process> SafeProcesses()
        {
            var list = new List<Process>();
            try
            {
                list.AddRange(Process.GetProcesses());
            }
            catch { }
            return list;
        }
    }
}
