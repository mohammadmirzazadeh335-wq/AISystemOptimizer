using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.Constants
{
    /// <summary>
    /// Contains lists of critical Windows processes that should never be terminated
    /// </summary>
    public static class CriticalProcesses
    {
        #region Critical System Processes

        /// <summary>
        /// List of absolutely critical Windows system processes
        /// These processes are essential for Windows to function
        /// </summary>
        public static readonly HashSet<string> SystemCritical = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            // Core Windows processes
            "System",
            "System Idle Process",
            "Registry",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "services.exe",
            "lsass.exe",
            "winlogon.exe",
            
            // Desktop and Window Management
            "dwm.exe",
            "explorer.exe",
            
            // Service Host
            "svchost.exe",
            
            // Windows Session Manager
            "smss",
            
            // Local Security Authority Subsystem Service
            "lsass",
            
            // Windows Logon
            "winlogon",
            
            // Windows Initialization
            "wininit",
            
            // Service Control Manager
            "services",
            
            // Client Server Runtime Subsystem
            "csrss"
        };

        #endregion

        #region Windows System Processes

        /// <summary>
        /// List of important Windows system processes
        /// These should not be terminated without careful consideration
        /// </summary>
        public static readonly HashSet<string> SystemProcesses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            // Windows Management
            "svchost.exe",
            "taskhostw.exe",
            "taskhost.exe",
            "dllhost.exe",
            "conhost.exe",
            "runtimebroker.exe",
            "sihost.exe",
            "shellhost.exe",
            
            // Windows Shell
            "explorer.exe",
            "shell32.dll",
            "user32.dll",
            
            // Desktop Window Manager
            "dwm.exe",
            "dwmredir.exe",
            
            // Windows Search
            "SearchIndexer.exe",
            "SearchProtocolHost.exe",
            "SearchFilterHost.exe",
            
            // Windows Update
            "MoUsoCoreWorker.exe",
            "TiWorker.exe",
            "svchost.exe",
            "trustedinstaller.exe",
            
            // Windows Defender
            "MsMpEng.exe",
            "mpcmdrun.exe",
            "MpOav.exe",
            "MpSoftwareUpdate.exe",
            "NisSrv.exe",
            "MsMpRes.exe",
            
            // Windows Security
            "SecurityHealthService.exe",
            "SecurityHealthSystray.exe",
            "WindowsSecurity.exe",
            "wscsvc.dll",
            
            // Windows Firewall
            "mpssvc.dll",
            "BFE.dll",
            
            // Windows Audio
            "Audiodg.exe",
            "AudioEndpointBuilder.exe",
            "AudioSrv.exe",
            
            // Windows Networking
            "iphlpsvc.dll",
            "nlasvc.dll",
            "netman.dll",
            "wlanext.exe",
            "wlansvc.dll",
            "wlanhlp.dll",
            
            // Windows Plug and Play
            "PlugPlay.exe",
            "umpnpmgr.dll",
            
            // Windows Power Management
            "powercfg.exe",
            "powershell.exe",
            
            // Windows Themes
            "Themes.exe",
            "ThemeService.exe",
            
            // Windows User Manager
            "UserManager.dll",
            
            // Windows Management Instrumentation
            "winmgmt.exe",
            "WmiPrvSE.exe",
            "WmiApSrv.exe",
            
            // Windows Task Scheduler
            "schedule.exe",
            "taskschd.exe",
            "taskeng.exe",
            
            // Windows Event Log
            "EventLog.exe",
            "svchost.exe",
            
            // Windows Performance Counters
            "perfhost.exe",
            
            // Windows Remote Procedure Call
            "rpcss.dll",
            "RpcSs",
            "DcomLaunch",
            "RpcEptMapper",
            
            // Windows COM+
            "dllhost.exe",
            "comsvcs.dll",
            
            // Windows Distributed Transaction Coordinator
            "msdtc.exe",
            
            // Windows Cryptography
            "cryptsvc.dll",
            "ProtectedStorage",
            
            // Windows Time
            "w32time.dll",
            
            // Windows Telephony
            "tapi32.dll",
            "tapisrv.dll",
            
            // Windows Fax
            "fxssvc.exe",
            
            // Windows Printing
            "spoolsv.exe",
            "PrintIsolationHost.exe",
            
            // Windows Clipboard
            "clip.exe",
            "clipbrd.exe",
            
            // Windows System Restore
            "rstrui.exe",
            "swprv.dll",
            
            // Windows Shadow Copy
            "vssvc.exe",
            "swprv.dll",
            
            // Windows Volume Snapshot
            "vds.exe",
            
            // Windows Error Reporting
            "werfault.exe",
            "wermgr.exe",
            "wercon.exe",
            "werui.exe",
            
            // Windows Problem Reporting
            "wpr.exe",
            "wprui.exe",
            
            // Windows Diagnostics
            "diagtrack.exe",
            "dmwappushservice.exe",
            "dsrole.exe",
            
            // Windows Connectivity
            "NetworkLocationWizard.exe",
            "netcfgx.dll",
            "netman.dll",
            
            // Windows Mobility Center
            "mblctr.exe",
            
            // Windows SideShow
            "gadgets.exe",
            "sidebar.exe",
            
            // Windows Media
            "wmplayer.exe",
            "wmpnetwk.exe",
            "wmpnscfg.exe",
            
            // Windows Camera
            "Camera.exe",
            
            // Windows Photos
            "PhotosApp.exe",
            
            // Windows Maps
            "Maps.exe",
            
            // Windows Calculator
            "Calculator.exe",
            
            // Windows Store
            "WinStore.App.exe",
            "wsclient.dll",
            
            // Windows Universal Apps
            "ApplicationFrameHost.exe",
            "ShellExperienceHost.exe",
            "StartMenuExperienceHost.exe",
            "SystemSettings.exe",
            "Settings.exe",
            "ImmersiveControlPanel.exe",
            "WindowsActionDialog.exe",
            "WindowsFeedback.exe",
            "InputApp.exe",
            "LockApp.exe",
            "LogonUI.exe",
            "OobeFldr.exe",
            "PeopleApp.exe",
            "PhoneExperienceHost.exe",
            "SharedRealityApp.exe",
            "SystemSettingsAdminFlows.exe",
            "SystemSettingsAdminFlowsUI.exe",
            "TextInputHost.exe",
            "TokenBroker.exe",
            "UserDataSvcHost.exe",
            "WebAccountBroker.exe",
            "Windows.Algebra.App.exe",
            "Windows.Calculator.exe",
            "Windows.Camera.exe",
            "Windows.Maps.exe",
            "Windows.MiracastView.exe",
            "Windows.Photos.exe",
            "Windows.ShellExperienceHost.exe",
            "Windows.StartMenuExperienceHost.exe",
            "Windows.SystemToast.exe",
            "Windows.Warpspace.exe",
            "WindowsInternal.ComposableShell.Experiences.TextInput.InputApp.exe",
            
            // Windows Security Center
            "wscsvc.dll",
            "wscui.cpl",
            
            // Windows Firewall Control Panel
            "wf.msc",
            "WindowsFirewall.cpl",
            
            // Windows Defender Control Panel
            "WindowsDefender.cpl",
            
            // Windows Update Standalone Installer
            "wusa.exe",
            
            // Windows Module Installer
            "moe.exe",
            
            // Windows Installer
            "msiexec.exe",
            "msi.dll",
            
            // Windows Script Host
            "wscript.exe",
            "cscript.exe",
            
            // Windows Command Processor
            "cmd.exe",
            
            // Windows PowerShell
            "powershell.exe",
            "pwsh.exe",
            
            // Windows Terminal
            "WindowsTerminal.exe",
            "wt.exe",
            "Terminal.exe",
            
            // Windows Console Host
            "conhost.exe",
            
            // Windows Task Manager
            "Taskmgr.exe",
            
            // Windows Resource Monitor
            "resmon.exe",
            
            // Windows Performance Monitor
            "perfmon.exe",
            
            // Windows System Configuration
            "msconfig.exe",
            
            // Windows System Information
            "msinfo32.exe",
            
            // Windows DirectX Diagnostic
            "dxdiag.exe",
            
            // Windows Registry Editor
            "regedit.exe",
            
            // Windows Disk Management
            "diskmgmt.msc",
            
            // Windows Device Manager
            "devmgmt.msc",
            
            // Windows Event Viewer
            "eventvwr.msc",
            
            // Windows Services
            "services.msc",
            
            // Windows Computer Management
            "compmgmt.msc",
            
            // Windows Local Users and Groups
            "lusrmgr.msc",
            
            // Windows Local Security Policy
            "secpol.msc",
            
            // Windows Group Policy Editor
            "gpedit.msc",
            
            // Windows ODBC Data Source Administrator
            "odbccp32.cpl",
            
            // Windows Fonts Folder
            "fonts.cpl",
            
            // Windows Display Properties
            "desk.cpl",
            
            // Windows System Properties
            "sysdm.cpl",
            
            // Windows Power Options
            "powercfg.cpl",
            
            // Windows Region and Language
            "intl.cpl",
            
            // Windows Date and Time
            "timedate.cpl",
            
            // Windows Mouse Properties
            "main.cpl",
            
            // Windows Keyboard Properties
            "main.cpl",
            
            // Windows Sound Properties
            "mmsys.cpl",
            
            // Windows Network Connections
            "ncpa.cpl",
            
            // Windows Internet Properties
            "inetcpl.cpl",
            
            // Windows Phone and Modem Options
            "telephon.cpl",
            
            // Windows Game Controllers
            "joy.cpl",
            
            // Windows Scanners and Cameras
            "sticpl.cpl",
            
            // Windows Administrative Tools
            "control.exe",
            "control.dll",
            
            // Windows Help
            "help.exe",
            "helppane.exe",
            
            // Windows Tour
            "Tour.exe",
            
            // Windows Welcome Center
            "Oobe.exe",
            
            // Windows Setup
            "setup.exe",
            "setupapi.dll",
            
            // Windows System File Checker
            "sfc.exe",
            
            // Windows Check Disk
            "chkdsk.exe",
            
            // Windows Defragment
            "defrag.exe",
            
            // Windows Disk Cleanup
            "cleanmgr.exe",
            
            // Windows System Restore
            "rstrui.exe",
            
            // Windows Backup
            "sdclt.exe",
            
            // Windows Recovery
            "recdisc.exe",
            
            // Windows Memory Diagnostic
            "MdSched.exe",
            
            // Windows Problem Steps Recorder
            "psr.exe",
            
            // Windows Steps Recorder
            "StepsRecorder.exe",
            
            
            
            
            
            
            
            // Windows Steps Recorder
            "StepsRecorder.exe"
        };

        #endregion

        #region Microsoft user-facing applications

        /// <summary>
        /// Microsoft applications that the user launches deliberately rather than part of Windows
        /// starting up: Notepad, Paint, Calculator, WordPad, Character Map and the Snipping Tool.
        ///
        /// These are deliberately <b>not</b> classified as system processes. Doing so mislabelled them
        /// as "Windows System" in the interface and made them permanently unoptimisable, which is both
        /// inaccurate and unnecessary - the far stronger guarantee that applies to them is the one that
        /// covers every application: a program that owns a window, or that owns the foreground window,
        /// is never closed automatically. A backgrounded copy of Notepad with no window is not in use.
        /// </summary>
        public static readonly HashSet<string> MicrosoftUserApplications = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "notepad.exe",
            "mspaint.exe",
            "calc.exe",
            "wordpad.exe",
            "charmap.exe",
            "SnippingTool.exe",
            "SnipAndSketch.exe"
        };

        /// <summary>
        /// True when the process is one of Microsoft's own user-facing applications.
        /// </summary>
        public static bool IsMicrosoftUserApplication(string processName)
        {
            if (string.IsNullOrWhiteSpace(processName))
                return false;

            return MicrosoftUserApplications.Contains(processName);
        }

        #endregion

        #region Security Processes

        /// <summary>
        /// List of security-related processes that should not be terminated
        /// </summary>
        public static readonly HashSet<string> SecurityProcesses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            // Windows Defender
            "MsMpEng.exe",
            "mpcmdrun.exe",
            "MpOav.exe",
            "MpSoftwareUpdate.exe",
            "NisSrv.exe",
            "MsMpRes.exe",
            "MPNdr.exe",
            "MpSigStub.exe",
            
            // Windows Security Center
            "SecurityHealthService.exe",
            "SecurityHealthSystray.exe",
            "WindowsSecurity.exe",
            "wscsvc.dll",
            "wscui.cpl",
            
            // Windows Firewall
            "mpssvc.dll",
            "BFE.dll",
            "WFmspService.dll",
            
            // Windows Security
            "LSASS.EXE",
            "lsass.exe",
            "authhost.exe",
            "consent.exe",
            "credentialmanager.exe",
            "seclogon.exe",
            "vaultcmd.exe",
            
            // Windows Credential Manager
            "VaultSvc.dll",
            "CredentialManager.dll",
            
            // Windows SmartScreen
            "SmartScreen.exe",
            
            // Windows Defender Application Guard
            "AppVShNotify.exe",
            "AppVClient.exe",
            "AppVStreamingUX.exe",
            
            // Windows Defender Exploit Guard
            "ExploitGuard.exe",
            
            // Windows Defender Controlled Folder Access
            "CFAMon.exe",
            
            // Windows Defender Network Inspection
            "NisSrv.exe",
            "NisDrvWFP.sys",
            
            // Windows Defender System Guard
            "SgrmBroker.exe",
            "SystemGuardRuntimeMonitorBroker",
            
            // Windows Hello
            "HelloFace.exe",
            "WindowsHello.exe",
            "NgcCtnrSvc.dll",
            "NgcPopkeySvc.dll",
            "NgcSvc.dll",
            
            // Windows Biometric Service
            "BioEnrollment.exe",
            "BiometricSettings.exe",
            "WUDFHost.exe",
            
            // Windows Secure Kernel
            "SecureKernel.exe",
            
            // Windows Virtualization Based Security
            "HVLoader.dll",
            "HvHost.exe",
            "IsolatedUserMode.dll",
            
            // Windows Device Guard
            "DeviceGuard.exe",
            "Ci.dll",
            
            // Windows Credential Guard
            "CredentialGuard.exe",
            "LsaIso.exe",
            
            // Windows Application Guard
            "AppGuard.exe",
            "AppVIsvSubsystems32.dll",
            "AppVIsvSubsystems64.dll",
            
            // Windows Sandbox
            "WindowsSandboxClient.exe",
            "WindowsSandboxManager.exe",
            
            // Third-party antivirus (common names)
            "avp.exe",           // Kaspersky
            "kav.exe",
            "avastsvc.exe",      // Avast
            "avastui.exe",
            "afwServ.exe",
            "AvastSvc.exe",
            "egui.exe",          // ESET
            "ekrn.exe",
            "esets_scanner.exe",
            "mcafee",            // McAfee
            "mcshield.exe",
            "mcsysmon.exe",
            "mcnasvc.exe",
            "mfeann.exe",
            "mfeavfk.exe",
            "mfefire.exe",
            "mfehidk.exe",
            "mfemms.exe",
            "mfevtps.exe",
            "norton",            // Norton
            "ccSvcHst.exe",
            "NS.exe",
            "NortonSecurity.exe",
            "bitdefender",       // Bitdefender
            "bdagent.exe",
            "vsserv.exe",
            "updatesrv.exe",
            "avc3.exe",
            "avfw.exe",
            "seccenter.exe",
            "webscanx.exe",
            "trend micro",       // Trend Micro
            "PccNTMon.exe",
            "TmListen.exe",
            "TmPfw.exe",
            "TmProxy.exe",
            "avira",            // Avira
            "avgnt.exe",
            "avguard.exe",
            "avshadow.exe",
            "sched.exe",
            "avcenter.exe",
            "avg",              // AVG
            "avgidsagent.exe",
            "avgwdsvc.exe",
            "avgrsx.exe",
            "avgemc.exe",
            "avgnsx.exe",
            "avgcsrvx.exe",
            "comodo",           // Comodo
            "cmdagent.exe",
            "cfp.exe",
            "cavwp.exe",
            "cis.exe",
            "f-secure",         // F-Secure
            "fsau.exe",
            "fsgk32st.exe",
            "fssm32.exe",
            "fsma32.exe",
            "fshoster32.exe",
            "panda",            // Panda Security
            "PSANHost.exe",
            "PSINProc.exe",
            "PSINProt.exe",
            "PSUAService.exe",
            "WebProxy.exe",
            "sophos",           // Sophos
            "SAVService.exe",
            "SavService.exe",
            "swc_service.exe",
            "swc_gui.exe",
            "malwarebytes",     // Malwarebytes
            "MBAMService.exe",
            "mbamtray.exe",
            "mbam.exe",
            "mbamservice.exe",
            "mbamscheduler.exe",
            "webroot",          // Webroot
            "WRSA.exe",
            "wrsvc.exe",
            "SSU.exe",
            "kaspersky",        // Kaspersky
            "avp.exe",
            "avpui.exe",
            "kav.exe",
            "kavui.exe",
            "kavfs.exe",
            "kavfssrv.exe",
            "klnagent.exe"
        };

        #endregion

        #region Driver Processes

        /// <summary>
        /// List of driver-related processes that should not be terminated
        /// </summary>
        public static readonly HashSet<string> DriverProcesses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            // AMD Graphics
            "atieclxx.exe",
            "atiesrxx.exe",
            "ati2evxx.exe",
            "ati2evxx.dll",
            "aticlx64.exe",
            "aticlx32.exe",
            "atieclxx.exe",
            "atiesrxx.exe",
            "RadeonSoftware.exe",
            "RadeonSettings.exe",
            "AMDExternalEvents64.exe",
            "AMDExternalEvents32.exe",
            "AMDCleanupUtility.exe",
            "AMDCrashDefense.exe",
            "AMDFanControl.exe",
            "AMDLinkServer.exe",
            "AMDLinkClient.exe",
            "AMDOverDriveCtrl.exe",
            "AMDRSServ.exe",
            "AMDRSSrcExt.exe",
            "AMDUSBDeviceReset.exe",
            "ATIAPFXX.BAT",
            "ATIAPFXX.exe",
            "ATICCL64.exe",
            "ATICCL32.exe",
            "ATICDS64.exe",
            "ATICDS32.exe",
            "ATIESRXX.EXE",
            "ATIECLXX.EXE",
            "ATI2EVXX.EXE",
            "ATI2EVXX.DLL",
            "ATI2MDXX.EXE",
            "ATIODE.exe",
            "ATIODE64.exe",
            "ATIPTAXX.exe",
            "ATIPTA64.exe",
            "ATISB64.exe",
            "CLI.exe",
            "CLI64.exe",
            "MOM.exe",
            "MOM64.exe",
            "ccc.exe",
            "ccc64.exe",
            "ccc764.exe",
            "LOG.exe",
            "KMD.exe",
            
            // NVIDIA Graphics
            "NvBackend.exe",
            "NvContainer.exe",
            "NvContainerSetup.exe",
            "NvCpl.dll",
            "NvCpl.exe",
            "NvGpuUtilization.exe",
            "NvNodeLauncher.exe",
            "NvNodeManager.exe",
            "NvNodeService.exe",
            "NvOFLSDRunner.exe",
            "NvProfileUpdater.exe",
            "NvTelemetry.exe",
            "NvTelemetry64.exe",
            "NvTelemetryContainer.exe",
            "NvTray.exe",
            "NvUI.exe",
            "NvWSS.exe",
            "NvWSS64.exe",
            "NvWSSDp64.exe",
            "NvXDCC.exe",
            "NvXDCC64.exe",
            "NvXDSync.exe",
            "NvXDVV.exe",
            "NvXDVV64.exe",
            "nvcontainer.exe",
            "nvcontainerls.exe",
            "nvdispco64.exe",
            "nvdispco32.exe",
            "nvdlist.exe",
            "nvdm.exe",
            "nvflash.exe",
            "nvinfo.exe",
            "nvlddmkm.sys",
            "nvldumd.dll",
            "nvldumdx.dll",
            "nvopencl.dll",
            "nvcuda.dll",
            "nvcuvid.dll",
            "nvencodeapi.dll",
            "nvdecoder.dll",
            "nvcuvenc.dll",
            "nvml.dll",
            "nvapi.dll",
            "nvapi64.dll",
            
            // Intel Graphics
            "igfxCUIService.exe",
            "igfxEM.exe",
            "igfxHK.exe",
            "igfxTray.exe",
            "igfxpers.exe",
            "igfxsrvc.exe",
            "igfxext.exe",
            "igfxDTCM.exe",
            "igfxLHM.exe",
            "igfxLHMM.exe",
            "GfxUI.exe",
            "Gfxv4_0.exe",
            "Gfxv2_0.exe",
            "IntelCpHDCPSvc.exe",
            "IntelCpHeciSvc.exe",
            "IntelGraphics.exe",
            "IntelGraphicsProxy.exe",
            "igfxCUIService64.exe",
            "igfxEM64.exe",
            "igfxHK64.exe",
            "igfxTray64.exe",
            "igfxpers64.exe",
            "igfxsrvc64.exe",
            "igfxext64.exe",
            "igfxDTCM64.exe",
            "igfxLHM64.exe",
            "igfxLHMM64.exe",
            
            // Audio Drivers
            "AudioEndpointBuilder.exe",
            "Audiodg.exe",
            "AudioSrv.exe",
            "Audioses.exe",
            "RtkAudioService64.exe",
            "RtkAudioService.exe",
            "RtkNGUI64.exe",
            "RtkNGUI.exe",
            "RtkCplApp64.exe",
            "RtkCplApp.exe",
            "RealtekAudioConsole.exe",
            "ConexantAudio.exe",
            "CAudioFilterAgent64.exe",
            "CAudioFilterAgent.exe",
            "CxAudMsg64.exe",
            "CxAudMsg.exe",
            "CxUtilSvc.exe",
            "CxUtilSvc64.exe",
            "DolbyDAX2APOPropPage.exe",
            "DolbyDAX2APOSvc.exe",
            "DolbyDAX2.exe",
            "DolbyDAX2Tray.exe",
            "IDTNC64.cpl",
            "IDTNC.cpl",
            "sttray64.exe",
            "sttray.exe",
            "SRS_PremiumSound_64.exe",
            "SRS_PremiumSound.exe",
            "WavesSvc64.exe",
            "WavesSvc.exe",
            "WavesMaxxAudioService64.exe",
            "WavesMaxxAudioService.exe",
            "CreativeAudio.exe",
            "CTAudSvcService.exe",
            "CTAudSvcService64.exe",
            
            // Network Drivers
            "WlanExt.exe",
            "WlanSvc.dll",
            "Wlanhlp.dll",
            "WlanMsg.dll",
            "WlanSec.dll",
            "WlanTlg.dll",
            "WlanUtil.dll",
            "Wlanapi.dll",
            "wlansec.dll",
            "wlansvc.dll",
            "wlanhlp.dll",
            "wlanmsg.dll",
            "wlantlg.dll",
            "wlanutil.dll",
            "wlanapi.dll",
            "bcmsmwdm.dll",
            "bcmwltry.exe",
            "bcmwl64.exe",
            "bcmwl32.exe",
            "IntelWifi.exe",
            "IntelWifi64.exe",
            "IntelWifi32.exe",
            "IWMSvc.exe",
            "IWMSSvc.exe",
            "QualcommAtheros.exe",
            "QualcommAtheros64.exe",
            "QualcommAtheros32.exe",
            "KillerNetworkService.exe",
            "KillerNetworkService64.exe",
            "KillerNetworkService32.exe",
            "RivetNetworks.exe",
            "RivetNetworks64.exe",
            "RivetNetworks32.exe",
            
            // Bluetooth Drivers
            "BtwRSupportService.exe",
            "BtwService.exe",
            "BtwAppl.exe",
            "BtwTray.exe",
            "BtwMUI.exe",
            "BtwUSBService.exe",
            "BtwUSB.exe",
            "BtwDebugService.exe",
            "BtwDebug.exe",
            "IntelBluetooth.exe",
            "IntelBluetooth64.exe",
            "IntelBluetooth32.exe",
            "BluetoothDeviceMonitor.exe",
            "BluetoothUserService.exe",
            "bthserv.dll",
            "BthProps.cpl",
            "fsquirt.exe",
            
            // Touchpad Drivers
            "SynTPEnh.exe",
            "SynTPEnh64.exe",
            "SynTPEnh32.exe",
            "SynTPHelper.exe",
            "SynTPHelper64.exe",
            "SynTPHelper32.exe",
            "SynTPAuto.exe",
            "SynTPAuto64.exe",
            "SynTPAuto32.exe",
            "SynTPCpl.exe",
            "SynTPCpl64.exe",
            "SynTPCpl32.exe",
            "SynZMetr.exe",
            "SynZMetr64.exe",
            "SynZMetr32.exe",
            "ETDControlCenter.exe",
            "ETDControlCenter64.exe",
            "ETDControlCenter32.exe",
            "ETDWare.exe",
            "ETDWare64.exe",
            "ETDWare32.exe",
            "Elantech.exe",
            "Elantech64.exe",
            "Elantech32.exe",
            "ETDCtrl.exe",
            "ETDCtrl64.exe",
            "ETDCtrl32.exe",
            "AsusTPCenter.exe",
            "AsusTPCenter64.exe",
            "AsusTPCenter32.exe",
            
            // USB Drivers
            "USB3Monitor.exe",
            "USB3Monitor64.exe",
            "USB3Monitor32.exe",
            "USBChargerPlus.exe",
            "USBChargerPlus64.exe",
            "USBChargerPlus32.exe",
            "USBGuard.exe",
            "USBGuard64.exe",
            "USBGuard32.exe",
            "IntelUSB3Monitor.exe",
            "IntelUSB3Monitor64.exe",
            "IntelUSB3Monitor32.exe",
            
            // Storage Drivers
            "SamsungMagician.exe",
            "SamsungMagician64.exe",
            "SamsungMagician32.exe",
            "SamsungNvmeDriver.exe",
            "SamsungNvmeDriver64.exe",
            "SamsungNvmeDriver32.exe",
            "SamsungRapidMode.exe",
            "SamsungRapidMode64.exe",
            "SamsungRapidMode32.exe",
            "IntelRapidStorage.exe",
            "IntelRapidStorage64.exe",
            "IntelRapidStorage32.exe",
            "IAStorIcon.exe",
            "IAStorIcon64.exe",
            "IAStorIcon32.exe",
            "IAStorDataMgrSvc.exe",
            "IAStorDataMgrSvc64.exe",
            "IAStorDataMgrSvc32.exe",
            "RST.exe",
            "RST64.exe",
            "RST32.exe",
            "WDDriveService.exe",
            "WDDriveService64.exe",
            "WDDriveService32.exe",
            "WDSyncService.exe",
            "WDSyncService64.exe",
            "WDSyncService32.exe",
            "SeagateDashboard.exe",
            "SeagateDashboard64.exe",
            "SeagateDashboard32.exe",
            "WDQuickView.exe",
            "WDQuickView64.exe",
            "WDQuickView32.exe",
            "SanDiskSSDDashboard.exe",
            "SanDiskSSDDashboard64.exe",
            "SanDiskSSDDashboard32.exe",
            
            // Chipset Drivers
            "IntelDriver.exe",
            "IntelDriver64.exe",
            "IntelDriver32.exe",
            "IntelChipset.exe",
            "IntelChipset64.exe",
            "IntelChipset32.exe",
            "AMDChipset.exe",
            "AMDChipset64.exe",
            "AMDChipset32.exe",
            "AMDRyzenMaster.exe",
            "AMDRyzenMaster64.exe",
            "AMDRyzenMaster32.exe",
            "RyzenMaster.exe",
            "RyzenMaster64.exe",
            "RyzenMaster32.exe",
            
            // Virtualization Drivers
            "VBoxService.exe",
            "VBoxTray.exe",
            "VBoxClient.exe",
            "VBoxWindowsAdditions.exe",
            "VMwareTray.exe",
            "VMwareService.exe",
            "VMwareUser.exe",
            "VMwareTools.exe",
            "VMwareVGAuthService.exe",
            "VMwareBlastVGAuthService.exe",
            "vmsrvc.exe",
            "vmtoolsd.exe",
            "HyperV.exe",
            "HyperV64.exe",
            "HyperV32.exe",
            "vmwp.exe",
            "vmcompute.exe",
            "vmms.exe",
            
            // Other Hardware Drivers
            "Thunderbolt.exe",
            "Thunderbolt64.exe",
            "Thunderbolt32.exe",
            "ThunderboltSoftware.exe",
            "ThunderboltSoftware64.exe",
            "ThunderboltSoftware32.exe",
            "IntelThunderbolt.exe",
            "IntelThunderbolt64.exe",
            "IntelThunderbolt32.exe"
        };

        #endregion

        #region Methods

        /// <summary>
        /// Check if a process is critical
        /// </summary>
        public static bool IsCritical(string processName, string? processPath = null, bool isService = false)
        {
            if (string.IsNullOrWhiteSpace(processName))
                return false;

            // The idle pseudo-process has no image and cannot be terminated, but naming it explicitly
            // keeps it out of every candidate list instead of relying on the kernel to refuse later.
            if (IsIdleProcess(processName))
                return true;

            // A name-only lookup still covers every curated list, so callers that have no path are
            // not left unprotected.
            if (SystemCritical.Contains(processName) ||
                SystemProcesses.Contains(processName) ||
                SecurityProcesses.Contains(processName) ||
                DriverProcesses.Contains(processName))
            {
                return true;
            }

            // BUG FIXED HERE - asymmetric protection.
            // This method used to consult the four curated lists above and nothing else, while
            // IsDriverProcess() (used for classification) additionally applied a naming heuristic for
            // vendor binaries. The two answers therefore disagreed for a process like
            // RtkAudUService64.exe: classified as a hardware driver, yet not considered critical - so the
            // safety layer would happily approve closing it. The category logic is layered and this
            // method now applies the same layering, by delegating to it.
            //
            // The layered check runs even without a path. The path-dependent tests inside it
            // (LooksLikeWindowsComponent, the driver-store check) already return false for an empty
            // path, while the name-based heuristics still work - and it is exactly those name-based
            // heuristics that must not be skipped, since skipping them was the original defect.
            var category = GetProcessCategory(processName, processPath ?? string.Empty, isService);

            return category == ProcessCategory.Critical ||
                   category == ProcessCategory.System ||
                   category == ProcessCategory.Driver ||
                   category == ProcessCategory.Security;
        }

        /// <summary>
        /// True when Windows cannot function without the process, or when closing it would remove a
        /// security guarantee. Equivalent to the old <c>IsCritical</c> name-based check and used where a
        /// caller genuinely has only a name.
        /// </summary>
        public static bool IsCriticalName(string processName)
        {
            return SystemCritical.Contains(processName) ||
                   SystemProcesses.Contains(processName) ||
                   SecurityProcesses.Contains(processName) ||
                   DriverProcesses.Contains(processName);
        }

        /// <summary>
        /// True when the process is Microsoft's own Idle pseudo-process. It is listed explicitly so the
        /// projection of the process table never proposes it.
        /// </summary>
        public static bool IsIdleProcess(string? processName)
        {
            if (string.IsNullOrWhiteSpace(processName))
                return false;

            return string.Equals(processName, "Idle", StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(processName, "System Idle Process", StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Check if a process is a Windows system process
        /// </summary>
        public static bool IsWindowsSystemProcess(string processName)
        {
            return SystemProcesses.Contains(processName) ||
                   SystemCritical.Contains(processName);
        }

        /// <summary>
        /// Check if a process is a security process
        /// </summary>
        public static bool IsSecurityProcess(string processName)
        {
            return SecurityProcesses.Contains(processName);
        }

        /// <summary>
        /// Check if a process is a hardware driver component.
        /// Combines the curated list with a naming heuristic so renamed vendor binaries are still
        /// recognised as drivers (failing "safe" here is the correct direction to fail).
        /// </summary>
        public static bool IsDriverProcess(string processName)
        {
            if (string.IsNullOrWhiteSpace(processName))
                return false;

            if (DriverProcesses.Contains(processName))
                return true;

            var name = processName.ToLowerInvariant();
            if (name.EndsWith(".exe", StringComparison.Ordinal))
                name = name[..^4];

            return LooksLikeDriver(name, string.Empty);
        }

        /// <summary>
        /// Get the category of a process.
        ///
        /// The order of the checks matters. Launchers, updaters, cloud clients and telemetry are
        /// tested *before* games, because a store client is not a game and mislabelling it would
        /// make Game Mode close the wrong thing. Matching is done on whole name tokens or on
        /// distinctive path segments - never on loose substrings, which produced false positives
        /// such as "diagtrack" matching "ac".
        /// </summary>
        public static ProcessCategory GetProcessCategory(string processName, string processPath, bool isService)
        {
            var name = (processName ?? string.Empty).ToLowerInvariant();
            var displayName = name.EndsWith(".exe", StringComparison.Ordinal) ? name[..^4] : name;
            var path = (processPath ?? string.Empty).ToLowerInvariant();

            // 1. Absolute protection first.
            if (SystemCritical.Contains(processName))
                return ProcessCategory.Critical;

            if (SecurityProcesses.Contains(processName) || LooksLikeSecurity(name, path))
                return ProcessCategory.Security;

            if (IsDriverProcess(processName) || LooksLikeDriver(name, path))
                return ProcessCategory.Driver;

            // 2. Windows own components.
            if (SystemProcesses.Contains(processName) || LooksLikeWindowsComponent(path))
                return ProcessCategory.System;

            // 3. Store clients and launchers (checked before games on purpose).
            if (LooksLikeLauncher(displayName, path))
                return ProcessCategory.Launcher;

            // 4. Self-updaters.
            if (LooksLikeUpdater(displayName))
                return ProcessCategory.Updater;

            // 5. Cloud synchronisation.
            if (LooksLikeCloudSync(displayName, path))
                return ProcessCategory.CloudSync;

            // 6. Telemetry / diagnostics.
            if (LooksLikeTelemetry(displayName, path))
                return ProcessCategory.Telemetry;

            // 7. Games (strict matching).
            if (LooksLikeGame(displayName, path))
                return ProcessCategory.Game;

            // 8. Services that are not Windows services are third-party software.
            if (isService)
                return ProcessCategory.BackgroundApplication;

            // 9. Anything else is something the user started.
            return ProcessCategory.UserApplication;
        }

        #region Classification helpers

        private static bool ContainsToken(string displayName, string token)
        {
            // Whole-name or hyphen-separated token match, so "steam" matches "steam" and
            // "steamwebhelper" but "ac" never matches "diagtrack".
            if (displayName.Equals(token, StringComparison.Ordinal))
                return true;

            return displayName.StartsWith(token, StringComparison.Ordinal) ||
                   displayName.EndsWith(token, StringComparison.Ordinal) ||
                   displayName.Contains("-" + token, StringComparison.Ordinal) ||
                   displayName.Contains(token + "-", StringComparison.Ordinal);
        }

        private static bool ContainsAny(string haystack, params string[] needles)
        {
            foreach (var needle in needles)
            {
                if (haystack.Contains(needle, StringComparison.Ordinal))
                    return true;
            }

            return false;
        }

        private static bool LooksLikeSecurity(string name, string path)
        {
            if (ContainsAny(name, "defender", "mpcmdrun", "msmpeng", "nissrv", "securityhealth",
                                  "wscsvc", "wscui", "firewall", "mpsSvc".ToLowerInvariant()))
                return true;

            return ContainsAny(path, "\\windows defender\\", "\\windows security\\",
                                     "\\antivirus\\", "\\security\\");
        }

        private static bool LooksLikeDriver(string name, string path)
        {
            // Vendor shorthands that only ever belong to hardware drivers.
            if (ContainsAny(name, "rtk", "realtek", "nvidia", "nvcontainer", "nvdisplay", "ati2ev",
                                  "atiesr", "atiecl", "amdlog", "igfx", "intelhaxm", "synTP".ToLowerInvariant(),
                                  "etdctrl", "elan", "bcmwl", "killer", "thunderbolt", "iaStor".ToLowerInvariant()))
                return true;

            return ContainsAny(path, "\\system32\\drivers\\", "\\oemdrv\\");
        }

        private static bool LooksLikeWindowsComponent(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;

            return ContainsAny(path, "\\windows\\system32\\", "\\windows\\syswow64\\",
                                     "\\windows\\systemapps\\", "\\windows\\winsxs\\");
        }

        private static bool LooksLikeLauncher(string displayName, string path)
        {
            if (ContainsAny(displayName, "steamwebhelper", "steamservice", "steamerrorreporter"))
                return true;

            if (ContainsToken(displayName, "steam"))
                return true;

            if (ContainsAny(displayName, "epicgameslauncher", "epicwebhelper", "ealauncher", "eadesktop",
                                          "origin", "uplay", "ubisoftconnect", "galaxyclient", "goggalaxy",
                                          "battle.net", "blizzard", "riotclient", "rockstarservice",
                                          "socialclub", "bethesdalauncher", "playnite"))
                return true;

            return ContainsAny(path, "\\steamapps\\", "\\epic games\\launcher\\",
                                     "\\electronic arts\\", "\\ubisoft\\", "\\riot games\\");
        }

        private static bool LooksLikeUpdater(string displayName)
        {
            return ContainsAny(displayName, "update", "updater", "upgrade", "autoupdate", "checkupdate",
                                          "patch", "splash", "preload", "installer", "setup");
        }

        private static bool LooksLikeCloudSync(string displayName, string path)
        {
            if (ContainsAny(displayName, "onedrive", "dropbox", "googledrive", "googleDrivefs".ToLowerInvariant(),
                                          "nextcloud", "owncloud", "icloud", "megasync", "pcloud",
                                          "backblaze", "syncthing", "boxsync"))
                return true;

            return ContainsAny(path, "\\microsoft\\onedrive\\", "\\dropbox\\",
                                     "\\google\\drive\\", "\\nextcloud\\");
        }

        private static bool LooksLikeTelemetry(string displayName, string path)
        {
            if (ContainsAny(displayName, "diagtrack", "dmwappushservice", "telemetry", "ceip",
                                          "compattelrunner", "devicecensus", "feedback", "wermgr",
                                          "sqmclient"))
                return true;

            return false;
        }

        private static bool LooksLikeGame(string displayName, string path)
        {
            // Distinctive path segments are the strongest signal.
            if (ContainsAny(path, "\\steamapps\\common\\", "\\games\\", "\\game\\",
                                  "\\epic games\\", "\\riot games\\", "\\battle.net\\",
                                  "\\rockstar games\\", "\\gog galaxy\\games\\"))
                return true;

            // Engine markers used by shipped game binaries.
            if (ContainsAny(displayName, "unityplayer", "unrealshipping", "shipping-win64"))
                return true;

            // Curated engine/executable names. Kept explicit to avoid substring false positives.
            string[] knownGameExecutables =
            {
                "valorant", "fortnitemac", "fortniteshipping", "apex_legends", "r5apex",
                "gtav", "gta5", "rdr2", "minecraft", "javaw", "wow", "wowclassic",
                "overwatch", "diablo", "starcraft", "hearthstone", "dota2", "csgo", "cs2",
                "pubg", "destiny2", "thedivision", "farcry", "watchdogs", "rainbowsix",
                "forzahorizon", "haloinfinite", "gearsofwar", "fallout", "skyrim",
                "elderscrolls", "cyberpunk", "witcher3", "hogwartslegacy", "eldenring",
                "leagueclient", "league of legends", "genshinimpact", "robloxplayerbeta"
            };

            foreach (var executable in knownGameExecutables)
            {
                if (displayName.Equals(executable, StringComparison.Ordinal) ||
                    displayName.StartsWith(executable, StringComparison.Ordinal))
                    return true;
            }

            return false;
        }

        #endregion

        /// <summary>
        /// Get the risk level of a process
        /// </summary>
        public static RiskLevel GetProcessRiskLevel(string processName, ProcessCategory category)
        {
            // Critical processes are always critical risk
            if (SystemCritical.Contains(processName))
                return RiskLevel.Critical;

            // Security processes are critical
            if (SecurityProcesses.Contains(processName))
                return RiskLevel.Critical;

            // Driver processes are high risk
            if (DriverProcesses.Contains(processName))
                return RiskLevel.High;

            // Windows system processes are high risk
            if (SystemProcesses.Contains(processName))
                return RiskLevel.High;

            // Services are medium risk
            if (category == ProcessCategory.System)
                return RiskLevel.Medium;

            // Security category is critical
            if (category == ProcessCategory.Security)
                return RiskLevel.Critical;

            // Driver category is high risk
            if (category == ProcessCategory.Driver)
                return RiskLevel.High;

            // Critical category is critical
            if (category == ProcessCategory.Critical)
                return RiskLevel.Critical;

            // Game processes are low risk (user can close them)
            if (category == ProcessCategory.Game)
                return RiskLevel.Low;

            // Launcher processes are medium risk
            if (category == ProcessCategory.Launcher)
                return RiskLevel.Medium;

            // Updater processes are medium risk
            if (category == ProcessCategory.Updater)
                return RiskLevel.Medium;

            // Cloud sync processes are medium risk
            if (category == ProcessCategory.CloudSync)
                return RiskLevel.Medium;

            // Telemetry processes are low risk
            if (category == ProcessCategory.Telemetry)
                return RiskLevel.Low;

            // User applications are low risk
            if (category == ProcessCategory.UserApplication)
                return RiskLevel.Low;

            // Background applications are low risk
            if (category == ProcessCategory.BackgroundApplication)
                return RiskLevel.Low;

            // Default to medium risk
            return RiskLevel.Medium;
        }

        #endregion
    }
}
