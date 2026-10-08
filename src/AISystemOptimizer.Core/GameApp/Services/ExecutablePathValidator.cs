using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// Outcome of validating a path the user selected.
    /// </summary>
    public sealed class PathValidationResult
    {
        public bool IsValid { get; init; }

        /// <summary>Canonical absolute path. Empty when the path was rejected.</summary>
        public string CanonicalPath { get; init; } = string.Empty;

        public string FileName { get; init; } = string.Empty;

        /// <summary>True when the path is on a network share rather than a local volume.</summary>
        public bool IsNetworkPath { get; init; }

        /// <summary>Why it was rejected, in words the user can act on. Empty when valid.</summary>
        public string ErrorMessage { get; init; } = string.Empty;

        /// <summary>Things that are not rejections but should be shown (a redirected parent directory, a share).</summary>
        public List<string> Notes { get; init; } = new List<string>();

        public static PathValidationResult Reject(string reason) =>
            new PathValidationResult { IsValid = false, ErrorMessage = reason };
    }

    /// <summary>
    /// Validates an executable path before anything else touches it.
    ///
    /// A path that arrives from a file picker is still untrusted input: it can be a device path, a
    /// reparse point that is re-pointed after the profile is created, a path with characters that mean
    /// something to a shell, or a file that is not what its extension claims. None of that reaches the
    /// rest of the application unless it passes here first.
    ///
    /// This validator is a pure function of (path, options). It performs file-system metadata reads and
    /// never opens, executes or modifies the target.
    /// </summary>
    public static class ExecutablePathValidator
    {
        /// <summary>
        /// Conservative ceiling. Windows can be told to accept longer paths with the <c>\\?\</c> prefix,
        /// which this application deliberately refuses, so the practical limit applies.
        /// </summary>
        public const int MaximumPathLength = 520;

        public const string RequiredExtension = ".exe";

        /// <summary>
        /// Validate a path.
        /// </summary>
        /// <param name="path">The path as supplied.</param>
        /// <param name="requireExists">
        /// True when the file must exist right now (adding an application). False when the caller is
        /// checking a path that is expected to be present but whose absence is reported as health, not
        /// as a rejection.
        /// </param>
        /// <param name="rejectReparsePoints">
        /// True by default. A symbolic link or junction can be re-pointed at a different program after
        /// the profile is created, which would make a previously verified identity meaningless.
        /// </param>
        public static PathValidationResult Validate(
            string? path,
            bool requireExists = true,
            bool rejectReparsePoints = true)
        {
            if (string.IsNullOrWhiteSpace(path))
                return PathValidationResult.Reject("No file was selected.");

            var supplied = path.Trim().Trim('"');

            if (supplied.Length == 0)
                return PathValidationResult.Reject("No file was selected.");

            if (supplied.Length > MaximumPathLength)
            {
                return PathValidationResult.Reject(
                    $"The path is {supplied.Length} characters long; {MaximumPathLength} is the limit this " +
                    "application accepts. Move the application to a shorter path.");
            }

            foreach (var character in supplied)
            {
                if (character < ' ')
                {
                    return PathValidationResult.Reject(
                        "The path contains control characters, which is not a path this application will use.");
                }
            }

            // Device paths bypass normal path parsing and normal security checks. Refuse them outright:
            // nothing a user browses to in a file dialog legitimately starts this way.
            if (supplied.StartsWith(@"\\?\", StringComparison.Ordinal) ||
                supplied.StartsWith(@"\\.\", StringComparison.Ordinal) ||
                supplied.StartsWith(@"\??\", StringComparison.Ordinal))
            {
                return PathValidationResult.Reject(
                    "Device paths (\\\\?\\, \\\\.\\) are not accepted.");
            }

            if (!IsRooted(supplied))
                return PathValidationResult.Reject("The path is not absolute.");

            // "C:Game.exe" is rooted but not absolute: it resolves against the current directory of drive
            // C, so it names a different file depending on where this application happens to be running.
            if (IsDriveRelative(supplied))
            {
                return PathValidationResult.Reject(
                    "The path is relative to a drive's current directory (for example 'C:Game.exe') and " +
                    "would resolve differently depending on where the application is started. Use the full " +
                    "path instead.");
            }

            // Every directory or file name component must be a legal Windows name. Checking component by
            // component is what catches a name that came from somewhere other than the file system.
            var segments = supplied.Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries);

            // An explicit set rather than Path.GetInvalidFileNameChars(): that method returns a different
            // list on a non-Windows host, and this validator must reject exactly the same shapes wherever
            // it runs. ':' is handled by the drive special case below.
            var invalidChars = new[] { '<', '>', ':', '"', '|', '?', '*', '\0' };

            foreach (var segment in segments)
            {
                // The drive or UNC host component is a special case ("C:", "server").
                if (segment.Length == 2 && segment[1] == ':')
                    continue;

                if (segment.IndexOfAny(invalidChars) >= 0)
                {
                    return PathValidationResult.Reject(
                        $"The path contains a character that is not valid in a Windows file name: '{segment}'.");
                }
            }

            string canonical;

            try
            {
                canonical = Path.GetFullPath(supplied);
            }
            catch (Exception exception)
            {
                return PathValidationResult.Reject($"The path could not be resolved: {exception.Message}");
            }

            if (!canonical.EndsWith(RequiredExtension, StringComparison.OrdinalIgnoreCase))
            {
                return PathValidationResult.Reject(
                    $"Only {RequiredExtension} files can be added. '{Path.GetFileName(canonical)}' is not one.");
            }

            var notes = new List<string>();
            var isNetworkPath = canonical.StartsWith(@"\\", StringComparison.Ordinal);

            if (isNetworkPath)
            {
                notes.Add(
                    "This executable is on a network share. It is accepted, but the profile's identity check " +
                    "will fail if the share is unavailable.");
            }

            if (requireExists && !File.Exists(canonical))
            {
                return File.Exists(canonical)
                    ? PathValidationResult.Reject("The file exists but could not be opened.")
                    : PathValidationResult.Reject($"No file exists at '{canonical}'.");
            }

            if (Directory.Exists(canonical))
                return PathValidationResult.Reject("The path is a directory, not a file.");

            if (File.Exists(canonical))
            {
                try
                {
                    var attributes = File.GetAttributes(canonical);

                    if (rejectReparsePoints && (attributes & FileAttributes.ReparsePoint) != 0)
                    {
                        return PathValidationResult.Reject(
                            "The selected file is a symbolic link or junction. A link can be re-pointed at a " +
                            "different program after the profile is created, so it cannot be profiled safely. " +
                            "Select the real executable instead.");
                    }

                    var directory = Path.GetDirectoryName(canonical);

                    if (!string.IsNullOrEmpty(directory) && Directory.Exists(directory))
                    {
                        var directoryAttributes = File.GetAttributes(directory);

                        if ((directoryAttributes & FileAttributes.ReparsePoint) != 0)
                        {
                            notes.Add(
                                "The containing directory is a link or junction (common for redirected game " +
                                "libraries). The file itself is not, so the profile is valid, but a future " +
                                "re-point would change what the path resolves to.");
                        }
                    }
                }
                catch (UnauthorizedAccessException)
                {
                    if (requireExists)
                    {
                        return PathValidationResult.Reject(
                            "The file exists but this process is not allowed to read its information. " +
                            "Try running the optimiser with different permissions.");
                    }

                    notes.Add("The file exists but its attributes could not be read (permission denied).");
                }
                catch (IOException exception)
                {
                    notes.Add($"The file's attributes could not be read: {exception.Message}");
                }
            }

            return new PathValidationResult
            {
                IsValid = true,
                CanonicalPath = canonical,
                FileName = Path.GetFileName(canonical),
                IsNetworkPath = isNetworkPath,
                Notes = notes
            };
        }

        /// <summary>
        /// True when the path resolves to the same file as the canonical path the caller already holds.
        /// Case-insensitive, separator-tolerant, quote-tolerant - the ways two spellings of one path
        /// differ in practice.
        /// </summary>
        public static bool RefersToSameFile(string? left, string? right)
        {
            if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
                return false;

            return Normalise(left).Equals(Normalise(right), StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Bring a path to a single comparable spelling: quotes and whitespace removed, separators made
        /// uniform, repeated separators collapsed, no trailing separator.
        ///
        /// On Windows the operating system is asked to resolve the path, which also settles '.' and '..'
        /// segments. Off Windows that cannot be done for a Windows-shaped path, so the
        /// separator-normalised form is compared instead. That is exact for every path this validator
        /// accepts, because it accepts only absolute ones.
        /// </summary>
        private static string Normalise(string value)
        {
            var text = value.Trim().Trim('"').Replace('/', '\\');

            if (OperatingSystem.IsWindows())
            {
                try
                {
                    text = Path.GetFullPath(text);
                }
                catch
                {
                    // Fall through to separator normalisation.
                }
            }

            var isUnc = text.StartsWith("\\\\", StringComparison.Ordinal);
            var body = isUnc ? text.Substring(2) : text;

            var segments = body.Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);
            var joined = string.Join("\\", segments);

            return (isUnc ? "\\\\" + joined : joined).TrimEnd('\\');
        }

        private static bool IsRooted(string path)
        {
            try
            {
                // Path.IsPathRooted also returns true for "\foo" (rooted on the current drive), which is
                // not an absolute path for our purposes.
                if (!Path.IsPathRooted(path))
                    return false;

                var root = Path.GetPathRoot(path) ?? string.Empty;

                // "C:\..."
                if (root.Length >= 2 && root[1] == ':')
                    return true;

                // "\\server\share\..."
                if (root.StartsWith("\\\\", StringComparison.Ordinal))
                    return true;

                // A rooted POSIX path. The product is Windows-only: on Windows the drive and UNC rules
                // above are the only ones that pass, so "/foo.exe" is refused there. Off Windows a rooted
                // path is allowed so that the rest of the pipeline - validation outcomes, hashing,
                // inspection, storage - can be exercised and tested on a development host.
                return !OperatingSystem.IsWindows() && root.StartsWith("/", StringComparison.Ordinal);
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// True for a path that is rooted but not absolute: "C:folder\file.exe", which resolves against
        /// whatever the current directory of drive C happens to be.
        /// </summary>
        private static bool IsDriveRelative(string path)
        {
            if (path.Length < 2 || path[1] != ':')
                return false;

            return path.Length == 2 || path[2] != '\\' && path[2] != '/';
        }

        /// <summary>
        /// The volume root of a path, or an empty string when it cannot be determined.
        /// </summary>
        public static string VolumeRootOf(string? path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return string.Empty;

            try
            {
                return Path.GetPathRoot(Path.GetFullPath(path)) ?? string.Empty;
            }
            catch
            {
                return string.Empty;
            }
        }

        /// <summary>
        /// Strip extensions and directories so "Game.exe", "game" and "C:\x\Game.exe" compare equal.
        /// Mirrors <c>WindowsApiHelper.NormalizeProcessName</c>; duplicated here only because that method
        /// lives on a Windows-API helper and this one must be usable in a pure test.
        /// </summary>
        public static string NormaliseExecutableName(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            // Split on both separators by hand: on a non-Windows host Path.GetFileName does not treat '\'
            // as a separator, and this method must read a Windows path the same way everywhere.
            var text = value.Trim().Trim('"');

            var separator = text.LastIndexOfAny(new[] { '\\', '/' });

            var name = separator >= 0 ? text.Substring(separator + 1) : text;

            if (name.EndsWith(RequiredExtension, StringComparison.OrdinalIgnoreCase))
                name = name.Substring(0, name.Length - RequiredExtension.Length);

            return name.Trim();
        }
    }
}
