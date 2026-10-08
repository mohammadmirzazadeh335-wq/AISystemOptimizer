using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace AISystemOptimizer.SmokeTests
{
    /// <summary>
    /// Result of one check.
    /// </summary>
    public enum CheckStatus
    {
        /// <summary>The check ran on this machine and met its expectation.</summary>
        Pass,

        /// <summary>The check ran and the expectation was not met.</summary>
        Fail,

        /// <summary>The check could not run here - a missing dependency, a missing sensor, or a
        /// capability this machine does not expose. This is not a pass and not a failure.</summary>
        NotVerified,

        /// <summary>Informational output with no pass/fail meaning.</summary>
        Info
    }

    /// <summary>
    /// A single unit of validation.
    /// </summary>
    public sealed class CheckResult
    {
        public string Id { get; init; } = string.Empty;
        public string Name { get; init; } = string.Empty;
        public CheckStatus Status { get; init; }
        public string Detail { get; init; } = string.Empty;

        /// <summary>Specification items this check addresses, for the traceability table.</summary>
        public string SpecReference { get; init; } = string.Empty;
    }

    /// <summary>
    /// Runs checks, records their outcome and prints a report.
    ///
    /// The governing rule of this harness is that a check which did not actually execute must never
    /// report success. Every helper below either produces a real observation or returns
    /// <see cref="CheckStatus.NotVerified"/>; there is no code path that turns "I could not tell" into
    /// "PASS".
    /// </summary>
    public sealed class CheckRunner
    {
        private readonly List<CheckResult> _results = new();
        private int _counter;

        public IReadOnlyList<CheckResult> Results => _results;

        public string MachineLabel { get; set; } = "unknown";

        /// <summary>
        /// Run a check whose body reports its own status.
        /// </summary>
        public CheckResult Run(string name, string specReference, Func<CheckResult> body)
        {
            _counter++;
            var id = $"C{_counter:D3}";

            CheckResult result;

            try
            {
                result = body();

                if (result == null)
                {
                    result = new CheckResult
                    {
                        Id = id,
                        Name = name,
                        Status = CheckStatus.NotVerified,
                        Detail = "The check produced no result.",
                        SpecReference = specReference
                    };
                }
                else
                {
                    result = new CheckResult
                    {
                        Id = id,
                        Name = string.IsNullOrEmpty(result.Name) ? name : result.Name,
                        Status = result.Status,
                        Detail = result.Detail,
                        SpecReference = specReference
                    };
                }
            }
            catch (Exception exception)
            {
                result = new CheckResult
                {
                    Id = id,
                    Name = name,
                    Status = CheckStatus.Fail,
                    Detail = $"The check threw {exception.GetType().Name}: {exception.Message}",
                    SpecReference = specReference
                };
            }

            _results.Add(result);
            Print(result);
            return result;
        }

        /// <summary>
        /// Run an asynchronous check.
        /// </summary>
        public CheckResult RunAsync(string name, string specReference, Func<Task<CheckResult>> body)
        {
            return Run(name, specReference, () => body().GetAwaiter().GetResult());
        }

        /// <summary>Record an informational line that is not a check.</summary>
        public void Note(string message)
        {
            Console.WriteLine($"    · {message}");
        }

        public CheckResult Pass(string id, string name, string detail, string spec = "") =>
            new() { Id = id, Name = name, Status = CheckStatus.Pass, Detail = detail, SpecReference = spec };

        public CheckResult Fail(string name, string detail, string spec = "") =>
            new() { Name = name, Status = CheckStatus.Fail, Detail = detail, SpecReference = spec };

        public CheckResult NotVerified(string name, string detail, string spec = "") =>
            new() { Name = name, Status = CheckStatus.NotVerified, Detail = detail, SpecReference = spec };

        private static void Print(CheckResult result)
        {
            var marker = result.Status switch
            {
                CheckStatus.Pass => "PASS",
                CheckStatus.Fail => "FAIL",
                CheckStatus.NotVerified => "N/V ",
                _ => "INFO"
            };

            Console.WriteLine($"  [{marker}] {result.Id} {result.Name}");

            if (!string.IsNullOrWhiteSpace(result.Detail))
                Console.WriteLine($"         {result.Detail}");
        }

        /// <summary>
        /// Render the report into a Markdown file and return the summary counts.
        /// </summary>
        public (int Passed, int Failed, int NotVerified) WriteReport(string path)
        {
            var passed = _results.Count(r => r.Status == CheckStatus.Pass);
            var failed = _results.Count(r => r.Status == CheckStatus.Fail);
            var unverified = _results.Count(r => r.Status == CheckStatus.NotVerified);

            var builder = new StringBuilder();

            builder.AppendLine("# Smoke-test results");
            builder.AppendLine();
            builder.AppendLine($"Machine: {MachineLabel}");
            builder.AppendLine($"Run at:  {DateTime.Now:yyyy-MM-dd HH:mm:ss zzz}");
            builder.AppendLine($"Runtime: {Environment.Version}, {System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription}");
            builder.AppendLine();
            builder.AppendLine($"**PASS {passed} · FAIL {failed} · NOT VERIFIED {unverified}**");
            builder.AppendLine();
            builder.AppendLine("| Status | ID | Check | Detail |");
            builder.AppendLine("|---|---|---|---|");

            foreach (var result in _results)
            {
                var status = result.Status switch
                {
                    CheckStatus.Pass => "PASS",
                    CheckStatus.Fail => "FAIL",
                    CheckStatus.NotVerified => "NOT VERIFIED",
                    _ => "INFO"
                };

                var detail = (result.Detail ?? string.Empty).Replace("|", "\\|").Replace("\n", " ");

                builder.AppendLine($"| {status} | {result.Id} | {result.Name} | {detail} |");
            }

            try
            {
                File.WriteAllText(path, builder.ToString());
            }
            catch
            {
                // Reporting must never be the thing that fails the run.
            }

            return (passed, failed, unverified);
        }

        /// <summary>
        /// Wait for a condition, polling, with a hard limit. Returns true when it became true.
        /// </summary>
        public static bool WaitUntil(Func<bool> condition, TimeSpan timeout, int pollMilliseconds = 100)
        {
            var deadline = DateTime.UtcNow + timeout;

            while (DateTime.UtcNow < deadline)
            {
                if (condition())
                    return true;

                Thread.Sleep(pollMilliseconds);
            }

            return condition();
        }
    }
}
