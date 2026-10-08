using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// Reads everything that can be known about an executable without running it.
    ///
    /// Rules this class follows, in order:
    ///   1. It never executes the target. The file is opened for reading only; the PE header is parsed
    ///      byte by byte. Nothing about the file is passed to the shell.
    ///   2. It validates the path before it opens anything (see <see cref="ExecutablePathValidator"/>).
    ///   3. Every field it cannot determine is reported as absent or Unknown, never guessed. A missing
    ///      hash is empty; an architecture it cannot read is "Unknown"; a temperature-like value never
    ///      appears at all.
    ///   4. Running state is determined by matching the *path*, not the file name, and every match is
    ///      returned with its creation time so a caller can pin the identity.
    /// </summary>
    public sealed class ExecutableInspector
    {
        private readonly ILogger _logger;

        public ExecutableInspector(ILogger? logger = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
        }

        #region Inspection

        /// <summary>
        /// Inspect a path that has already been validated.
        /// </summary>
        public ExecutableInspectionResult Inspect(PathValidationResult validated)
        {
            if (validated == null) throw new ArgumentNullException(nameof(validated));

            var result = new ExecutableInspectionResult
            {
                SuppliedPath = validated.CanonicalPath,
                CanonicalPath = validated.CanonicalPath,
                FileName = validated.FileName,
                IsNetworkPath = validated.IsNetworkPath
            };

            result.Notes.AddRange(validated.Notes ?? new List<string>());

            if (!validated.IsValid)
            {
                result.Exists = false;
                result.Notes.Add(validated.ErrorMessage);
                return result;
            }

            var path = validated.CanonicalPath;

            try
            {
                var file = new FileInfo(path);

                result.Exists = file.Exists;

                if (!file.Exists)
                {
                    result.Notes.Add("The file is not present at this path.");
                    result.SignatureVerdict = SignatureVerdict.Unknown;
                    return result;
                }

                result.FileSizeBytes = file.Length;
                result.LastModifiedUtc = file.LastWriteTimeUtc;
                result.DirectoryPath = file.DirectoryName ?? string.Empty;
                result.ParentDirectoryPath = string.IsNullOrEmpty(result.DirectoryPath)
                    ? string.Empty
                    : (Directory.GetParent(result.DirectoryPath)?.FullName ?? string.Empty);

                ReadVersionResource(result, path);
                ReadPortableExecutableHeader(result, path);
                result.Sha256 = ComputeSha256(path, result);
                ReadSignature(result, path);
            }
            catch (UnauthorizedAccessException)
            {
                result.Exists = File.Exists(path);
                result.Notes.Add("This process is not allowed to read the file (permission denied).");
                result.SignatureVerdict = SignatureVerdict.Unknown;
            }
            catch (IOException exception)
            {
                result.Notes.Add($"The file could not be read: {exception.Message}");
                result.SignatureVerdict = SignatureVerdict.Unknown;
            }

            return result;
        }

        /// <summary>
        /// Validate and inspect in one step. This is what a caller should use when the path arrived from
        /// outside the application.
        /// </summary>
        public ExecutableInspectionResult ValidateAndInspect(string? path, out PathValidationResult validation)
        {
            validation = ExecutablePathValidator.Validate(path);

            if (!validation.IsValid)
            {
                _logger.Warning("ExecutableInspector",
                    $"Rejected a path before inspecting it: {validation.ErrorMessage}");

                return new ExecutableInspectionResult
                {
                    SuppliedPath = path ?? string.Empty,
                    Exists = false,
                    SignatureVerdict = SignatureVerdict.Unknown,
                    Notes = { validation.ErrorMessage }
                };
            }

            return Inspect(validation);
        }

        #endregion

        #region Metadata

        private static void ReadVersionResource(ExecutableInspectionResult result, string path)
        {
            try
            {
                var version = FileVersionInfo.GetVersionInfo(path);

                result.ProductName = Clean(version.ProductName);
                result.FileDescription = Clean(version.FileDescription);
                result.Publisher = Clean(version.CompanyName);
                result.FileVersion = Clean(version.FileVersion);
                result.ProductVersion = Clean(version.ProductVersion);
                result.Copyright = Clean(version.LegalCopyright);
            }
            catch (Exception exception)
            {
                // A file without a version resource is normal (many small tools have none).
                result.Notes.Add($"The file has no readable version information ({exception.GetType().Name}).");
            }
        }

        private static void ReadPortableExecutableHeader(ExecutableInspectionResult result, string path)
        {
            try
            {
                using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);

                var header = new byte[0x40];

                if (stream.Read(header, 0, header.Length) < header.Length)
                {
                    // Too small to hold a header at all. Say so rather than leaving "Unknown" unexplained.
                    result.Architecture = "Unknown";
                    result.Notes.Add("The file is too small to contain a Windows executable header.");
                    return;
                }

                // "MZ"
                if (header[0] != 0x4D || header[1] != 0x5A)
                {
                    result.Architecture = "Unknown";
                    result.Notes.Add("The file does not begin with a DOS header, so it is not a Windows executable.");
                    return;
                }

                var peOffset = BitConverter.ToInt32(header, 0x3C);

                if (peOffset <= 0 || peOffset + 6 > stream.Length)
                {
                    result.Architecture = "Unknown";
                    return;
                }

                stream.Seek(peOffset, SeekOrigin.Begin);

                var peHeader = new byte[6];

                if (stream.Read(peHeader, 0, peHeader.Length) < peHeader.Length)
                {
                    result.Architecture = "Unknown";
                    return;
                }

                // "PE\0\0"
                if (peHeader[0] != 0x50 || peHeader[1] != 0x45 || peHeader[2] != 0 || peHeader[3] != 0)
                {
                    result.Architecture = "Unknown";
                    result.Notes.Add("The file has no Portable Executable header.");
                    return;
                }

                var machine = BitConverter.ToUInt16(peHeader, 4);

                result.Architecture = machine switch
                {
                    0x014C => "x86",
                    0x8664 => "x64",
                    0xAA64 => "ARM64",
                    0x01C4 => "ARM",
                    0x0200 => "Itanium",
                    _ => $"Unknown (machine 0x{machine:X4})"
                };

                // Characteristics: bit 0x2000 is IMAGE_FILE_DLL.
                if (peOffset + 24 <= stream.Length)
                {
                    stream.Seek(peOffset + 22, SeekOrigin.Begin);

                    var characteristics = new byte[2];

                    if (stream.Read(characteristics, 0, 2) == 2)
                    {
                        var flags = BitConverter.ToUInt16(characteristics, 0);
                        result.IsDll = (flags & 0x2000) != 0;

                        if (result.IsDll)
                        {
                            result.Notes.Add(
                                "The file is marked as a library (DLL) rather than an application. It is " +
                                "accepted, but it is unusual to launch one directly.");
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                result.Architecture = "Unknown";
                result.Notes.Add($"The executable header could not be read ({exception.GetType().Name}).");
            }
        }

        private static string ComputeSha256(string path, ExecutableInspectionResult result)
        {
            try
            {
                using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                using var sha = SHA256.Create();

                var hash = sha.ComputeHash(stream);

                return Convert.ToHexString(hash).ToLowerInvariant();
            }
            catch (Exception exception)
            {
                // Without a hash there is no identity, so this is reported loudly rather than silently.
                result.Notes.Add(
                    $"The file hash could not be computed ({exception.GetType().Name}), so this executable " +
                    "cannot be identified reliably and will not be profiled.");

                return string.Empty;
            }
        }

        private static void ReadSignature(ExecutableInspectionResult result, string path)
        {
            var verification = AuthenticodeVerifier.Verify(path);

            result.SignatureVerdict = verification.Verdict;
            result.SignatureResultCode = verification.ResultCode;

            if (!string.IsNullOrWhiteSpace(verification.Explanation))
                result.Notes.Add(verification.Explanation);

            // The existing classifier is kept for continuity with the rest of the application. It reports
            // who appears in the certificate, not whether Windows trusts it.
            result.SignatureStatus = ProcessHelper.GetSignatureStatus(path);

            if (verification.Verdict == SignatureVerdict.Unsigned &&
                result.SignatureStatus != AISystemOptimizer.Core.Models.SignatureStatus.Unsigned)
            {
                // The two disagree, which means WinVerifyTrust reported "no signature" while a certificate
                // could be read. Say so instead of picking one silently.
                result.Notes.Add(
                    "Windows reports no valid signature while a certificate could be read from the file. " +
                    "Treat the publisher as unverified.");
            }
        }

        private static string Clean(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            var trimmed = value.Trim();

            // FileVersionInfo returns an empty-looking string when the resource is absent.
            return trimmed.All(c => c == '\0' || char.IsWhiteSpace(c)) ? string.Empty : trimmed;
        }

        #endregion

        #region Running state

        /// <summary>
        /// Find the processes that belong to an executable.
        ///
        /// A process is treated as a match only when its executable path equals the profile's path.
        /// A process whose name matches but whose path cannot be read is returned separately as
        /// unconfirmed, so the caller can report it honestly instead of either ignoring it or assuming
        /// it is the application.
        /// </summary>
        public ApplicationRunState DetectRunningState(
            string executablePath,
            out List<ApplicationRunInfo> confirmed,
            out List<int> unconfirmedProcessIds)
        {
            confirmed = new List<ApplicationRunInfo>();
            unconfirmedProcessIds = new List<int>();

            if (string.IsNullOrWhiteSpace(executablePath))
                return ApplicationRunState.NotRunning;

            var fileName = Path.GetFileName(executablePath);
            var processName = Path.GetFileNameWithoutExtension(fileName);

            if (string.IsNullOrWhiteSpace(processName))
                return ApplicationRunState.NotRunning;

            Process[] candidates;

            try
            {
                candidates = Process.GetProcessesByName(processName);
            }
            catch (Exception exception)
            {
                _logger.Warning("ExecutableInspector",
                    $"The process list could not be read ({exception.GetType().Name}).");

                return ApplicationRunState.NotRunning;
            }

            var foregroundPid = WindowsApiHelper.GetForegroundProcessId();

            foreach (var process in candidates)
            {
                try
                {
                    var pid = process.Id;
                    var path = WindowsApiHelper.GetProcessExecutablePath(pid);

                    if (ExecutablePathValidator.RefersToSameFile(path, executablePath))
                    {
                        var creation = WindowsApiHelper.GetProcessCreationTimeUtc(pid);

                        if (!creation.HasValue)
                        {
                            // The path matched but the identity could not be pinned. Without a creation
                            // time no action against this process could ever be executed safely, so it is
                            // reported as unconfirmed rather than as a confirmed instance.
                            unconfirmedProcessIds.Add(pid);
                            continue;
                        }

                        confirmed.Add(new ApplicationRunInfo
                        {
                            ProcessId = pid,
                            CreationTimeUtc = creation.Value,
                            Path = path ?? string.Empty,
                            WorkingSet = SafeWorkingSet(process),
                            IsConfirmedMatch = true,
                            IsForeground = pid == foregroundPid,
                            HasVisibleWindow = WindowsApiHelper.HasVisibleWindow(pid)
                        });
                    }
                    else if (string.IsNullOrWhiteSpace(path))
                    {
                        // Same file name, path unreadable. Cannot be confirmed either way.
                        unconfirmedProcessIds.Add(pid);
                    }
                }
                catch
                {
                    // The process exited between enumeration and inspection.
                }
                finally
                {
                    process.Dispose();
                }
            }

            if (confirmed.Count > 0)
                return ApplicationRunState.Running;

            return unconfirmedProcessIds.Count > 0
                ? ApplicationRunState.Unconfirmed
                : ApplicationRunState.NotRunning;
        }

        private static long SafeWorkingSet(Process process)
        {
            try
            {
                return process.WorkingSet64;
            }
            catch
            {
                return 0;
            }
        }

        #endregion
    }
}
