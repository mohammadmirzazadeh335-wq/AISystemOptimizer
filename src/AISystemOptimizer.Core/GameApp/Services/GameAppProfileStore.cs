using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// What happened when the store was read.
    /// </summary>
    public enum ProfileLoadOutcome
    {
        /// <summary>Every profile file was read.</summary>
        Loaded,

        /// <summary>Some files were skipped, and the reasons are recorded.</summary>
        LoadedWithProblems,

        /// <summary>The store is empty because no profile has been created yet.</summary>
        Empty,

        /// <summary>The directory could not be read at all.</summary>
        DirectoryUnreadable
    }

    /// <summary>
    /// Durable storage for <see cref="GameAppProfile"/>.
    ///
    /// One file per profile, named after the profile's identifier and never after the executable: a
    /// profile must survive the executable being renamed, moved or replaced, so that the health check can
    /// report what changed instead of the profile quietly disappearing.
    ///
    /// The storage discipline is the one the configuration loader already uses, because it is the one
    /// that has been tested against real failures: atomic write through a temporary file, a `.bak` that
    /// is never overwritten with something broken, tolerant parsing that isolates one bad file instead of
    /// discarding the set, quarantine with a written reason, and clamping of out-of-range values on load.
    ///
    /// Adding an application writes exactly one file and changes nothing else on the machine.
    /// </summary>
    public sealed class GameAppProfileStore
    {
        private const int MaxProfileFileBytes = 512 * 1024;

        private readonly ILogger _logger;
        private readonly string _directory;

        private readonly List<string> _loadProblems = new List<string>();

        public GameAppProfileStore(ILogger? logger = null, string? directory = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _directory = string.IsNullOrWhiteSpace(directory) ? DefaultDirectory : directory!;
        }

        /// <summary>Where profiles live by default: beside the rest of the application's data.</summary>
        public static string DefaultDirectory =>
            Path.Combine(AppConstants.AppDataPath, AppConstants.GameAppDirectoryName, "profiles");

        public string DirectoryPath => _directory;

        /// <summary>Problems encountered during the last load. Empty when everything was read.</summary>
        public IReadOnlyList<string> LoadProblems => _loadProblems;

        public ProfileLoadOutcome LastOutcome { get; private set; } = ProfileLoadOutcome.Empty;

        #region Paths

        /// <summary>
        /// The file name for a profile. The identifier is the only input, and it is a GUID, so the name
        /// cannot contain anything that could escape the directory.
        /// </summary>
        public static string FileNameFor(GameAppProfile profile) =>
            FileNameFor(profile?.ApplicationId ?? Guid.Empty);

        public static string FileNameFor(Guid applicationId) =>
            $"{applicationId:D}.json";

        public string FilePathFor(GameAppProfile profile) => FilePathFor(profile?.ApplicationId ?? Guid.Empty);

        public string FilePathFor(Guid applicationId) =>
            Path.Combine(_directory, FileNameFor(applicationId));

        #endregion

        #region Load

        /// <summary>
        /// Read every profile. A file that cannot be read does not stop the others; it is quarantined and
        /// reported.
        /// </summary>
        public List<GameAppProfile> LoadAll()
        {
            var profiles = new List<GameAppProfile>();

            _loadProblems.Clear();

            string[] files;

            try
            {
                if (!Directory.Exists(_directory))
                {
                    LastOutcome = ProfileLoadOutcome.Empty;
                    return profiles;
                }

                files = Directory.GetFiles(_directory, "*.json");
            }
            catch (Exception exception)
            {
                _loadProblems.Add($"The profile directory could not be read: {exception.Message}");
                LastOutcome = ProfileLoadOutcome.DirectoryUnreadable;
                _logger.Warning("GameAppProfileStore", _loadProblems[0], null, exception);
                return profiles;
            }

            if (files.Length == 0)
            {
                LastOutcome = ProfileLoadOutcome.Empty;
                return profiles;
            }

            foreach (var file in files.OrderBy(f => f, StringComparer.OrdinalIgnoreCase))
            {
                var profile = LoadOne(file);

                if (profile != null)
                    profiles.Add(profile);
            }

            LastOutcome = _loadProblems.Count == 0
                ? ProfileLoadOutcome.Loaded
                : ProfileLoadOutcome.LoadedWithProblems;

            return profiles;
        }

        /// <summary>
        /// Read one profile file, recovering from the backup when the file itself is damaged.
        /// </summary>
        public GameAppProfile? LoadOne(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath))
                return null;

            var fromFile = TryRead(filePath, out var reason);

            if (fromFile != null)
            {
                ApplyLoadAdjustments(fromFile, Path.GetFileName(filePath));
                return fromFile;
            }

            // The file is unusable. Try the backup before giving up.
            var backupPath = AppConfig.BackupPathFor(filePath);

            if (File.Exists(backupPath))
            {
                var fromBackup = TryRead(backupPath, out _);

                if (fromBackup != null)
                {
                    _loadProblems.Add(
                        $"{Path.GetFileName(filePath)} could not be read ({reason}); the backup was used instead.");

                    _logger.Warning("GameAppProfileStore",
                        $"Profile '{Path.GetFileName(filePath)}' was recovered from its backup.");

                    Quarantine(filePath, reason);
                    ApplyLoadAdjustments(fromBackup, Path.GetFileName(filePath));
                    return fromBackup;
                }
            }

            _loadProblems.Add($"{Path.GetFileName(filePath)} could not be read and has no usable backup: {reason}");

            Quarantine(filePath, reason);

            return null;
        }

        private GameAppProfile? TryRead(string filePath, out string reason)
        {
            reason = string.Empty;

            try
            {
                var info = new FileInfo(filePath);

                if (!info.Exists)
                {
                    reason = "file not found";
                    return null;
                }

                if (info.Length > MaxProfileFileBytes)
                {
                    reason = $"file is {info.Length} bytes, above the {MaxProfileFileBytes} byte limit";
                    return null;
                }

                if (info.Length == 0)
                {
                    reason = "file is empty";
                    return null;
                }

                var json = File.ReadAllText(filePath);

                var profile = JsonSerializer.Deserialize<GameAppProfile>(json, GameAppProfileJson.Options);

                if (profile == null)
                {
                    reason = "the file produced no object";
                    return null;
                }

                if (profile.ApplicationId == Guid.Empty)
                {
                    // A profile without an identifier cannot be referred to, matched or restored.
                    reason = "the profile has no identifier";
                    return null;
                }

                return profile;
            }
            catch (JsonException exception)
            {
                reason = $"the file is not valid JSON ({exception.Message})";
                return null;
            }
            catch (UnauthorizedAccessException)
            {
                reason = "permission denied";
                return null;
            }
            catch (IOException exception)
            {
                reason = $"the file could not be read ({exception.Message})";
                return null;
            }
        }

        private void ApplyLoadAdjustments(GameAppProfile profile, string fileName)
        {
            try
            {
                var adjustments = profile.NormalizeToSupportedRanges();

                if (adjustments.Count > 0)
                {
                    _loadProblems.Add(
                        $"{fileName}: {adjustments.Count} value(s) were outside their supported range and were " +
                        $"corrected ({string.Join("; ", adjustments)})");

                    _logger.Warning("GameAppProfileStore",
                        $"Profile '{fileName}' was corrected on load: {string.Join("; ", adjustments)}");
                }

                profile.TrimHistory(maxBenchmarks: 200, maxSessions: 200);
            }
            catch (Exception exception)
            {
                _loadProblems.Add($"{fileName}: the profile could not be normalised ({exception.Message})");
            }
        }

        #endregion

        #region Save

        /// <summary>
        /// Write a profile atomically.
        ///
        /// The existing good file is copied to `.bak` before the new content replaces it, so a crash
        /// during the write leaves either the old file or a recoverable backup - never a truncated file
        /// with no way back.
        /// </summary>
        public bool Save(GameAppProfile profile)
        {
            if (profile == null || profile.ApplicationId == Guid.Empty)
                return false;

            try
            {
                Directory.CreateDirectory(_directory);

                profile.UpdatedAtUtc = DateTime.UtcNow;
                profile.SchemaVersion = GameAppProfile.CurrentSchemaVersion;
                profile.TrimHistory(maxBenchmarks: 200, maxSessions: 200);

                var target = FilePathFor(profile);
                var temporary = target + ".tmp";

                var json = JsonSerializer.Serialize(profile, GameAppProfileJson.Options);

                File.WriteAllText(temporary, json);

                if (File.Exists(target))
                {
                    var backup = AppConfig.BackupPathFor(target);

                    try
                    {
                        File.Copy(target, backup, overwrite: true);
                    }
                    catch
                    {
                        // A missing backup is not a reason to refuse the save; the existing file is still
                        // valid until the move below replaces it.
                    }

                    File.Delete(target);
                }

                File.Move(temporary, target);

                return File.Exists(target);
            }
            catch (Exception exception)
            {
                _logger.Error("GameAppProfileStore",
                    $"Profile '{profile.ResolveDisplayName()}' could not be saved", null, exception);

                return false;
            }
        }

        /// <summary>
        /// Remove a profile and its backup. Used when the user removes an application from the list.
        /// Nothing else on the machine is touched.
        /// </summary>
        public bool Delete(GameAppProfile profile)
        {
            if (profile == null || profile.ApplicationId == Guid.Empty)
                return false;

            try
            {
                var target = FilePathFor(profile);

                if (File.Exists(target))
                    File.Delete(target);

                var backup = AppConfig.BackupPathFor(target);

                if (File.Exists(backup))
                    File.Delete(backup);

                var quarantine = target + ".invalid";

                if (File.Exists(quarantine))
                    File.Delete(quarantine);

                return !File.Exists(target);
            }
            catch (Exception exception)
            {
                _logger.Error("GameAppProfileStore", "Profile could not be removed", null, exception);
                return false;
            }
        }

        /// <summary>
        /// Move an unreadable file aside with a written reason, so the user can see what happened and
        /// nothing is silently discarded.
        /// </summary>
        private void Quarantine(string filePath, string reason)
        {
            try
            {
                var target = filePath + ".invalid";

                if (File.Exists(target))
                    File.Delete(target);

                File.Move(filePath, target);

                File.WriteAllText(
                    target + ".reason.txt",
                    $"Quarantined {DateTime.Now:yyyy-MM-dd HH:mm:ss} by {AppConstants.AppName}.{Environment.NewLine}" +
                    $"Reason: {reason}{Environment.NewLine}");

                _logger.Warning("GameAppProfileStore",
                    $"Profile file '{Path.GetFileName(filePath)}' was quarantined: {reason}");
            }
            catch (Exception exception)
            {
                _logger.Warning("GameAppProfileStore",
                    $"A damaged profile file could not be quarantined: {exception.Message}");
            }
        }

        #endregion

        #region Queries

        /// <summary>
        /// Find the profile that already describes an executable, matched on canonical path first and on
        /// content hash second. Two different programs with the same file name never collide.
        /// </summary>
        public GameAppProfile? FindByExecutable(
            IEnumerable<GameAppProfile> profiles,
            string executablePath,
            string? sha256 = null)
        {
            if (profiles == null || string.IsNullOrWhiteSpace(executablePath))
                return null;

            var byPath = profiles.FirstOrDefault(p =>
                ExecutablePathValidator.RefersToSameFile(p?.ExecutablePath, executablePath));

            if (byPath != null)
                return byPath;

            if (!string.IsNullOrWhiteSpace(sha256))
            {
                return profiles.FirstOrDefault(p =>
                    p != null &&
                    !string.IsNullOrWhiteSpace(p.Identity?.Sha256) &&
                    p.Identity!.Sha256.Equals(sha256, StringComparison.OrdinalIgnoreCase));
            }

            return null;
        }

        /// <summary>
        /// True when this executable is already profiled. Used to refuse a duplicate before the user has
        /// finished creating one.
        /// </summary>
        public bool IsDuplicate(
            IEnumerable<GameAppProfile> profiles,
            string executablePath,
            string? sha256 = null) =>
            FindByExecutable(profiles, executablePath, sha256) != null;

        #endregion
    }
}
