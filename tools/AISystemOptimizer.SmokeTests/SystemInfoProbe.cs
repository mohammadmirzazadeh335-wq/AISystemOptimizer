using System;
using System.Management;
using System.Text;
using Microsoft.Win32;

namespace AISystemOptimizer.SmokeTests
{
    /// <summary>
    /// Machine facts read independently of the application, so that what the application reports can be
    /// compared against a second source.
    /// </summary>
    public static class SystemInfoProbe
    {
        /// <summary>
        /// Edition, version and build of Windows, read from the registry where Windows actually records
        /// them. `wmic` is gone from Windows 11 24H2, so WMI-through-wmic is not an option.
        /// </summary>
        public static string DescribeOs()
        {
            var builder = new StringBuilder();

            try
            {
                using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion");

                if (key != null)
                {
                    builder.Append(Convert.ToString(key.GetValue("ProductName")));
                    builder.Append(" · version ");
                    builder.Append(Convert.ToString(key.GetValue("DisplayVersion") ?? key.GetValue("ReleaseId")));
                    builder.Append(" · build ");
                    builder.Append(Convert.ToString(key.GetValue("CurrentBuildNumber")));

                    var ubr = key.GetValue("UBR");

                    if (ubr != null)
                        builder.Append('.').Append(Convert.ToString(ubr));

                    builder.Append(Convert.ToString(key.GetValue("EditionID") != null ? " · " : string.Empty));
                    builder.Append(Convert.ToString(key.GetValue("EditionID")));
                }
            }
            catch (Exception exception)
            {
                builder.Append($"(registry read failed: {exception.GetType().Name})");
            }

            builder.Append($" · Environment.OSVersion {Environment.OSVersion.Version}");
            builder.Append($" · 64-bit OS {Environment.Is64BitOperatingSystem}, 64-bit process {Environment.Is64BitProcess}");

            return builder.ToString();
        }

        /// <summary>
        /// Total physical memory according to WMI. Returns false when WMI is unavailable, which is not
        /// an error - the caller reports not-verified rather than comparing against nothing.
        /// </summary>
        public static bool TryReadTotalRamFromWmi(out long bytes)
        {
            bytes = 0;

            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT TotalPhysicalMemory FROM Win32_ComputerSystem");

                foreach (var item in searcher.Get())
                {
                    bytes = Convert.ToInt64(Convert.ToString(item["TotalPhysicalMemory"]));
                    break;
                }

                return bytes > 0;
            }
            catch
            {
                return false;
            }
        }
    }
}
