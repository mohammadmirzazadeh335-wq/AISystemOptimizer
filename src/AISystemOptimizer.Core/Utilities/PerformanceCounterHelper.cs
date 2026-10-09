using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Management;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Wrapper around Windows Performance Counters and WMI.
    ///
    /// Design rules (important for honesty of the product):
    ///  * Counters are cached - creating them on every sample would itself cost CPU.
    ///  * A counter that does not exist returns a neutral value and sets
    ///    <see cref="LastError"/>, it never fabricates a number.
    ///  * Temperature is only reported when a real sensor exposes it.
    /// </summary>
    public static class PerformanceCounterHelper
    {
        #region State

        private static readonly object SyncRoot = new object();
        private static readonly Dictionary<string, PerformanceCounter> CounterCache =
            new Dictionary<string, PerformanceCounter>(StringComparer.OrdinalIgnoreCase);

        private static DateTime _lastCacheReset = DateTime.UtcNow;
        private static readonly TimeSpan CacheLifetime = TimeSpan.FromMinutes(2);

        // Hardware identity never changes while Windows runs; once a WMI read of it succeeds it is
        // cached for good, and a failed read is retried at most once a minute. This keeps the
        // two-second live sampler from re-asking a broken WMI repository on every tick.
        private static string? _cpuNameCache;
        private static DateTime _cpuNameNextAttempt = DateTime.MinValue;
        private static string? _cpuManufacturerCache;
        private static DateTime _cpuManufacturerNextAttempt = DateTime.MinValue;
        private static int _coreCountCache;
        private static DateTime _coreCountNextAttempt = DateTime.MinValue;
        private static (double, double)? _cpuClockCache;
        private static DateTime _cpuClockNextAttempt = DateTime.MinValue;

        /// <summary>
        /// Last error raised by a counter/WMI call (empty when the last call succeeded).
        /// </summary>
        public static string LastError { get; private set; } = string.Empty;

        #endregion

        #region Counter plumbing

        /// <summary>
        /// Get (and cache) a counter. Returns null when the category/counter does not exist.
        /// </summary>
        private static PerformanceCounter? GetCounter(string category, string counter, string? instance = null)
        {
            var key = string.IsNullOrEmpty(instance)
                ? $"{category}|{counter}"
                : $"{category}|{counter}|{instance}";

            lock (SyncRoot)
            {
                if (DateTime.UtcNow - _lastCacheReset > CacheLifetime)
                {
                    ResetCacheInternal();
                }

                if (CounterCache.TryGetValue(key, out var cached))
                    return cached;
            }

            // Creation and priming talk to the counter store, which on a corrupt machine can
            // block for a long time. They therefore run OUTSIDE the cache lock and with a hard
            // limit; if two threads race, the loser disposes its counter and uses the winner's.
            var created = BoundedReader.Read<PerformanceCounter?>(() =>
            {
                var candidate = string.IsNullOrEmpty(instance)
                    ? new PerformanceCounter(category, counter, readOnly: true)
                    : new PerformanceCounter(category, counter, instance, readOnly: true);

                candidate.NextValue(); // prime the counter
                return candidate;
            }, null, 2500, $"counter {category}\\{counter}");

            if (created == null)
            {
                LastError = $"{category}\\{counter}: unavailable or timed out";
                return null;
            }

            lock (SyncRoot)
            {
                if (CounterCache.TryGetValue(key, out var winner))
                {
                    try { created.Dispose(); } catch { }
                    return winner;
                }

                CounterCache[key] = created;
                LastError = string.Empty;
                return created;
            }
        }

        private static void ResetCacheInternal()
        {
            foreach (var counter in CounterCache.Values)
            {
                try { counter.Dispose(); } catch { }
            }

            CounterCache.Clear();
            _lastCacheReset = DateTime.UtcNow;
        }

        /// <summary>
        /// Dispose cached counters. Call before the application exits.
        /// </summary>
        public static void ResetCache()
        {
            lock (SyncRoot)
            {
                ResetCacheInternal();
            }
        }

        /// <summary>
        /// Sample a counter twice with a short delay - the documented way to get a rate.
        /// </summary>
        private static float SampleCounter(string category, string counter, string? instance = null, int delayMs = 500)
        {
            var pc = GetCounter(category, counter, instance);
            if (pc == null) return 0f;

            try
            {
                // Both reads are bounded: a stuck counter store must cost this call at most a
                // few seconds, never the thread that called it.
                BoundedReader.Read(() => { pc.NextValue(); return 0f; }, 0f, 1500,
                    $"prime {category}\\{counter}");

                if (delayMs > 0)
                    System.Threading.Thread.Sleep(delayMs);

                var value = BoundedReader.Read(() => pc.NextValue(), float.NaN, 1500,
                    $"sample {category}\\{counter}");

                return float.IsNaN(value) || float.IsInfinity(value) ? 0f : value;
            }
            catch (Exception ex)
            {
                LastError = $"{category}\\{counter}: {ex.Message}";
                return 0f;
            }
        }

        /// <summary>
        /// True when the given counter category is registered on this machine.
        /// </summary>
        public static bool CounterCategoryExists(string category)
        {
            return BoundedReader.Read(() => CounterCategoryExistsCore(category), false, 2000, "counter category probe");
        }

        private static bool CounterCategoryExistsCore(string category)
        {
            try
            {
                return PerformanceCounterCategory.Exists(category);
            }
            catch
            {
                return false;
            }
        }

        #endregion

        #region Memory

        /// <summary>
        /// Total physical memory in bytes.
        /// </summary>
        public static long GetTotalPhysicalMemory()
        {
            return WindowsApiHelper.GetTotalPhysicalMemory();
        }

        /// <summary>
        /// Available physical memory in bytes.
        /// </summary>
        public static long GetAvailablePhysicalMemory()
        {
            return WindowsApiHelper.GetAvailablePhysicalMemory();
        }

        /// <summary>
        /// Used physical memory in bytes.
        /// </summary>
        public static long GetUsedPhysicalMemory()
        {
            var total = GetTotalPhysicalMemory();
            var available = GetAvailablePhysicalMemory();

            if (total <= 0) return 0;

            var used = total - available;
            return used < 0 ? 0 : used;
        }

        /// <summary>
        /// Memory load in percent (from the OS, not derived from our own maths).
        /// </summary>
        public static float GetMemoryUsagePercentage()
        {
            return WindowsApiHelper.GetMemoryLoadPercentage();
        }

        /// <summary>
        /// System cache bytes (the "Cache Bytes" counter).
        /// </summary>
        public static long GetCachedMemory()
        {
            return BoundedReader.Read(GetCachedMemoryCore, 0, 2000, "cached memory");
        }

        private static long GetCachedMemoryCore()
        {
            var value = SampleCounter("Memory", "Cache Bytes", null, 0);
            return (long)Math.Max(0, value);
        }

        /// <summary>
        /// Standby (cached, reclaimable) memory in bytes.
        /// Windows deliberately keeps RAM in standby - this is not a problem to "fix".
        /// </summary>
        public static long GetStandbyMemory()
        {
            return BoundedReader.Read(GetStandbyMemoryCore, 0, 3000, "standby memory");
        }

        private static long GetStandbyMemoryCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT StandbyCacheNormalPriorityBytes, StandbyCacheReserveBytes, " +
                    "StandbyCacheCoreBytes FROM Win32_PerfRawData_PerfOS_Memory"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        long total = 0;

                        total += SafeToLong(obj["StandbyCacheNormalPriorityBytes"]);
                        total += SafeToLong(obj["StandbyCacheReserveBytes"]);
                        total += SafeToLong(obj["StandbyCacheCoreBytes"]);

                        return total;
                    }
                }
            }
            catch (Exception ex)
            {
                LastError = $"Standby memory: {ex.Message}";
            }

            return 0;
        }

        /// <summary>
        /// Free (truly unused) memory in bytes.
        /// </summary>
        public static long GetFreeMemory()
        {
            return BoundedReader.Read(GetFreeMemoryCore, 0, 4000, "free memory");
        }

        private static long GetFreeMemoryCore()
        {
            var value = SampleCounter("Memory", "Free &amp; Zero Page List Bytes", null, 0);
            if (value <= 0)
                value = SampleCounter("Memory", "Available Bytes", null, 0);

            return (long)Math.Max(0, value);
        }

        /// <summary>
        /// Paged pool bytes.
        /// </summary>
        public static long GetPagedPoolMemory()
        {
            return BoundedReader.Read(GetPagedPoolMemoryCore, 0, 2000, "paged pool");
        }

        private static long GetPagedPoolMemoryCore()
        {
            return (long)Math.Max(0, SampleCounter("Memory", "Pool Paged Bytes", null, 0));
        }

        /// <summary>
        /// Non-paged pool bytes.
        /// </summary>
        public static long GetNonPagedPoolMemory()
        {
            return BoundedReader.Read(GetNonPagedPoolMemoryCore, 0, 2000, "non-paged pool");
        }

        private static long GetNonPagedPoolMemoryCore()
        {
            return (long)Math.Max(0, SampleCounter("Memory", "Pool Nonpaged Bytes", null, 0));
        }

        /// <summary>
        /// Committed bytes (what the OS promised to processes).
        /// </summary>
        public static long GetCommittedMemory()
        {
            return BoundedReader.Read(GetCommittedMemoryCore, 0, 2000, "committed bytes");
        }

        private static long GetCommittedMemoryCore()
        {
            return (long)Math.Max(0, SampleCounter("Memory", "Committed Bytes", null, 0));
        }

        /// <summary>
        /// Commit limit in bytes.
        /// </summary>
        public static long GetCommitLimit()
        {
            return BoundedReader.Read(GetCommitLimitCore, 0, 2000, "commit limit");
        }

        private static long GetCommitLimitCore()
        {
            return (long)Math.Max(0, SampleCounter("Memory", "Commit Limit", null, 0));
        }

        /// <summary>
        /// Page file usage in bytes.
        /// </summary>
        public static long GetPageFileUsage()
        {
            return BoundedReader.Read(GetPageFileUsageCore, 0, 5000, "page file usage");
        }

        private static long GetPageFileUsageCore()
        {
            var (_, available) = WindowsApiHelper.GetPageFileBytes();
            // "Available" from GlobalMemoryStatusEx refers to the commit charge,
            // so usage is: commit limit - available.
            var limit = GetCommitLimit();
            if (limit > 0 && available > 0)
                return Math.Max(0, limit - available);

            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT AllocatedBaseSize, CurrentUsage FROM Win32_PageFileUsage"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var currentUsageMb = SafeToLong(obj["CurrentUsage"]);
                        if (currentUsageMb > 0)
                            return currentUsageMb * 1024 * 1024;
                    }
                }
            }
            catch { }

            return 0;
        }

        /// <summary>
        /// Page file limit in bytes.
        /// </summary>
        public static long GetPageFileLimit()
        {
            return BoundedReader.Read(GetPageFileLimitCore, 0, 4000, "page file limit");
        }

        private static long GetPageFileLimitCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT AllocatedBaseSize FROM Win32_PageFileUsage"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var allocatedMb = SafeToLong(obj["AllocatedBaseSize"]);
                        if (allocatedMb > 0)
                            return allocatedMb * 1024 * 1024;
                    }
                }
            }
            catch { }

            var (total, _) = WindowsApiHelper.GetPageFileBytes();
            return total;
        }

        /// <summary>
        /// Page file usage in percent.
        /// </summary>
        public static float GetPageFileUsagePercentage()
        {
            return BoundedReader.Read(GetPageFileUsagePercentageCore, 0f, 9000, "page file percentage");
        }

        private static float GetPageFileUsagePercentageCore()
        {
            var limit = GetPageFileLimit();
            if (limit <= 0) return 0f;

            var used = GetPageFileUsage();
            return (float)Math.Max(0, Math.Min(100, used / (double)limit * 100));
        }

        #endregion

        #region CPU

        /// <summary>
        /// Total CPU usage in percent.
        /// </summary>
        public static float GetCpuUsage()
        {
            return BoundedReader.Read(GetCpuUsageCore, 0f, 3000, "CPU usage");
        }

        private static float GetCpuUsageCore()
        {
            return SampleCounter("Processor Information", "% Processor Utility", "_Total", 500) switch
            {
                var utility when utility > 0 => Math.Min(100f, utility),
                _ => Math.Min(100f, SampleCounter("Processor", "% Processor Time", "_Total", 500))
            };
        }

        /// <summary>
        /// Per-core CPU usage in percent.
        /// </summary>
        public static float[] GetCpuUsagePerCore()
        {
            return BoundedReader.Read(GetCpuUsagePerCoreCore, Array.Empty<float>(), 5000, "per-core CPU");
        }

        private static float[] GetCpuUsagePerCoreCore()
        {
            var coreCount = Environment.ProcessorCount;
            if (coreCount <= 0) return Array.Empty<float>();

            var usage = new float[coreCount];
            var counters = new PerformanceCounter?[coreCount];

            try
            {
                for (int i = 0; i < coreCount; i++)
                {
                    counters[i] = GetCounter("Processor", "% Processor Time", i.ToString());
                    counters[i]?.NextValue();
                }

                System.Threading.Thread.Sleep(400);

                for (int i = 0; i < coreCount; i++)
                {
                    if (counters[i] == null) continue;

                    try
                    {
                        var value = counters[i]!.NextValue();
                        usage[i] = float.IsNaN(value) ? 0f : Math.Max(0f, Math.Min(100f, value));
                    }
                    catch
                    {
                        usage[i] = 0f;
                    }
                }
            }
            catch (Exception ex)
            {
                LastError = $"Per-core CPU: {ex.Message}";
            }

            return usage;
        }

        /// <summary>
        /// Average load across all cores.
        /// </summary>
        public static float GetCpuLoad()
        {
            return BoundedReader.Read(GetCpuLoadCore, 0f, 6000, "CPU load");
        }

        private static float GetCpuLoadCore()
        {
            var perCore = GetCpuUsagePerCore();
            return perCore.Length == 0 ? 0f : perCore.Average();
        }

        /// <summary>
        /// Number of context switches per second (system responsiveness signal).
        /// </summary>
        public static float GetContextSwitchesPerSecond()
        {
            return BoundedReader.Read(GetContextSwitchesPerSecondCore, 0f, 2500, "context switches");
        }

        private static float GetContextSwitchesPerSecondCore()
        {
            return SampleCounter("System", "Context Switches/sec", null, 500);
        }

        /// <summary>
        /// Run queue length - number of threads waiting for CPU.
        /// </summary>
        public static float GetProcessorQueueLength()
        {
            return BoundedReader.Read(GetProcessorQueueLengthCore, 0f, 2000, "processor queue");
        }

        private static float GetProcessorQueueLengthCore()
        {
            return SampleCounter("System", "Processor Queue Length", null, 0);
        }

        #endregion

        #region CPU / GPU identity

        /// <summary>
        /// CPU marketing name (empty when WMI is unavailable).
        /// </summary>
        public static string GetCpuName()
        {
            if (_cpuNameCache != null) return _cpuNameCache;
            if (DateTime.UtcNow < _cpuNameNextAttempt) return string.Empty;

            _cpuNameNextAttempt = DateTime.UtcNow.AddSeconds(60);
            var value = BoundedReader.Read(GetCpuNameCore, string.Empty, 3000, "CPU name");

            if (!string.IsNullOrEmpty(value)) _cpuNameCache = value;
            return value;
        }

        private static string GetCpuNameCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher("SELECT Name FROM Win32_Processor"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var name = obj["Name"]?.ToString()?.Trim();
                        if (!string.IsNullOrEmpty(name))
                            return name!;
                    }
                }
            }
            catch (Exception ex)
            {
                LastError = $"CPU name: {ex.Message}";
            }

            return string.Empty;
        }

        /// <summary>
        /// CPU manufacturer (AuthenticAMD / GenuineIntel / ...).
        /// </summary>
        public static string GetCpuManufacturer()
        {
            if (_cpuManufacturerCache != null) return _cpuManufacturerCache;
            if (DateTime.UtcNow < _cpuManufacturerNextAttempt) return string.Empty;

            _cpuManufacturerNextAttempt = DateTime.UtcNow.AddSeconds(60);
            var value = BoundedReader.Read(GetCpuManufacturerCore, string.Empty, 3000, "CPU manufacturer");

            if (!string.IsNullOrEmpty(value)) _cpuManufacturerCache = value;
            return value;
        }

        private static string GetCpuManufacturerCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher("SELECT Manufacturer FROM Win32_Processor"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var manufacturer = obj["Manufacturer"]?.ToString()?.Trim();
                        if (!string.IsNullOrEmpty(manufacturer))
                            return manufacturer!;
                    }
                }
            }
            catch { }

            return string.Empty;
        }

        /// <summary>
        /// Physical core count (falls back to logical processor count).
        /// </summary>
        public static int GetPhysicalCoreCount()
        {
            if (_coreCountCache > 0) return _coreCountCache;
            if (DateTime.UtcNow < _coreCountNextAttempt) return Environment.ProcessorCount;

            _coreCountNextAttempt = DateTime.UtcNow.AddSeconds(60);
            var value = BoundedReader.Read(GetPhysicalCoreCountCore, 0, 3000, "physical core count");

            if (value > 0) _coreCountCache = value;
            return value > 0 ? value : Environment.ProcessorCount;
        }

        private static int GetPhysicalCoreCountCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher("SELECT NumberOfCores FROM Win32_Processor"))
                {
                    int total = 0;
                    foreach (var obj in searcher.Get())
                    {
                        total += (int)SafeToLong(obj["NumberOfCores"]);
                    }

                    if (total > 0) return total;
                }
            }
            catch { }

            return Environment.ProcessorCount;
        }

        /// <summary>
        /// Nominal / current / max clock in MHz. Returns (current, max) - (0,0) when unavailable.
        /// </summary>
        public static (double Current, double Max) GetCpuClockMhz()
        {
            if (_cpuClockCache != null) return _cpuClockCache.Value;
            if (DateTime.UtcNow < _cpuClockNextAttempt) return (0, 0);

            _cpuClockNextAttempt = DateTime.UtcNow.AddSeconds(60);
            var value = BoundedReader.Read(GetCpuClockMhzCore, (0.0, 0.0), 3000, "CPU clock");

            if (value != (0.0, 0.0)) _cpuClockCache = value;
            return value;
        }

        private static (double Current, double Max) GetCpuClockMhzCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT CurrentClockSpeed, MaxClockSpeed FROM Win32_Processor"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var current = SafeToDouble(obj["CurrentClockSpeed"]);
                        var max = SafeToDouble(obj["MaxClockSpeed"]);
                        return (current, max);
                    }
                }
            }
            catch { }

            return (0, 0);
        }

        /// <summary>
        /// CPU temperature in Celsius, or null when no sensor is exposed.
        /// NEVER fabricates a value - the UI must show "N/A" when this returns null.
        /// </summary>
        public static float? GetCpuTemperature()
        {
            return BoundedReader.Read(GetCpuTemperatureCore, (float?)null, 4000, "CPU temperature");
        }

        private static float? GetCpuTemperatureCore()
        {
            // MSAcpi_ThermalZoneTemperature reports tenths of Kelvin.
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    @"root\WMI", "SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var tenthsKelvin = SafeToDouble(obj["CurrentTemperature"]);
                        if (tenthsKelvin <= 0) continue;

                        var celsius = (tenthsKelvin / 10.0) - 273.15;
                        if (celsius > -50 && celsius < 150)
                            return (float)celsius;
                    }
                }
            }
            catch { }

            // Win32_TemperatureProbe (rarely implemented by OEMs).
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT CurrentReading FROM Win32_TemperatureProbe"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var celsius = SafeToDouble(obj["CurrentReading"]);
                        if (celsius > -50 && celsius < 150)
                            return (float)celsius;
                    }
                }
            }
            catch { }

            return null;
        }

        /// <summary>
        /// GPU list with name, vendor, driver version and (when available) usage/memory.
        /// </summary>
        public static List<GpuCounterInfo> GetGpuInformation()
        {
            return BoundedReader.Read(GetGpuInformationCore, new List<GpuCounterInfo>(), 10000, "GPU information");
        }

        private static List<GpuCounterInfo> GetGpuInformationCore()
        {
            var gpus = new List<GpuCounterInfo>();

            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT Name, AdapterCompatibility, DriverVersion, AdapterRAM, PNPDeviceID " +
                    "FROM Win32_VideoController"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        try
                        {
                            var name = obj["Name"]?.ToString()?.Trim();
                            if (string.IsNullOrEmpty(name)) continue;

                            var gpu = new GpuCounterInfo
                            {
                                Name = name!,
                                Manufacturer = obj["AdapterCompatibility"]?.ToString()?.Trim() ?? string.Empty,
                                DriverVersion = obj["DriverVersion"]?.ToString()?.Trim() ?? string.Empty,
                                PnpDeviceId = obj["PNPDeviceID"]?.ToString() ?? string.Empty,
                                TotalMemory = SafeToLong(obj["AdapterRAM"]),
                                Usage = GetGpuUsage(),
                                UsedMemory = GetGpuMemoryUsage()
                            };

                            // Identify integrated vs dedicated hardware.
                            var lower = gpu.Name.ToLowerInvariant();
                            if (lower.Contains("radeon graphics") || lower.Contains("vega") ||
                                lower.Contains("intel") || lower.Contains("uhd") || lower.Contains("iris"))
                            {
                                gpu.Type = "Integrated";
                            }
                            else
                            {
                                gpu.Type = "Dedicated";
                            }

                            gpus.Add(gpu);
                        }
                        catch { }
                    }
                }
            }
            catch (Exception ex)
            {
                LastError = $"GPU information: {ex.Message}";
            }

            return gpus;
        }

        /// <summary>
        /// Overall GPU utilization in percent using the "GPU Engine" counters (Windows 10 1709+).
        /// Returns 0 when the counters are unavailable - callers display N/A in that case.
        /// </summary>
        public static float GetGpuUsage()
        {
            return BoundedReader.Read(GetGpuUsageCore, 0f, 5000, "GPU usage");
        }

        private static float GetGpuUsageCore()
        {
            try
            {
                if (!CounterCategoryExists("GPU Engine"))
                    return 0f;

                var category = new PerformanceCounterCategory("GPU Engine");
                var instanceNames = category.GetInstanceNames();

                if (instanceNames.Length == 0)
                    return 0f;

                float total = 0f;
                var counters = new List<PerformanceCounter>();
                var sampledInstances = 0;

                foreach (var instance in instanceNames)
                {
                    // Only aggregate the *_engtype_3D / Compute / VideoDecode engines.
                    if (!instance.Contains("engtype_3D") &&
                        !instance.Contains("engtype_Compute") &&
                        !instance.Contains("engtype_VideoDecode") &&
                        !instance.Contains("engtype_VideoEncode"))
                        continue;

                    try
                    {
                        var counter = new PerformanceCounter("GPU Engine", "Utilization Percentage", instance, readOnly: true);
                        counter.NextValue();
                        counters.Add(counter);
                        sampledInstances++;
                    }
                    catch { }
                }

                if (sampledInstances == 0)
                {
                    foreach (var counter in counters)
                        counter.Dispose();

                    return 0f;
                }

                System.Threading.Thread.Sleep(500);

                foreach (var counter in counters)
                {
                    try
                    {
                        total += counter.NextValue();
                    }
                    catch { }
                    finally
                    {
                        counter.Dispose();
                    }
                }

                return Math.Max(0f, Math.Min(100f, total));
            }
            catch (Exception ex)
            {
                LastError = $"GPU usage: {ex.Message}";
                return 0f;
            }
        }

        /// <summary>
        /// GPU dedicated memory usage in bytes (0 when the counters are unavailable).
        /// </summary>
        public static long GetGpuMemoryUsage()
        {
            return BoundedReader.Read(GetGpuMemoryUsageCore, 0, 5000, "GPU memory");
        }

        private static long GetGpuMemoryUsageCore()
        {
            try
            {
                if (!CounterCategoryExists("GPU Adapter Memory"))
                    return 0;

                var category = new PerformanceCounterCategory("GPU Adapter Memory");
                var instanceNames = category.GetInstanceNames();
                if (instanceNames.Length == 0) return 0;

                long total = 0;
                var counters = new List<PerformanceCounter>();

                foreach (var instance in instanceNames)
                {
                    try
                    {
                        var counter = new PerformanceCounter("GPU Adapter Memory", "Dedicated Usage", instance, readOnly: true);
                        counter.NextValue();
                        counters.Add(counter);
                    }
                    catch { }
                }

                System.Threading.Thread.Sleep(300);

                foreach (var counter in counters)
                {
                    try
                    {
                        total += (long)counter.NextValue();
                    }
                    catch { }
                    finally
                    {
                        counter.Dispose();
                    }
                }

                return Math.Max(0, total);
            }
            catch (Exception ex)
            {
                LastError = $"GPU memory: {ex.Message}";
                return 0;
            }
        }

        /// <summary>
        /// GPU temperature when a sensor is exposed (usually only on dedicated GPUs), else null.
        /// </summary>
        public static float? GetGpuTemperature()
        {
            return null; // WMI does not expose this reliably; vendor APIs are out of scope.
        }

        #endregion

        #region Disk

        /// <summary>
        /// Total disk read throughput in bytes/second.
        /// </summary>
        public static long GetDiskReadBytesPerSecond()
        {
            return BoundedReader.Read(GetDiskReadBytesPerSecondCore, 0, 2500, "disk read speed");
        }

        private static long GetDiskReadBytesPerSecondCore()
        {
            return (long)Math.Max(0, SampleCounter("PhysicalDisk", "Disk Read Bytes/sec", "_Total", 400));
        }

        /// <summary>
        /// Total disk write throughput in bytes/second.
        /// </summary>
        public static long GetDiskWriteBytesPerSecond()
        {
            return BoundedReader.Read(GetDiskWriteBytesPerSecondCore, 0, 2500, "disk write speed");
        }

        private static long GetDiskWriteBytesPerSecondCore()
        {
            return (long)Math.Max(0, SampleCounter("PhysicalDisk", "Disk Write Bytes/sec", "_Total", 400));
        }

        /// <summary>
        /// Total disk busy time in percent.
        /// </summary>
        public static float GetDiskActivity()
        {
            return BoundedReader.Read(GetDiskActivityCore, 0f, 2500, "disk activity");
        }

        private static float GetDiskActivityCore()
        {
            return Math.Min(100f, Math.Max(0f,
                SampleCounter("PhysicalDisk", "% Disk Time", "_Total", 400)));
        }

        /// <summary>
        /// Average disk queue length (a good signal of an over-loaded disk).
        /// </summary>
        public static float GetDiskQueueLength()
        {
            return BoundedReader.Read(GetDiskQueueLengthCore, 0f, 2000, "disk queue");
        }

        private static float GetDiskQueueLengthCore()
        {
            return Math.Max(0f, SampleCounter("PhysicalDisk", "Avg. Disk Queue Length", "_Total", 0));
        }

        /// <summary>
        /// Average disk response time in milliseconds.
        /// </summary>
        public static float GetDiskResponseTimeMs()
        {
            return BoundedReader.Read(GetDiskResponseTimeMsCore, 0f, 2000, "disk response time");
        }

        private static float GetDiskResponseTimeMsCore()
        {
            var seconds = SampleCounter("PhysicalDisk", "Avg. Disk sec/Transfer", "_Total", 0);
            return Math.Max(0f, seconds * 1000f);
        }

        /// <summary>
        /// Logical drive information including capacity and where the OS is installed.
        /// </summary>
        public static List<DiskDriveInfo> GetDiskDriveInfo()
        {
            return BoundedReader.Read(GetDiskDriveInfoCore, new List<DiskDriveInfo>(), 6000, "disk drives");
        }

        private static List<DiskDriveInfo> GetDiskDriveInfoCore()
        {
            var result = new List<DiskDriveInfo>();

            try
            {
                var systemRoot = Path.GetPathRoot(Environment.SystemDirectory) ?? "C:\\";

                foreach (var drive in DriveInfo.GetDrives())
                {
                    try
                    {
                        if (!drive.IsReady) continue;

                        var info = new DiskDriveInfo
                        {
                            DriveLetter = drive.Name,
                            Label = drive.VolumeLabel,
                            FileSystem = drive.DriveFormat,
                            TotalSize = drive.TotalSize,
                            FreeSpace = drive.AvailableFreeSpace,
                            IsSystemDisk = string.Equals(drive.Name, systemRoot, StringComparison.OrdinalIgnoreCase)
                        };

                        info.Type = GetPhysicalMediaType(info.DriveLetter);
                        result.Add(info);
                    }
                    catch { }
                }
            }
            catch (Exception ex)
            {
                LastError = $"Disk information: {ex.Message}";
            }

            return result;
        }

        /// <summary>
        /// Determine whether a volume lives on an SSD/NVMe (affects which optimizations are safe -
        /// defragmentation must never be offered for flash storage).
        /// </summary>
        private static string GetPhysicalMediaType(string driveLetter)
        {
            try
            {
                var letter = driveLetter.TrimEnd('\\').TrimEnd(':');

                using (var partitionSearcher = new ManagementObjectSearcher(
                    $"ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='{letter}:'}} WHERE ResultClass=Win32_DiskPartition"))
                {
                    foreach (var partition in partitionSearcher.Get())
                    {
                        using (var diskSearcher = new ManagementObjectSearcher(
                            $"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{partition["DeviceID"]}'}} WHERE ResultClass=Win32_DiskDrive"))
                        {
                            foreach (var disk in diskSearcher.Get())
                            {
                                var model = disk["Model"]?.ToString() ?? string.Empty;
                                var mediaType = disk["MediaType"]?.ToString() ?? string.Empty;
                                var interfaceType = disk["InterfaceType"]?.ToString() ?? string.Empty;

                                var haystack = $"{model} {mediaType} {interfaceType}".ToLowerInvariant();

                                if (haystack.Contains("nvme")) return "NVMe SSD";
                                if (haystack.Contains("ssd") || haystack.Contains("solid state")) return "SSD";
                                if (interfaceType.Equals("SCSI", StringComparison.OrdinalIgnoreCase) && !haystack.Contains("hdd"))
                                    return "SSD";

                                return "HDD";
                            }
                        }
                    }
                }
            }
            catch { }

            return "Unknown";
        }

        /// <summary>
        /// Disk temperature when exposed by the storage driver, else null.
        /// </summary>
        public static float? GetDiskTemperature()
        {
            return BoundedReader.Read(GetDiskTemperatureCore, (float?)null, 4000, "disk temperature");
        }

        private static float? GetDiskTemperatureCore()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    @"root\WMI", "SELECT Temperature FROM MSStorageDriver_ATAPISmartData"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        var raw = obj["Temperature"] as byte[];
                        if (raw == null || raw.Length < 2) continue;

                        // The attribute blob layout is vendor specific; only trust explicit values.
                        var value = raw[0];
                        if (value > 0 && value < 100)
                            return value;
                    }
                }
            }
            catch { }

            return null;
        }

        #endregion

        #region Network

        /// <summary>
        /// Total network receive throughput in bytes/second.
        /// </summary>
        public static long GetNetworkDownloadSpeed()
        {
            return BoundedReader.Read(GetNetworkDownloadSpeedCore, 0, 2500, "network download");
        }

        private static long GetNetworkDownloadSpeedCore()
        {
            return (long)Math.Max(0, SampleCounter("Network Interface", "Bytes Received/sec", "_Total", 400));
        }

        /// <summary>
        /// Total network send throughput in bytes/second.
        /// </summary>
        public static long GetNetworkUploadSpeed()
        {
            return BoundedReader.Read(GetNetworkUploadSpeedCore, 0, 2500, "network upload");
        }

        private static long GetNetworkUploadSpeedCore()
        {
            return (long)Math.Max(0, SampleCounter("Network Interface", "Bytes Sent/sec", "_Total", 400));
        }

        /// <summary>
        /// Per-adapter throughput for physical adapters.
        /// </summary>
        public static List<NetworkAdapterCounterInfo> GetNetworkAdapterInfo()
        {
            return BoundedReader.Read(GetNetworkAdapterInfoCore, new List<NetworkAdapterCounterInfo>(), 6000, "network adapters");
        }

        private static List<NetworkAdapterCounterInfo> GetNetworkAdapterInfoCore()
        {
            var result = new List<NetworkAdapterCounterInfo>();

            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT Name, NetConnectionID, MACAddress, NetEnabled FROM Win32_NetworkAdapter " +
                    "WHERE PhysicalAdapter = TRUE"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        try
                        {
                            var netConnectionId = obj["NetConnectionID"]?.ToString();
                            if (string.IsNullOrWhiteSpace(netConnectionId)) continue;

                            var adapter = new NetworkAdapterCounterInfo
                            {
                                Name = netConnectionId!,
                                Description = obj["Name"]?.ToString() ?? string.Empty,
                                MacAddress = obj["MACAddress"]?.ToString() ?? string.Empty,
                                IsEnabled = Convert.ToBoolean(obj["NetEnabled"] ?? false)
                            };

                            adapter.DownloadSpeed = (long)Math.Max(0,
                                SampleCounter("Network Interface", "Bytes Received/sec", $"{netConnectionId}", 0));

                            adapter.UploadSpeed = (long)Math.Max(0,
                                SampleCounter("Network Interface", "Bytes Sent/sec", $"{netConnectionId}", 0));

                            result.Add(adapter);
                        }
                        catch { }
                    }
                }
            }
            catch (Exception ex)
            {
                LastError = $"Network adapters: {ex.Message}";
            }

            return result;
        }

        #endregion

        #region Helpers

        private static long SafeToLong(object? value)
        {
            if (value == null) return 0;

            try
            {
                return Convert.ToInt64(value);
            }
            catch
            {
                return 0;
            }
        }

        private static double SafeToDouble(object? value)
        {
            if (value == null) return 0;

            try
            {
                return Convert.ToDouble(value);
            }
            catch
            {
                return 0;
            }
        }

        #endregion

        #region Result types

        /// <summary>
        /// GPU information gathered from counters + WMI.
        /// </summary>
        public class GpuCounterInfo
        {
            public string Name { get; set; } = string.Empty;
            public string Manufacturer { get; set; } = string.Empty;
            public string Type { get; set; } = "Unknown";
            public string DriverVersion { get; set; } = string.Empty;
            public string PnpDeviceId { get; set; } = string.Empty;
            public long TotalMemory { get; set; }
            public long UsedMemory { get; set; }
            public float Usage { get; set; }
            public float? Temperature { get; set; }
        }

        /// <summary>
        /// Logical drive information.
        /// </summary>
        public class DiskDriveInfo
        {
            public string DriveLetter { get; set; } = string.Empty;
            public string Label { get; set; } = string.Empty;
            public string Type { get; set; } = "Unknown";
            public string FileSystem { get; set; } = string.Empty;
            public long TotalSize { get; set; }
            public long FreeSpace { get; set; }
            public long UsedSpace => Math.Max(0, TotalSize - FreeSpace);
            public bool IsSystemDisk { get; set; }

            public float UsagePercentage =>
                TotalSize <= 0 ? 0f : (float)Math.Max(0, Math.Min(100, UsedSpace / (double)TotalSize * 100));
        }

        /// <summary>
        /// Per-adapter network throughput.
        /// </summary>
        public class NetworkAdapterCounterInfo
        {
            public string Name { get; set; } = string.Empty;
            public string Description { get; set; } = string.Empty;
            public string MacAddress { get; set; } = string.Empty;
            public bool IsEnabled { get; set; }
            public long DownloadSpeed { get; set; }
            public long UploadSpeed { get; set; }
        }

        #endregion
    }
}
