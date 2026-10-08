using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// A durable record of a start-up entry that this application removed.
    ///
    /// A start-up entry is a user-visible setting. Deleting the registry value destroys it, so the
    /// exact value has to be written down somewhere that survives the process - otherwise "reversible"
    /// only holds until the optimizer is closed.
    /// </summary>
    public sealed class StartupItemBackupRecord
    {
        /// <summary>Display name of the entry (the registry value name, or the file name).</summary>
        public string Name { get; set; } = string.Empty;

        /// <summary>Where the entry came from, e.g. "Registry (HKCU)" or "Startup Folder".</summary>
        public string Source { get; set; } = string.Empty;

        /// <summary>Registry subkey the value lived in, when applicable.</summary>
        public string RegistryPath { get; set; } = string.Empty;

        /// <summary>Path recorded for the entry at scan time.</summary>
        public string Path { get; set; } = string.Empty;

        /// <summary>Arguments recorded for the entry at scan time.</summary>
        public string Arguments { get; set; } = string.Empty;

        /// <summary>
        /// The exact value that was removed. This is what makes the change reversible; it is written
        /// before the removal and never inferred afterwards.
        /// </summary>
        public string OriginalValue { get; set; } = string.Empty;

        public DateTime RemovedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>Component that made the change. Never a user name, which would be personal data.</summary>
        public string RemovedBy { get; set; } = "AI System Optimizer";

        /// <summary>
        /// Rebuild a start-up item that can be handed to the restore path.
        /// </summary>
        public SystemInfo.StartupItem ToStartupItem()
        {
            return new SystemInfo.StartupItem
            {
                Name = Name,
                Source = Source,
                RegistryPath = RegistryPath,
                Path = string.IsNullOrWhiteSpace(Path) ? OriginalValue : Path,
                Arguments = Arguments,
                IsEnabled = false,
                IsWindowsItem = false,
                RiskLevel = RiskLevel.Low,
                Recommendation = "Disabled by AI System Optimizer; it can be re-enabled from the Start-up view."
            };
        }
    }

    /// <summary>
    /// File-backed store for <see cref="StartupItemBackupRecord"/>.
    ///
    /// One JSON file per removed entry, written atomically, under the application's backup directory.
    /// Everything here is defensive: a corrupt or unreadable record must never stop the application
    /// from starting or from listing the other records.
    /// </summary>
    public static class StartupItemBackupStore
    {
        private static readonly object SyncRoot = new object();

        private static readonly JsonSerializerOptions SerializerOptions = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNameCaseInsensitive = true
        };

        /// <summary>Directory holding the records.</summary>
        public static string DirectoryPath =>
            System.IO.Path.Combine(AppConstants.BackupDirectoryPath, "StartupItems");

        /// <summary>
        /// Turn an arbitrary entry name into a file name that cannot escape the backup directory.
        ///
        /// Every character that is not plainly safe is replaced, so a name such as
        /// "..\..\Windows\System32\evil" cannot address anything outside the directory. A short hash of
        /// the original name is appended so that two different names can never map to the same file.
        /// </summary>
        public static string FileNameFor(string name)
        {
            var source = name ?? string.Empty;

            var safe = new char[source.Length];
            var length = 0;

            foreach (var character in source)
            {
                var allowed = (character >= 'a' && character <= 'z') ||
                              (character >= 'A' && character <= 'Z') ||
                              (character >= '0' && character <= '9') ||
                              character == '-' || character == '_';

                if (allowed)
                {
                    safe[length++] = character;
                }
                else
                {
                    safe[length++] = '_';
                }

                if (length >= 48)
                    break;
            }

            var stem = new string(safe, 0, length).Trim('_');

            if (stem.Length == 0)
                stem = "item";

            return $"{stem}_{StableHash(source):x8}.json";
        }

        /// <summary>Full path of the record for an entry name.</summary>
        public static string FilePathFor(string name) =>
            System.IO.Path.Combine(DirectoryPath, FileNameFor(name));

        /// <summary>
        /// Write the record for a removed entry.
        ///
        /// Returns false when the record could not be written - the caller must treat that as a refusal
        /// to remove the entry, because removing it without a record is not reversible.
        /// </summary>
        public static bool Save(SystemInfo.StartupItem item, string removedValue)
        {
            if (item == null || string.IsNullOrWhiteSpace(item.Name))
                return false;

            try
            {
                lock (SyncRoot)
                {
                    System.IO.Directory.CreateDirectory(DirectoryPath);

                    var record = new StartupItemBackupRecord
                    {
                        Name = item.Name,
                        Source = item.Source ?? string.Empty,
                        RegistryPath = item.RegistryPath ?? string.Empty,
                        Path = item.Path ?? string.Empty,
                        Arguments = item.Arguments ?? string.Empty,
                        OriginalValue = removedValue ?? string.Empty,
                        RemovedAtUtc = DateTime.UtcNow
                    };

                    var json = JsonSerializer.Serialize(record, SerializerOptions);

                    var target = FilePathFor(item.Name);
                    var temporary = target + ".tmp";

                    // Write through a temporary file so that an interrupted write cannot leave a
                    // half-written record where a valid one used to be.
                    File.WriteAllText(temporary, json);

                    if (File.Exists(target))
                        File.Delete(target);

                    File.Move(temporary, target);

                    return File.Exists(target);
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Read the record for an entry name. Returns false when there is no readable record.
        /// </summary>
        public static bool TryLoad(string name, out StartupItemBackupRecord record)
        {
            record = null;

            if (string.IsNullOrWhiteSpace(name))
                return false;

            try
            {
                var path = FilePathFor(name);

                if (!File.Exists(path))
                    return false;

                var json = File.ReadAllText(path);

                var parsed = JsonSerializer.Deserialize<StartupItemBackupRecord>(json, SerializerOptions);

                if (parsed == null || string.IsNullOrWhiteSpace(parsed.Name))
                    return false;

                record = parsed;
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Read every record. A corrupt file is skipped rather than thrown, so one bad file cannot hide
        /// the other disabled entries from the user.
        /// </summary>
        public static List<StartupItemBackupRecord> LoadAll()
        {
            var records = new List<StartupItemBackupRecord>();

            try
            {
                lock (SyncRoot)
                {
                    if (!System.IO.Directory.Exists(DirectoryPath))
                        return records;

                    foreach (var file in System.IO.Directory.GetFiles(DirectoryPath, "*.json"))
                    {
                        try
                        {
                            var parsed = JsonSerializer.Deserialize<StartupItemBackupRecord>(
                                File.ReadAllText(file),
                                SerializerOptions);

                            if (parsed != null && !string.IsNullOrWhiteSpace(parsed.Name))
                                records.Add(parsed);
                        }
                        catch
                        {
                            // Skip this record; the remaining ones are still listed.
                        }
                    }
                }
            }
            catch
            {
                // An unreadable backup directory is reported by the absence of records.
            }

            return records.OrderBy(r => r.Name, StringComparer.OrdinalIgnoreCase).ToList();
        }

        /// <summary>
        /// Remove the record for an entry, once the entry has been restored.
        /// </summary>
        public static bool Delete(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return false;

            try
            {
                lock (SyncRoot)
                {
                    var path = FilePathFor(name);

                    if (File.Exists(path))
                        File.Delete(path);

                    return !File.Exists(path);
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// FNV-1a over the original name. Deterministic across runs and processes (unlike
        /// <see cref="string.GetHashCode()"/>, which is randomised per process and would make the file
        /// name - and therefore the ability to restore - differ between sessions).
        /// </summary>
        private static uint StableHash(string value)
        {
            unchecked
            {
                var hash = 2166136261u;

                foreach (var character in value ?? string.Empty)
                {
                    hash ^= character;
                    hash *= 16777619u;
                }

                return hash;
            }
        }
    }
}
