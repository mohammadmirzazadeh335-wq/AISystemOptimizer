using System;
using System.Runtime.InteropServices;
using AISystemOptimizer.Core.GameApp.Models;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// Result of a signature verification, including the raw code so a verdict is never a bare word.
    /// </summary>
    public sealed class SignatureVerificationResult
    {
        public SignatureVerdict Verdict { get; init; } = SignatureVerdict.Unknown;

        /// <summary>
        /// The HRESULT from WinVerifyTrust, or 0 when the check could not run at all. Reported so that
        /// "Invalid" always has a reason attached.
        /// </summary>
        public int ResultCode { get; init; }

        /// <summary>Subject of the signing certificate when it could be read.</summary>
        public string Subject { get; init; } = string.Empty;

        public string Explanation { get; init; } = string.Empty;
    }

    /// <summary>
    /// Verifies that an executable's Authenticode signature actually validates.
    ///
    /// Why this exists next to <c>ProcessHelper.GetSignatureStatus</c>: that method reads the certificate
    /// attached to a file. Reading a certificate proves a file *carries* a signature; it does not prove
    /// Windows accepted it. The specification asks for Valid / Invalid / Unsigned / Unknown, and claiming
    /// "Valid" from a certificate read would be exactly the kind of unverified claim this project does not
    /// make. So a real chain check is performed here, with WinVerifyTrust.
    ///
    /// Off Windows, and on any failure of the check itself, the verdict is <see cref="SignatureVerdict.Unknown"/>:
    /// never <see cref="SignatureVerdict.Valid"/>, never <see cref="SignatureVerdict.Invalid"/>.
    /// </summary>
    public static class AuthenticodeVerifier
    {
        #region Constants

        private const uint WTD_UI_NONE = 2;
        private const uint WTD_REVOKE_NONE = 0;
        private const uint WTD_CHOICE_FILE = 1;
        private const uint WTD_STATEACTION_VERIFY = 1;
        private const uint WTD_STATEACTION_CLOSE = 2;

        /// <summary>Offline-friendly: no revocation fetch, cache only, no network requirement.</summary>
        private const uint WTD_REVOCATION_CHECK_NONE = 0x10;
        private const uint WTD_CACHE_ONLY_URL_RETRIEVAL = 0x1000;
        private const uint WTD_SAFER_FLAG = 0x100;

        private static readonly Guid WINTRUST_ACTION_GENERIC_VERIFY_V2 =
            new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");

        // WinVerifyTrust returns a LONG. These are the values that mean something specific here.
        private const int S_OK = 0;
        private const int TRUST_E_NOSIGNATURE = unchecked((int)0x800B0100);
        private const int TRUST_E_SUBJECT_FORM_UNKNOWN = unchecked((int)0x800B0003);
        private const int TRUST_E_PROVIDER_UNKNOWN = unchecked((int)0x800B0001);
        private const int TRUST_E_EXPLICIT_DISTRUST = unchecked((int)0x800B0111);
        private const int TRUST_E_BAD_DIGEST = unchecked((int)0x80096010);
        private const int CERT_E_UNTRUSTEDROOT = unchecked((int)0x800B0109);
        private const int CERT_E_EXPIRED = unchecked((int)0x800B0101);
        private const int CERT_E_CHAINING = unchecked((int)0x800B010A);

        #endregion

        /// <summary>
        /// True when the platform is capable of performing the check at all.
        /// </summary>
        public static bool IsSupported => OperatingSystem.IsWindows();

        /// <summary>
        /// Verify a file's signature.
        /// </summary>
        public static SignatureVerificationResult Verify(string? filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath))
            {
                return new SignatureVerificationResult
                {
                    Verdict = SignatureVerdict.Unknown,
                    Explanation = "No file path was supplied."
                };
            }

            if (!IsSupported)
            {
                return new SignatureVerificationResult
                {
                    Verdict = SignatureVerdict.Unknown,
                    Explanation = "Signature verification requires Windows; this host cannot check it."
                };
            }

            try
            {
                return VerifyOnWindows(filePath);
            }
            catch (DllNotFoundException)
            {
                return new SignatureVerificationResult
                {
                    Verdict = SignatureVerdict.Unknown,
                    Explanation = "The Windows trust provider (wintrust.dll) is not available on this host."
                };
            }
            catch (EntryPointNotFoundException)
            {
                return new SignatureVerificationResult
                {
                    Verdict = SignatureVerdict.Unknown,
                    Explanation = "The Windows trust provider does not expose the expected entry point."
                };
            }
            catch (Exception exception)
            {
                return new SignatureVerificationResult
                {
                    Verdict = SignatureVerdict.Unknown,
                    Explanation = $"The check could not be completed: {exception.GetType().Name}."
                };
            }
        }

        private static SignatureVerificationResult VerifyOnWindows(string filePath)
        {
            var fileInfoSize = Marshal.SizeOf<WinTrustFileInfo>();
            var fileInfo = new WinTrustFileInfo
            {
                cbStruct = (uint)fileInfoSize,
                pcwszFilePath = Marshal.StringToCoTaskMemUni(filePath),
                hFile = IntPtr.Zero,
                pgKnownSubject = IntPtr.Zero
            };

            var dataSize = Marshal.SizeOf<WinTrustData>();

            var data = new WinTrustData
            {
                cbStruct = (uint)dataSize,
                dwUIChoice = WTD_UI_NONE,
                fdwRevocationChecks = WTD_REVOKE_NONE,
                dwUnionChoice = WTD_CHOICE_FILE,
                pFile = Marshal.AllocCoTaskMem(fileInfoSize),
                dwStateAction = WTD_STATEACTION_VERIFY,
                dwProvFlags = WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_SAFER_FLAG
            };

            var dataHandle = IntPtr.Zero;

            try
            {
                Marshal.StructureToPtr(fileInfo, data.pFile, false);

                dataHandle = Marshal.AllocCoTaskMem(dataSize);
                Marshal.StructureToPtr(data, dataHandle, false);

                var result = WinVerifyTrust(IntPtr.Zero, WINTRUST_ACTION_GENERIC_VERIFY_V2, dataHandle);

                var verdict = ClassifyResult(result);

                return new SignatureVerificationResult
                {
                    Verdict = verdict,
                    ResultCode = result,
                    Explanation = ExplainResult(verdict, result)
                };
            }
            finally
            {
                // Close the state, as the API requires, and release everything that was allocated.
                try
                {
                    if (dataHandle != IntPtr.Zero)
                    {
                        var closeData = Marshal.PtrToStructure<WinTrustData>(dataHandle);
                        closeData.dwStateAction = WTD_STATEACTION_CLOSE;

                        Marshal.StructureToPtr(closeData, dataHandle, false);
                        WinVerifyTrust(IntPtr.Zero, WINTRUST_ACTION_GENERIC_VERIFY_V2, dataHandle);
                    }
                }
                catch
                {
                    // Closing the state is best effort; the verdict has already been produced.
                }

                if (data.pFile != IntPtr.Zero) Marshal.FreeCoTaskMem(data.pFile);
                if (dataHandle != IntPtr.Zero) Marshal.FreeCoTaskMem(dataHandle);
                if (fileInfo.pcwszFilePath != IntPtr.Zero) Marshal.FreeCoTaskMem(fileInfo.pcwszFilePath);
            }
        }

        /// <summary>
        /// Map a WinVerifyTrust result to a verdict.
        ///
        /// "No signature" and "a signature that does not verify" are different findings and are reported
        /// differently. Unsigned is not evidence of harm - plenty of legitimate software is unsigned - and
        /// the interface is required to say so.
        /// </summary>
        public static SignatureVerdict ClassifyResult(int result)
        {
            if (result == S_OK)
                return SignatureVerdict.Valid;

            switch (result)
            {
                case TRUST_E_NOSIGNATURE:
                case TRUST_E_SUBJECT_FORM_UNKNOWN:
                case TRUST_E_PROVIDER_UNKNOWN:
                    return SignatureVerdict.Unsigned;

                case TRUST_E_EXPLICIT_DISTRUST:
                case TRUST_E_BAD_DIGEST:
                case CERT_E_UNTRUSTEDROOT:
                case CERT_E_EXPIRED:
                case CERT_E_CHAINING:
                    return SignatureVerdict.Invalid;

                default:
                    return SignatureVerdict.Unknown;
            }
        }

        public static string ExplainResult(SignatureVerdict verdict, int result)
        {
            return verdict switch
            {
                SignatureVerdict.Valid =>
                    "Windows verified the file against its signature.",

                SignatureVerdict.Unsigned =>
                    "The file carries no digital signature. This is common for legitimate software and is not " +
                    "by itself evidence of anything wrong; it does mean the publisher is unverified.",

                SignatureVerdict.Invalid => result switch
                {
                    TRUST_E_BAD_DIGEST =>
                        "The file is signed, but the contents no longer match the signature - the file was " +
                        "modified after it was signed.",
                    CERT_E_EXPIRED =>
                        "The signing certificate has expired.",
                    CERT_E_UNTRUSTEDROOT =>
                        "The signing certificate chains to a root that this machine does not trust.",
                    TRUST_E_EXPLICIT_DISTRUST =>
                        "This machine explicitly distrusts the publisher of this file.",
                    _ =>
                        $"The signature does not verify (code 0x{result:X8})."
                },

                _ =>
                    $"The signature could not be verified (code 0x{result:X8})."
            };
        }

        #region Interop

        [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int WinVerifyTrust(
            IntPtr hwnd,
            [MarshalAs(UnmanagedType.LPStruct)] Guid actionId,
            IntPtr data);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct WinTrustFileInfo
        {
            public uint cbStruct;
            public IntPtr pcwszFilePath;
            public IntPtr hFile;
            public IntPtr pgKnownSubject;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct WinTrustData
        {
            public uint cbStruct;
            public IntPtr pPolicyCallbackData;
            public IntPtr pSIPClientData;
            public uint dwUIChoice;
            public uint fdwRevocationChecks;
            public uint dwUnionChoice;
            public IntPtr pFile;
            public uint dwStateAction;
            public IntPtr hWVTStateData;
            public IntPtr pwszURLReference;
            public uint dwProvFlags;
            public uint dwUIContext;
            public IntPtr pSignatureSettings;
        }

        #endregion
    }
}
