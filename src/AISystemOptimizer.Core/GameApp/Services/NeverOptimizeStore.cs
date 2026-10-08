using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// One entry in the user's "Never optimize" list.
    ///
    /// The list can only ever make optimisation *more* restrictive. It is checked after - never instead
    /// of - the hard system protections: a critical process, a security component or a service with
    /// dependents is refused whether or not it appears here, and a user cannot add an allow-entry that
    /// re-enables any of them.
    /// </summary>
    public sealed class NeverOptimizeEntry
    {
        public NeverOptimizeKind Kind { get; set; } = NeverOptimizeKind.ProcessName;

        /// <summary>Process name, canonical path, publisher string or hash, depending on <see cref="Kind"/>.</summary>
        public string Value { get; set; } = string.Empty;

        public string Reason { get; set; } = string.Empty;

        public DateTime AddedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>Always false for an entry the user added; present so the file explains its own rule.</summary>
        public bool CanOverrideSystemProtection { get; set; }

        public bool Matches(string? processName, string? path, string? publisher, string? sha256)
        {
            if (string.IsNullOrWhiteSpace(Value))
                return false;

            var target = Value.Trim().Trim('"');

            switch (Kind)
            {
                case NeverOptimizeKind.ProcessName:
                    return ExecutablePathValidator.NormaliseExecutableName(processName)
                        .Equals(ExecutablePathValidator.NormaliseExecutableName(target), StringComparison.OrdinalIgnoreCase);

                case NeverOptimizeKind.ExecutablePath:
                    return !string.IsNullOrWhiteSpace(path) &&
                           ExecutablePathValidator.RefersToSameFile(path, target);

                case NeverOptimizeKind.Publisher:
                    return !string.IsNullOrWhiteSpace(publisher) &&
                           publisher.IndexOf(target, StringComparison.OrdinalIgnoreCase) >= 0;

                case NeverOptimizeKind.FileHash:
                    return !string.IsNullOrWhiteSpace(sha256) &&
                           sha256.Equals(target, StringComparison.OrdinalIgnoreCase);

                default:
                    return false;
            }
        }
    }

    /// <summary>
    /// The "Never optimize" list, stored beside the profiles.
    ///
    /// A missing file means an empty list, not an error. A damaged file is quarantined rather than
    /// silently emptied, because silently losing this list would remove a protection the user chose.
    /// </summary>
    public sealed class NeverOptimizeStore
    {
        private const int MaxFileBytes = 512 * 1024;

        private readonly ILogger _logger;
        private readonly string _filePath;

        public NeverOptimizeStore(ILogger? logger = null, string? filePath = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _filePath = string.IsNullOrWhiteSpace(filePath) ? Constants.AppConstants.GameAppNeverOptimizeFilePath : filePath!;
        }

        public string FilePath => _filePath;

        public IReadOnlyList<string> LoadProblems { get; private set; } = Array.Empty<string>();

        public List<NeverOptimizeEntry> Load()
        {
            var problems = new List<string>();
            var entries = new List<NeverOptimizeEntry>();

            try
            {
                if (!File.Exists(_filePath))
                {
                    LoadProblems = problems;
                    return entries;
                }

                var info = new FileInfo(_filePath);

                if (info.Length == 0)
                {
                    LoadProblems = problems;
                    return entries;
                }

                if (info.Length > MaxFileBytes)
                {
                    problems.Add($"The never-optimise file is {info.Length} bytes, above the {MaxFileBytes} byte limit.");
                    LoadProblems = problems;
                    return entries;
                }

                var parsed = System.Text.Json.JsonSerializer.Deserialize<NeverOptimizeFile>(
                    File.ReadAllText(_filePath),
                    GameAppProfileJson.Options);

                if (parsed?.Entries != null)
                {
                    // The flag exists so the file documents its own rule; it is never honoured.
                    foreach (var entry in parsed.Entries.Where(e => e != null && !string.IsNullOrWhiteSpace(e.Value)))
                    {
                        if (entry.CanOverrideSystemProtection)
                        {
                            entry.CanOverrideSystemProtection = false;
                            problems.Add(
                                $"Entry '{entry.Value}' claimed it could override a system protection. That is " +
                                "not possible; the flag was cleared.");
                        }

                        entries.Add(entry);
                    }
                }
            }
            catch (Exception exception)
            {
                problems.Add($"The never-optimise list could not be read: {exception.Message}");
                Quarantine(exception.Message);
                _logger.Warning("NeverOptimizeStore", problems[^1]);
            }

            LoadProblems = problems;
            return entries;
        }

        public bool Save(IEnumerable<NeverOptimizeEntry> entries)
        {
            try
            {
                var directory = Path.GetDirectoryName(_filePath);

                if (!string.IsNullOrEmpty(directory))
                    Directory.CreateDirectory(directory);

                var file = new NeverOptimizeFile
                {
                    Explanation =
                        "Entries here make optimisation more restrictive. They are checked after the built-in " +
                        "system protections, never instead of them, and cannot re-enable anything those refuse.",
                    Entries = (entries ?? Enumerable.Empty<NeverOptimizeEntry>())
                        .Where(e => e != null && !string.IsNullOrWhiteSpace(e.Value))
                        .ToList()
                };

                var temporary = _filePath + ".tmp";

                File.WriteAllText(temporary, System.Text.Json.JsonSerializer.Serialize(file, GameAppProfileJson.Options));

                if (File.Exists(_filePath))
                {
                    var backup = AppConfig.BackupPathFor(_filePath);

                    try { File.Copy(_filePath, backup, overwrite: true); } catch { }

                    File.Delete(_filePath);
                }

                File.Move(temporary, _filePath);

                return File.Exists(_filePath);
            }
            catch (Exception exception)
            {
                _logger.Error("NeverOptimizeStore", "The never-optimise list could not be saved", null, exception);
                return false;
            }
        }

        private void Quarantine(string reason)
        {
            try
            {
                var target = _filePath + ".invalid";

                if (File.Exists(target)) File.Delete(target);

                File.Move(_filePath, target);

                File.WriteAllText(target + ".reason.txt", $"Reason: {reason}{Environment.NewLine}");
            }
            catch
            {
                // Nothing further can be done with an unreadable file.
            }
        }

        private sealed class NeverOptimizeFile
        {
            public string Explanation { get; set; } = string.Empty;
            public List<NeverOptimizeEntry> Entries { get; set; } = new List<NeverOptimizeEntry>();
        }
    }
}
