using System;
using System.IO;
using System.Text;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.SmokeTests
{
    /// <summary>
    /// Real-machine validation harness.
    ///
    /// It drives the shipped Core assembly against the machine it is running on and reports PASS, FAIL or
    /// NOT VERIFIED for every check. A check that could not run is never reported as a pass.
    ///
    /// Usage:
    ///   AISystemOptimizer.SmokeTests [options]
    ///
    /// Options:
    ///   --monitor-seconds N   How long to watch for leaks afterwards (default 60, 0 to skip).
    ///   --output PATH         Where to write the Markdown report (default: smoke-test-results.md).
    ///   --quick               Skip the long-running checks (leak watch and the settle-delay test).
    ///   --help                Show this text.
    /// </summary>
    public static class Program
    {
        public static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;

            var monitorSeconds = 60;
            var output = Path.Combine(AppContext.BaseDirectory, "smoke-test-results.md");
            var quick = false;

            for (var i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--monitor-seconds":
                        if (i + 1 < args.Length && int.TryParse(args[++i], out var seconds))
                            monitorSeconds = seconds;
                        break;

                    case "--output":
                        if (i + 1 < args.Length)
                            output = args[++i];
                        break;

                    case "--quick":
                        quick = true;
                        break;

                    case "--help":
                    case "-h":
                        Console.WriteLine(HelpText);
                        return 0;
                }
            }

            if (quick)
                monitorSeconds = 0;

            PrintBanner();

            // The harness uses the shipped loader, so a configuration that cannot be read shows up here
            // exactly as it would for a user.
            var config = AppConfig.Load();

            // Log where a user would find the log, so the run leaves real evidence behind.
            config.LogFilePath = AISystemOptimizer.Core.Constants.AppConstants.LogDirectoryPath;

            var logger = LoggerFactory.GetLogger(config);

            var runner = new CheckRunner();

            try
            {
                runner.MachineLabel = $"{Environment.MachineName}, {Environment.OSVersion}, " +
                                      $"{System.Runtime.InteropServices.RuntimeInformation.OSArchitecture}";

                var checks = new SystemChecks(runner, config, logger);

                checks.RunEnvironmentChecks();

                // Everything after the operating-system check depends on being on Windows.
                if (runner.Results.Count > 0 && runner.Results[0].Status != CheckStatus.Pass)
                {
                    return Finish(runner, output, logger);
                }

                checks.RunScannerChecks();
                checks.RunIdentityChecks();
                checks.RunExecutorChecks();
                checks.RunCloseChecks();
                checks.RunProtectionChecks();
                checks.RunCounterChecks();
                checks.RunOptimisationChecks();
                checks.RunConfigurationChecks();
                checks.RunAiChecks();
                checks.RunSelfUsageChecks(monitorSeconds);
            }
            catch (Exception exception)
            {
                Console.WriteLine();
                Console.WriteLine($"The harness itself failed: {exception}");
            }

            return Finish(runner, output, logger);
        }

        private static int Finish(CheckRunner runner, string output, ILogger logger)
        {
            var (passed, failed, notVerified) = runner.WriteReport(output);

            Console.WriteLine();
            Console.WriteLine(new string('-', 78));
            Console.WriteLine($"  PASS {passed}   FAIL {failed}   NOT VERIFIED {notVerified}");
            Console.WriteLine($"  Report: {output}");
            Console.WriteLine(new string('-', 78));

            if (failed > 0)
            {
                Console.WriteLine();
                Console.WriteLine("  Checks that failed on this machine:");

                foreach (var result in runner.Results)
                {
                    if (result.Status == CheckStatus.Fail)
                        Console.WriteLine($"    {result.Id}  {result.Name}");
                }
            }

            if (notVerified > 0)
            {
                Console.WriteLine();
                Console.WriteLine("  Checks that could not be verified here (not passes, not failures):");

                foreach (var result in runner.Results)
                {
                    if (result.Status == CheckStatus.NotVerified)
                        Console.WriteLine($"    {result.Id}  {result.Name}");
                }
            }

            try { logger.Flush(); } catch { }

            // The exit code is the number of failures, so a script can gate on it.
            return Math.Min(failed, 100);
        }

        private static void PrintBanner()
        {
            Console.WriteLine();
            Console.WriteLine("AI System Optimizer - real-machine validation harness");
            Console.WriteLine("=====================================================");
            Console.WriteLine($"Machine : {Environment.MachineName}");
            Console.WriteLine($"OS      : {SystemInfoProbe.DescribeOs()}");
            Console.WriteLine($"Runtime : {System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription}");
            Console.WriteLine($"Started : {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            Console.WriteLine();
            Console.WriteLine("Every check reports PASS, FAIL or NOT VERIFIED. A check that did not run is never");
            Console.WriteLine("reported as a pass. Destructive paths are exercised only against processes and");
            Console.WriteLine("registry values this harness creates and removes itself.");
        }

        private const string HelpText =
            "AI System Optimizer - real-machine validation harness\n" +
            "\n" +
            "  AISystemOptimizer.SmokeTests [--monitor-seconds N] [--output PATH] [--quick]\n" +
            "\n" +
            "  --monitor-seconds N   Watch for leaks for N seconds afterwards (default 60, 0 to skip).\n" +
            "  --output PATH         Write the Markdown report to PATH.\n" +
            "  --quick               Skip the long-running checks.\n" +
            "\n" +
            "The exit code is the number of failed checks.";
    }
}
