using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using ServerHelp.Core;
using ServerHelp.Mc;
using ServerHelp.Net;
using ServerHelp.Tunnel;

namespace ServerHelp
{
    /// <summary>
    /// Headless checks that run before anything is shipped: every configuration the app can generate
    /// is written out and handed to the real sing-box binary with <c>check</c>. A schema mistake in
    /// the tunnel config would otherwise only appear on the user's machine, in the middle of a game.
    ///
    /// Exit code 0 = everything passed. Run with: ServerHelp.exe --selftest
    /// </summary>
    internal static class SelfTest
    {
        public static int Run(string[] args)
        {
            var failures = new List<string>();
            var passes = new List<string>();
            var output = new List<string>();

            Console.WriteLine("Server Help self test");
            output.Add("Server Help self test");

            try
            {
                AppPaths.EnsureAll();

                // the engine travels inside the exe, exactly as it does for a user; unpack it first
                // so the configurations can be validated by the real thing
                var runner = new SingBoxRunner();
                string engineError;
                runner.EnsureBinaries(false, null, out engineError);
                string engine = File.Exists(AppPaths.SingBoxExe) ? AppPaths.SingBoxExe : "MISSING - " + engineError;
                Console.WriteLine("engine: " + engine);
                output.Add("engine: " + engine);
                output.Add("");

                RunChecks(failures, passes);
            }
            catch (Exception ex)
            {
                // a self test that crashes must still say why: a build failure with no message is
                // worse than no self test at all
                failures.Add("the self test itself failed: " + ex.GetType().Name + " " + ex.Message);
                int line = 0;
                try
                {
                    var frame = new System.Diagnostics.StackTrace(ex, true).GetFrame(1);
                    if (frame != null) line = frame.GetFileLineNumber();
                }
                catch { }
                failures.Add("at line " + line);
            }

            output.Add("");
            foreach (string line in passes) output.Add("  ok    " + line);
            foreach (string line in failures) output.Add("  FAIL  " + line);
            output.Add("");
            output.Add(passes.Count + " passed, " + failures.Count + " failed");

            // The app is a window application, so in a headless build its stdout is not attached to
            // anything. The report is written to a file as well, which is what the build reads.
            try
            {
                AppPaths.EnsureAll();
                File.WriteAllLines(AppPaths.SelfTestReport, output.ToArray(), new UTF8Encoding(false));
            }
            catch { }
            foreach (string line in output)
            {
                Console.WriteLine(line);
            }
            return failures.Count == 0 ? 0 : 1;
        }

        /// <summary>Every check, with each group guarded so one broken check cannot hide the rest.</summary>
        private static void RunChecks(List<string> failures, List<string> passes)
        {
            Guard("both languages", failures, delegate { CheckLanguages(failures, passes); });
            Guard("the connection parser", failures, delegate { CheckParser(failures, passes); });
            Guard("the connection model", failures, delegate { CheckConnectionModel(failures, passes); });
            Guard("the connection list file", failures, delegate { CheckListFile(failures, passes); });
            Guard("the settings model", failures, delegate { CheckSettings(failures, passes); });
            Guard("the quality numbers", failures, delegate { CheckQuality(failures, passes); });
            Guard("the launch plan", failures, delegate { CheckProfiler(failures, passes); });
            Guard("the launcher folder", failures, delegate { CheckVersions(failures, passes); });
            Guard("the tester", failures, delegate { CheckTesterAnswers(failures, passes); });
            Guard("the subscription reader", failures, delegate { CheckSubscription(failures, passes); });
            Guard("the OpenVPN profile", failures, delegate { CheckOvpn(failures, passes); });
            Guard("the generated tunnel configurations", failures, delegate { CheckConfigs(failures, passes); });
            Guard("the route optimiser", failures, delegate { CheckOptimizer(failures, passes); });
        }

        private static void Guard(string what, List<string> failures, Action body)
        {
            try { body(); }
            catch (Exception ex) { failures.Add(what + " threw " + ex.GetType().Name + ": " + ex.Message); }
        }

        private static void Expect(bool condition, string what, List<string> failures, List<string> passes)
        {
            if (condition) { if (passes.Count < 60) passes.Add(what); }
            else failures.Add(what);
        }

        /// <summary>
        /// The app promises both languages. This proves the switch really reaches the text, the
        /// direction and the digits, then puts the previous language back.
        /// </summary>
        private static void CheckLanguages(List<string> failures, List<string> passes)
        {
            string original = L.Lang;
            try
            {
                L.SetLang(L.En);
                Expect(L.T("فارسی", "English") == "English" && !L.IsRtl,
                       "English mode answers in English and is left to right", failures, passes);
                Expect(L.N(42) == "42", "English mode uses Western digits", failures, passes);

                L.SetLang(L.Fa);
                Expect(L.T("فارسی", "English") == "فارسی" && L.IsRtl,
                       "Persian mode answers in Persian and is right to left", failures, passes);
                Expect(L.N(42) == "۴۲", "Persian mode uses Persian digits", failures, passes);

                // every connection kind must be named in both languages: the table has no room for
                // an empty cell, and a missing translation is the usual way one appears
                int named = 0;
                foreach (ConnectionKind kind in new ConnectionKind[]
                         {
                             ConnectionKind.Warp, ConnectionKind.Dns, ConnectionKind.Socks5, ConnectionKind.Http,
                             ConnectionKind.Mtproto, ConnectionKind.WireGuard, ConnectionKind.SingBoxOutbound,
                             ConnectionKind.SingBoxConfig, ConnectionKind.OpenVpn
                         })
                {
                    ConnectionKindInfo info = ConnectionKindInfo.Of(kind);
                    if (info.Kind != kind) failures.Add("kind " + kind + " has no description of its own");
                    L.SetLang(L.En);
                    string english = info.Title;
                    L.SetLang(L.Fa);
                    string persian = info.Title;
                    if (english.Length == 0 || persian.Length == 0 || english == persian)
                        failures.Add("kind " + kind + " is not named in both languages");
                    else named++;
                }
                if (named == 9) passes.Add("every connection kind is named in both languages");
            }
            finally
            {
                L.SetLang(original);
            }
        }

        /// <summary>
        /// The connection model: every kind must say what it is missing, survive a save/load round
        /// trip with all of its fields, and produce a usable outbound or endpoint when it is complete.
        /// </summary>
        private static void CheckConnectionModel(List<string> failures, List<string> passes)
        {
            var kinds = new ConnectionKind[]
            {
                ConnectionKind.Warp, ConnectionKind.Dns, ConnectionKind.Socks5, ConnectionKind.Http,
                ConnectionKind.Mtproto, ConnectionKind.WireGuard, ConnectionKind.SingBoxOutbound,
                ConnectionKind.SingBoxConfig, ConnectionKind.OpenVpn
            };

            // a fresh entry must never look complete when it needs fields
            int complaining = 0;
            foreach (ConnectionKind kind in kinds)
            {
                ConnectionEntry fresh = ConnectionEntry.Create("test " + kind, kind);
                if (fresh.Missing().Length > 0 || kind == ConnectionKind.Warp) complaining++;
            }
            Expect(complaining == kinds.Length - 1, "an empty entry reports what it is missing", failures, passes);

            // a filled entry must survive save/load unchanged
            var filled = ConnectionEntry.Create("filled", ConnectionKind.Socks5);
            filled.Host = "203.0.113.9";
            filled.Port = 1080;
            filled.User = "user";
            filled.Password = "pass";
            filled.FragmentTls = true;
            filled.LastDelayMs = 42;
            filled.LastJitterMs = 6;
            filled.LastLossPercent = 0;
            filled.LastSpeedKbps = 512;
            filled.LastPingMin = 38;
            filled.LastPingMax = 55;
            filled.LastTestUtc = "12:00:00";

            var writer = new JsonWriter(false);
            filled.WriteTo(writer);
            ConnectionEntry back = ConnectionEntry.Read(Json.ParseObject(writer.ToString()));
            Expect(back != null && back.Host == filled.Host && back.Port == 1080 && back.User == "user" &&
                   back.FragmentTls && back.LastJitterMs == 6 && back.LastSpeedKbps == 512 &&
                   back.LastPingMin == 38 && back.LastPingMax == 55 && back.LastLossPercent == 0,
                   "a connection survives a save and load with every field", failures, passes);
            Expect(back.SameConfig(filled), "the round trip keeps the entry equal to itself", failures, passes);
            Expect(back.QualityText().Length > 0, "the measured quality is readable again after loading",
                   failures, passes);

            // outbounds and endpoints
            var socks = ConnectionEntry.Create("s", ConnectionKind.Socks5);
            socks.Host = "203.0.113.4"; socks.Port = 1080; socks.FragmentTls = true;
            ConnectionRoute.FragmentTlsByDefault = false;
            Dictionary<string, object> outbound = ConnectionRoute.BuildOutbound(socks, "t1");
            Expect(Json.GetStr(outbound, "type", "") == "socks" && Json.GetStr(outbound, "tag", "") == "t1",
                   "a SOCKS5 entry becomes a socks outbound", failures, passes);

            // fragmentation only lands on an outbound that actually speaks TLS
            var vless = ConnectionEntry.Create("v", ConnectionKind.SingBoxOutbound);
            vless.Config = "{\"type\":\"vless\",\"server\":\"example.org\",\"server_port\":443,\"uuid\":\"00000000-0000-0000-0000-000000000000\",\"tls\":{\"enabled\":true,\"server_name\":\"example.org\"}}";
            vless.FragmentTls = true;
            Dictionary<string, object> tlsOutbound = ConnectionRoute.BuildOutbound(vless, "t2");
            var tls = Json.Obj(Json.Get(tlsOutbound, "tls"));
            Expect(tls != null && Json.GetBool(tls, "fragment", false) && Json.GetBool(tls, "record_fragment", false),
                   "TLS fragmentation is written into the handshake of an outbound", failures, passes);

            var plain = ConnectionEntry.Create("p", ConnectionKind.Socks5);
            plain.Host = "203.0.113.4"; plain.Port = 1080; plain.FragmentTls = true;
            var plainOutbound = ConnectionRoute.BuildOutbound(plain, "t3");
            Expect(Json.Get(plainOutbound, "tls") == null,
                   "a route without TLS is left alone when fragmentation is on", failures, passes);

            // every tag must be unique: two entries of the same kind would collide in the config
            var first = ConnectionEntry.Create("one", ConnectionKind.Socks5);
            first.Host = "203.0.113.1"; first.Port = 1080;
            var second = ConnectionEntry.Create("two", ConnectionKind.Socks5);
            second.Host = "203.0.113.2"; second.Port = 1080;
            Expect(ConnectionRoute.TagFor(first) != ConnectionRoute.TagFor(second),
                   "two connections of the same kind get different tags", failures, passes);

            // the wireguard endpoint needs its keys, and must say so instead of throwing something odd
            var wg = ConnectionEntry.Create("wg", ConnectionKind.WireGuard);
            wg.PeerHost = "198.51.100.4"; wg.PeerPort = 2408;
            Expect(wg.Missing().Contains("client address") || wg.Missing().Length > 0,
                   "an incomplete WireGuard entry lists what is missing", failures, passes);
            wg.Address = "172.16.0.2/32";
            wg.Secret = new string('A', 44);
            wg.PeerPublicKey = new string('B', 44);
            Dictionary<string, object> endpoint = ConnectionRoute.BuildEndpoint(wg, "wg-1");
            Expect(Json.GetStr(endpoint, "type", "") == "wireguard" && Json.Get(endpoint, "peers") != null,
                   "a complete WireGuard entry becomes an endpoint", failures, passes);
        }

        /// <summary>Saving the list and reading it back is how a user moves machines: it must round trip.</summary>
        private static void CheckListFile(List<string> failures, List<string> passes)
        {
            var list = new List<ConnectionEntry>();
            var socks = ConnectionEntry.Create("home", ConnectionKind.Socks5);
            socks.Host = "203.0.113.5"; socks.Port = 1080;
            var dns = ConnectionEntry.Create("resolver", ConnectionKind.Dns);
            dns.DnsUrl = "tls://1.1.1.1:853";
            var ovpn = ConnectionEntry.Create("bear", ConnectionKind.OpenVpn);
            ovpn.Config = "client\ndev tun\nproto udp\nremote 198.51.100.9 443\n";
            list.Add(socks);
            list.Add(dns);
            list.Add(ovpn);

            string json = ConnectionParser.SerializeList(list);
            string error;
            List<ConnectionEntry> back = ConnectionParser.ParseListFile(json, out error);
            Expect(back.Count == 3, "the saved list comes back with all three entries", failures, passes);
            Expect(error.Length == 0, "reading the list file reports no error", failures, passes);
            bool kindsOk = back.Count == 3 && back[0].Kind == ConnectionKind.Socks5 &&
                           back[1].Kind == ConnectionKind.Dns && back[2].Kind == ConnectionKind.OpenVpn;
            Expect(kindsOk, "the kinds survive the list file", failures, passes);

            // a bare array is what other tools export
            string bare = "[{\"name\":\"x\",\"kind\":2,\"host\":\"203.0.113.6\",\"port\":1080}]";
            List<ConnectionEntry> fromArray = ConnectionParser.ParseListFile(bare, out error);
            Expect(fromArray.Count == 1 && fromArray[0].Host == "203.0.113.6",
                   "a bare JSON array of connections is accepted", failures, passes);

            // and the import blob: every line becomes one entry, bad lines are reported not thrown
            var blob = ConnectionParser.ParseBlob("203.0.113.7:1080\n\ngarbage line here\n", out List<string> problems);
            Expect(blob.Count == 1 && problems.Count >= 1,
                   "a mixed paste imports what it can and reports the rest", failures, passes);
        }

        /// <summary>A subscription is a base64 list of share links; both shapes must import.</summary>
        private static void CheckSubscription(List<string> failures, List<string> passes)
        {
            string links = "vless://11111111-1111-1111-1111-111111111111@203.0.113.8:443?type=tcp&security=tls&sni=example.org#node-1" + "\n" +
                           "trojan://password@203.0.113.9:443#node-2" + "\n";
            string encoded = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(links));

            List<string> problems;
            List<ConnectionEntry> decoded = Subscription.Parse(encoded, out problems);
            Expect(decoded.Count == 2, "a base64 subscription becomes two connections", failures, passes);

            List<ConnectionEntry> plainText = Subscription.Parse(links, out problems);
            Expect(plainText.Count == 2, "an already decoded subscription is accepted too", failures, passes);

            List<ConnectionEntry> empty = Subscription.Parse("", out problems);
            Expect(empty.Count == 0, "an empty subscription adds nothing instead of throwing", failures, passes);

            // fetching is where a user's typo lands: it has to come back as a message, not a crash
            Subscription.FetchResult noUrl = Subscription.Fetch("", 500, null);
            Expect(noUrl != null && !noUrl.Ok && noUrl.Error.Length > 0,
                   "an empty subscription address is reported instead of fetched", failures, passes);
            Subscription.FetchResult badUrl = Subscription.Fetch("this is not an address", 500, null);
            Expect(badUrl != null && !badUrl.Ok && badUrl.Error.Length > 0,
                   "an address that cannot be parsed is reported instead of fetched", failures, passes);
        }

        /// <summary>
        /// The settings are the memory of the whole connections section: a field that is written to
        /// disk but never read back (or the other way round) makes a switch look broken. The round
        /// trip below is done in memory, without touching the user's own file.
        /// </summary>
        private static void CheckSettings(List<string> failures, List<string> passes)
        {
            AppSettings wanted = AppSettings.Default();
            wanted.Language = L.En;
            wanted.Nickname = "tester";
            wanted.Tunnel = TunnelMode.DnsOnly;
            wanted.PinnedConnection = "home";
            wanted.PinnedChainHop = "work";
            wanted.DnsThroughTunnel = false;
            wanted.OptimiseChains = 7;
            wanted.FragmentTls = true;
            wanted.RetestMinutes = 45;
            wanted.ConnectionTestTimeoutMs = 4500;
            wanted.KillSwitch = true;
            wanted.ProxyFailover = false;
            wanted.AllowRouteFallback = false;
            wanted.ConfirmTuning = false;
            wanted.Servers.Clear();
            // the defaults already carry sample connections; the round trip is about ours
            wanted.Connections.Clear();
            var server = new ServerProfile();
            server.Name = "SMP";
            server.Host = "smp3.mcsh.io";
            server.Port = 11005;
            server.DirectIp = "163.5.201.3";
            server.PreferDomain = true;
            wanted.Servers.Add(server);
            var entry = ConnectionEntry.Create("home", ConnectionKind.Socks5);
            entry.Host = "203.0.113.5";
            entry.Port = 1080;
            entry.FragmentTls = true;
            entry.Enabled = false;
            wanted.Connections.Add(entry);

            AppSettings back = SettingsStore.Parse(SettingsStore.ToJson(wanted));
            Expect(back != null, "the settings can be written and read back", failures, passes);
            if (back == null) return;

            Expect(back.Language == L.En && back.Nickname == "tester" && back.Tunnel == TunnelMode.DnsOnly,
                   "the language, the nickname and the tunnel mode survive a save and load", failures, passes);
            Expect(back.PinnedConnection == "home" && back.PinnedChainHop == "work" && !back.DnsThroughTunnel &&
                   back.OptimiseChains == 7 && back.FragmentTls && back.RetestMinutes == 45 &&
                   back.ConnectionTestTimeoutMs == 4500 && back.KillSwitch &&
                   !back.ProxyFailover && !back.AllowRouteFallback,
                   "every connection setting survives a save and load", failures, passes);
            Expect(back.Servers.Count == 1 && back.Servers[0].Host == "smp3.mcsh.io" &&
                   back.Servers[0].Port == 11005 && back.Servers[0].PreferDomain &&
                   back.Servers[0].DirectIp == "163.5.201.3",
                   "the server list survives a save and load", failures, passes);
            Expect(wanted.Connections.Count == 1, "the test starts from exactly one connection", failures, passes);
            Expect(back.Connections.Count == 1, "one connection comes back from the settings file", failures, passes);
            if (back.Connections.Count == 1)
            {
                ConnectionEntry re = back.Connections[0];
                Expect(re.Name == "home" && re.Kind == ConnectionKind.Socks5,
                       "the name and the kind of a connection survive a save and load", failures, passes);
                Expect(re.Host == "203.0.113.5" && re.Port == 1080,
                       "the address of a connection survives a save and load", failures, passes);
                Expect(re.FragmentTls, "the per connection TLS fragmentation survives a save and load",
                       failures, passes);
                Expect(!re.Enabled, "a connection that was switched off stays off after a save and load",
                       failures, passes);
            }
            Expect(SettingsStore.Parse("{\"pinnedConnection\":null,\"retestMinutes\":9999}").RetestMinutes == 720,
                   "a nonsense retest interval is clamped instead of trusted", failures, passes);
            Expect(!back.ConfirmTuning && AppSettings.Default().ConfirmTuning,
                   "the \"ask before tuning\" switch is on by default and survives a save and load",
                   failures, passes);
        }

        /// <summary>
        /// The switches on the optimisation tab have to match the command line the game is started
        /// with: with "JVM tuning flags" switched off the plan changes the memory and nothing else, and
        /// the plan the user reads says exactly that.
        /// </summary>
        private static void CheckProfiler(List<string> failures, List<string> passes)
        {
            var version = new McVersion();
            version.Id = "1.20.1";
            version.Type = "release";
            version.Folder = Path.Combine(Path.GetTempPath(), "serverhelp-selftest-version");

            AppSettings settings = AppSettings.Default();
            settings.UseAikarFlags = true;
            settings.OpenGlPipeline = false;
            GamePlan on = GameProfiler.Build(version, settings, null, "", 17, new List<string>());
            bool collector = false, ipv4 = false;
            foreach (string flag in on.Flags)
            {
                if (flag.StartsWith("-XX:", StringComparison.Ordinal)) collector = true;
                if (flag == "-Djava.net.preferIPv4Stack=true") ipv4 = true;
            }
            Expect(collector && on.G1 && ipv4,
                   "the launch plan carries the collector and the IPv4 flag while the switches are on",
                   failures, passes);
            Expect(on.Summary().Contains("G1GC"),
                   "the plan that is shown names the collector the game will be started with", failures, passes);

            settings.UseAikarFlags = false;
            GamePlan off = GameProfiler.Build(version, settings, null, "", 17, new List<string>());
            Expect(off.Flags.Count == 0 && !off.G1,
                   "with the JVM switches off the plan changes the memory and nothing else", failures, passes);
            Expect(!off.Summary().Contains("G1GC") && off.Summary().Contains(L.T("فقط حافظه", "only the memory")),
                   "the plan says out loud that only the memory is tuned", failures, passes);

            settings.OpenGlPipeline = true;
            GamePlan opengl = GameProfiler.Build(version, settings, null, "", 17, new List<string>());
            bool pipeline = false;
            foreach (string flag in opengl.Flags) if (flag == "-Dsun.java2d.opengl=true") pipeline = true;
            Expect(pipeline && opengl.Flags.Count == 1,
                   "the separate OpenGL switch still works with the tuning flags off", failures, passes);
        }

        /// <summary>
        /// Reading the launcher folder: the version list, the java version each one needs, and the name
        /// the launcher remembers. Everything runs against files written here, so no launcher and no
        /// network are needed.
        /// </summary>
        private static void CheckVersions(List<string> failures, List<string> passes)
        {
            string root = Path.Combine(Path.GetTempPath(), "serverhelp-selftest-mc");
            string versions = Path.Combine(root, "versions");
            try
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
                Directory.CreateDirectory(Path.Combine(versions, "1.20.1"));
                Directory.CreateDirectory(Path.Combine(versions, "1.7.10-forge"));
                File.WriteAllText(Path.Combine(versions, "1.20.1", "1.20.1.json"),
                    "{\"id\":\"1.20.1\",\"type\":\"release\",\"javaVersion\":{\"majorVersion\":17}," +
                    "\"assetIndex\":{\"id\":\"5\"}}");
                File.WriteAllText(Path.Combine(versions, "1.20.1", "1.20.1.jar"), "jar");
                // a folder with a jar but no json: it has to be listed, and marked as not launchable
                File.WriteAllText(Path.Combine(versions, "1.7.10-forge", "1.7.10-forge.jar"), "jar");
                File.WriteAllText(Path.Combine(root, "launcher_profiles.json"),
                    "{\"authenticationDatabase\":{\"a1\":{\"username\":\"player@example.com\"," +
                    "\"profiles\":{\"p1\":{\"displayName\":\"Crafty_One\"}}}}," +
                    "\"profiles\":{\"p2\":{\"name\":\"Latest release\"}}}");
            }
            catch (Exception ex) { Log.Debug("selftest fixture: " + ex.Message); }

            Expect(VersionScanner.DetectGameDir(root) == root,
                   "the game folder is found when it carries a versions folder", failures, passes);
            Expect(VersionScanner.ResolveVersionsDir(root, versions) == versions,
                   "a versions folder that was picked by hand is used as it is", failures, passes);

            List<McVersion> list = VersionScanner.Scan(versions);
            Expect(list.Count == 2, "both version folders in the folder are listed", failures, passes);
            McVersion release = null, bare = null;
            foreach (McVersion v in list)
            {
                if (v.Id == "1.20.1") release = v;
                if (v.Id == "1.7.10-forge") bare = v;
            }
            Expect(release != null && release.HasJson && release.Type == "release" &&
                   release.RequiredJavaMajor == 17 && release.AssetIndex == "5" && release.JarSize == 3,
                   "the version json gives the id, the java version and the asset index", failures, passes);
            Expect(bare != null && !bare.HasJson && bare.Error.Length > 0,
                   "a folder without a version json is listed and marked as not launchable", failures, passes);

            Expect(VersionScanner.GuessNickname(root) == "Crafty_One",
                   "the name comes from the account and not from a launch profile label", failures, passes);

            string labelsOnly = Path.Combine(Path.GetTempPath(), "serverhelp-selftest-labels");
            try
            {
                Directory.CreateDirectory(labelsOnly);
                File.WriteAllText(Path.Combine(labelsOnly, "launcher_profiles.json"),
                    "{\"profiles\":{\"p1\":{\"name\":\"Latest release\"},\"p2\":{\"name\":\"1.20.1-Fabric\"}}}");
            }
            catch { }
            Expect(VersionScanner.GuessNickname(labelsOnly) == "",
                   "launch profile labels are never mistaken for the player's name", failures, passes);
        }

        /// <summary>The numbers a route is judged by, checked without touching the network.</summary>
        private static void CheckQuality(List<string> failures, List<string> passes)
        {
            var steady = new QualityResult();
            steady.Samples = 5; steady.Lost = 0; steady.MinMs = 38; steady.MaxMs = 46; steady.AvgMs = 41; steady.JitterMs = 4;
            Expect(steady.Ok && steady.LossPercent == 0 && steady.Grade() == L.T("عالی", "excellent"),
                   "a steady 41 ms run is graded excellent", failures, passes);
            Expect(steady.Summary().Contains(L.N(41)) && steady.Summary().Contains(L.N(0)),
                   "the quality line shows the average and the loss in the reader's digits", failures, passes);

            var lossy = new QualityResult();
            lossy.Samples = 5; lossy.Lost = 2; lossy.MinMs = 40; lossy.MaxMs = 40; lossy.AvgMs = 40; lossy.JitterMs = 0;
            Expect(lossy.LossPercent == 40 && lossy.Grade() == L.T("پرافت", "lossy"),
                   "two lost samples out of five are reported as 40% loss", failures, passes);

            var rubber = new QualityResult();
            rubber.Samples = 5; rubber.Lost = 0; rubber.MinMs = 30; rubber.MaxMs = 200; rubber.AvgMs = 95; rubber.JitterMs = 60;
            Expect(rubber.Grade() == L.T("لرزان", "unstable"),
                   "a wide spread is called unstable even when the average looks fine", failures, passes);

            var dead = new QualityResult();
            dead.Detail = "connection refused";
            Expect(!dead.Ok && dead.Grade() == L.T("بد", "bad") && dead.Summary() == "connection refused",
                   "a run that never answered keeps the reason it failed", failures, passes);
        }

        /// <summary>
        /// The table and the connection dialog call the tester on a worker thread that has no handler
        /// around it, so a malformed entry has to come back as a failed result: an exception used to
        /// leave the Test button disabled for the rest of the dialog's life.
        /// </summary>
        private static void CheckTesterAnswers(List<string> failures, List<string> passes)
        {
            ConnectionTestResult nothing = ConnectionTester.Test(null, "smp3.mcsh.io", 11005, 500, false);
            Expect(nothing != null && !nothing.Ok, "testing an empty entry answers instead of throwing", failures, passes);

            var incomplete = ConnectionEntry.Create("incomplete", ConnectionKind.Socks5);
            ConnectionTestResult missing = ConnectionTester.Test(incomplete, "smp3.mcsh.io", 11005, 500, false);
            Expect(missing != null && !missing.Ok && !missing.Deferred && missing.Detail.Length > 0,
                   "an entry with missing fields is incomplete, not deferred", failures, passes);

            var broken = ConnectionEntry.Create("broken", ConnectionKind.SingBoxOutbound);
            broken.Config = "{\"type\":\"vless\"";
            ConnectionTestResult bad = ConnectionTester.Test(broken, "smp3.mcsh.io", 11005, 500, false);
            Expect(bad != null && !bad.Ok, "a half written outbound config fails the test politely", failures, passes);

            var junk = ConnectionEntry.Create("junk", ConnectionKind.SingBoxConfig);
            junk.Config = "this is not json at all";
            ConnectionTestResult full = ConnectionTester.Test(junk, "smp3.mcsh.io", 11005, 500, false);
            Expect(full != null && !full.Ok, "a full config that is not JSON fails the test politely", failures, passes);

            var half = ConnectionEntry.Create("wg", ConnectionKind.WireGuard);
            half.PeerHost = "198.51.100.4";
            half.PeerPort = 2408;
            ConnectionTestResult wireguard = ConnectionTester.Test(half, "smp3.mcsh.io", 11005, 500, false);
            Expect(wireguard != null && !wireguard.Ok,
                   "a half filled WireGuard entry is reported, not attempted", failures, passes);

            // Inside the one minute budget a WireGuard or a full config is not started at all. That
            // has to be reported as "deferred", never as "does not work": the pinned route decision
            // reads exactly this flag, and getting it wrong throws the user's chosen route away.
            var ready = ConnectionEntry.Create("ready wg", ConnectionKind.WireGuard);
            ready.Address = "172.16.0.2/32";
            ready.Secret = new string('A', 44);
            ready.PeerPublicKey = new string('B', 44);
            ready.PeerHost = "198.51.100.4";
            ready.PeerPort = 2408;
            ConnectionTestResult deferred = ConnectionTester.Test(ready, "smp3.mcsh.io", 11005, 800, true);
            Expect(deferred != null && !deferred.Ok && deferred.Deferred,
                   "a route that is only brought up at launch says so instead of pretending to fail",
                   failures, passes);

            // the helpers a measurement leans on: which configs may be started at all, and how a
            // full config is moved to a free port without breaking its outbound
            Expect(ConnectionTester.HasTunInbound("{\"inbounds\":[{\"type\":\"tun\",\"tag\":\"t\"}]}"),
                   "a config with a TUN inbound is recognised", failures, passes);
            Expect(!ConnectionTester.HasTunInbound("{\"inbounds\":[{\"type\":\"socks\",\"listen_port\":1080}]}"),
                   "a config without a TUN inbound is not accused of one", failures, passes);
            Expect(!ConnectionTester.HasTunInbound("not json"), "an unreadable config is not a TUN config",
                   failures, passes);
            string moved = ConnectionTester.RewriteSocksPort(
                "{\"inbounds\":[{\"type\":\"socks\",\"listen_port\":1080}],\"outbounds\":[{\"type\":\"direct\"}]}", 22470);
            Expect(moved.Contains("22470") && moved.Contains("\"direct\"") && !moved.Contains("1080"),
                   "a full config is moved to a free port with its outbound intact", failures, passes);

            var fullConfig = ConnectionEntry.Create("full config", ConnectionKind.SingBoxConfig);
            fullConfig.Config = "{\"log\":{\"level\":\"warn\"}}";
            ConnectionTestResult deferredConfig = ConnectionTester.Test(fullConfig, "smp3.mcsh.io", 11005, 800, true);
            Expect(deferredConfig != null && !deferredConfig.Ok && deferredConfig.Deferred,
                   "a full config is reported as deferred inside the launch budget", failures, passes);

        }

        private static void CheckParser(List<string> failures, List<string> passes)
        {
            string error;
            var socks = ConnectionParser.ParseLine("1.2.3.4:1080", out error);
            Expect(socks != null && socks.Kind == ConnectionKind.Socks5 && socks.Host == "1.2.3.4" && socks.Port == 1080,
                   "plain host:port becomes a SOCKS5 proxy", failures, passes);

            var tg = ConnectionParser.ParseLine("tg://proxy?server=1.2.3.4&port=443&secret=dd0123456789abcdef0123456789abcdef", out error);
            Expect(tg != null && tg.Kind == ConnectionKind.Mtproto && tg.Port == 443,
                   "tg:// link becomes an MTProto entry", failures, passes);

            var dns = ConnectionParser.ParseLine("tls://1.1.1.1:853", out error);
            Expect(dns != null && dns.Kind == ConnectionKind.Dns, "tls:// becomes a DNS entry", failures, passes);

            var wg = ConnectionParser.ParseLine(
                "[Interface]\nPrivateKey = aGVsbG8=\nAddress = 172.16.0.2/32\n[Peer]\nPublicKey = d29ybGQ=\nEndpoint = 5.6.7.8:2408\n",
                out error);
            Expect(wg != null && wg.Kind == ConnectionKind.WireGuard && wg.PeerPort == 2408,
                   "a WireGuard ini becomes an entry", failures, passes);

            var many = ConnectionParser.ParseBlob("1.2.3.4:1080\n5.6.7.8:8080\n", out List<string> problems);
            Expect(many.Count == 2, "two lines become two entries", failures, passes);
        }

        private static void CheckOvpn(List<string> failures, List<string> passes)
        {
            string profile = SampleOvpn() + "cipher AES-256-CBC\nauth SHA256\nkey-direction 1\n" +
                             "tls-auth [inline] 1\n<ca>\n" + SampleCert() + "</ca>\n" +
                             "<tls-auth>\n" + SampleStaticKey() + "</tls-auth>\n";

            OvpnProfile parsed = OvpnProfile.Parse(profile, "");
            Expect(parsed.Ok && parsed.Host == "198.51.100.9" && parsed.Port == 443,
                   ".ovpn remote line becomes the endpoint", failures, passes);
            Expect(parsed.Network == "udp" && parsed.Auth == "SHA256" && parsed.KeyDirection == 1,
                   ".ovpn options are read (proto, auth, key-direction)", failures, passes);
            Expect(parsed.CaCert.Length > 0 && parsed.TlsAuthKey.Length > 0,
                   ".ovpn inline certificates are kept", failures, passes);
            Expect(parsed.NeedsCredentials, ".ovpn asks for an account when it needs one", failures, passes);

            Dictionary<string, object> endpoint = parsed.ToEndpoint("ovpn-1", "user@example.com", "secret");
            Expect(Json.GetStr(endpoint, "type", "") == "openvpn-client" &&
                   Json.GetStr(endpoint, "server", "") == "198.51.100.9" &&
                   Json.GetInt(endpoint, "server_port", 0) == 443,
                   ".ovpn turns into an openvpn-client endpoint", failures, passes);
            var tls = Json.Obj(Json.Get(endpoint, "tls"));
            Expect(tls != null && Json.Get(tls, "certificate") != null && Json.Get(tls, "control_wrap") != null,
                   "the endpoint carries the CA and the tls-auth key", failures, passes);

            string error;
            var entry = ConnectionParser.FromOvpn(profile, "bear-latvia.ovpn", out error);
            Expect(entry != null && entry.Kind == ConnectionKind.OpenVpn && entry.NeedsCredentials,
                   "an .ovpn paste becomes an OpenVPN connection entry", failures, passes);

            var blob = ConnectionParser.ParseBlob(profile, out List<string> problems);
            Expect(blob.Count == 1 && blob[0].Kind == ConnectionKind.OpenVpn,
                   "an .ovpn profile pasted among other lines stays one entry", failures, passes);
        }

        /// <summary>The head of a realistic .ovpn profile without the certificates.</summary>
        private static string SampleOvpn()
        {
            return "client\ndev tun\nproto udp\nremote 198.51.100.9 443\nresolv-retry infinite\n" +
                   "nobind\npersist-key\nremote-cert-tls server\ncomp-lzo no\nverb 3\nauth-user-pass\n";
        }

        /// <summary>A real certificate: the engine parses these fields, so a fake one must not be used.</summary>
        private static string SampleCert()
        {
            return "-----BEGIN CERTIFICATE-----\nMIIDJTCCAg2gAwIBAgIUJqjxjnPDCLJqRNbE4lhswgs6pTYwDQYJKoZIhvcNAQEL\nBQAwIjEgMB4GA1UEAwwXU2VydmVySGVscCBTZWxmIFRlc3QgQ0EwHhcNMjYxMDEy\nMTMwMTQ5WhcNMzYxMDA5MTMwMTQ5WjAiMSAwHgYDVQQDDBdTZXJ2ZXJIZWxwIFNl\nbGYgVGVzdCBDQTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANHP7E9K\nF5myT3bDzb0PhCJU6BAz+akbjun3GaB3hCsc9JiyKcNzzZoSssxdkz56EuADFdG7\nx3N+AZivtr81ooYckV/JdxzQSnWuGXYC5oF2+zj0Yy1/tQ7FkuAsYDeY4SZBObaW\nSZb7EGiBeC40zS5qH7ShYRipHRl98svWZpOaAmR6azy2uqAg1CakhAS09XKlMq0g\n58HiJry3E0VqflrFTgjrz+sAxdbFMnXBKtFW50l8IYBvlqVOlTuslX4co5VAVIpZ\nGrHuj4gY26Uz6FR4so70/UM+cHUWFq7w+VkeWp34sIHYHsrrlw07YQF28SVsAiHm\nAU8UgYajmlEfqZMCAwEAAaNTMFEwHQYDVR0OBBYEFHxpAvR6AMOFrDgUeezy5tnP\ngIAJMB8GA1UdIwQYMBaAFHxpAvR6AMOFrDgUeezy5tnPgIAJMA8GA1UdEwEB/wQF\nMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAFdVMdr2bfDTGrYub7VreBshDG2PA7Dd\nIIXqr9Aii2XY9SLpiU1r0fQ2+xvYAYIAKVIndWE4Gt46F6GO47eV5/7SXccMeTpf\nt0kkt9UV+vrPyVF8vf6ajET9tP7SaZRKPvSpmVvoAP38xfZOdHBpAQyoT8QVQ2QI\nS+Ng2IZMfcmIW/GFVonWBJru30wxHtZ3L61eAZ4z0YTPZZMo4GjWFejJnBtsGTWJ\n0aIn6ndEvztLikp/xIK41oQAKIzDoYpvlxPri/O8Y8FarjegqFBI8Uc42x9i0pHT\n1wpL3DUZUjjVmU7zApJ29/g02+1e98HCHA4+fFY5HMRo2cCg0odV7Qw=\n-----END CERTIFICATE-----\n";
        }

        private static string SampleStaticKey()
        {
            return "3d989cd1f5e5d405166a7666a053f54a\n2cfe83bb7c79beae2fed1d579f864c53\n4a833c0fc8d57e32dd60a97001d4a0d7\nf8d63f601969f671ff4bd21c8ac5a13e\n8ddc6ea3c50e08d4fa8802fefb7cc524\nfd49200fafc7952df846122134edf9cd\nb69b72120643177033344483d700578c\n4339e94315958dd7a16f408b59097f8d\nefe3f4eea0f19419b50bb71e7d2d9a57\n13d6d03e0a41c8d6c7198281c5c59769\n0e5270184b5bccf07640cb2e0b06e097\nb966bb0e7c5f2b2412db2d440ffd5e81\nfc0a8438d7c1871506ad5afa89d17f7f\n93c18e4d1ddce062327ef09899355200\nf45e14380d72e1c35c9523d53f236028\nf80b7e8ef48c9aa0b3617ea7490871e5\n";
        }

        private static void CheckConfigs(List<string> failures, List<string> passes)
        {
            var settings = new AppSettings();
            var server = new ServerProfile();
            server.Host = "smp3.mcsh.io";
            server.DirectIp = "163.5.201.3";
            server.Port = 11005;

            // ---- a plain proxy route with DNS through the tunnel
            var socks = ConnectionEntry.Create("home socks", ConnectionKind.Socks5);
            socks.Host = "203.0.113.7";
            socks.Port = 1080;

            var plan = new TunnelPlan();
            plan.IncludeTun = true;
            plan.ServerIps.Add("163.5.201.3");
            plan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(socks, "hop-1"));
            plan.MemberTags.Add("hop-1");
            plan.RouteTag = "hop-1";
            plan.DnsThroughRoute = true;
            plan.GameDomains.Add("smp3.mcsh.io");
            RunCheck("proxy route with DNS inside the tunnel", SingBoxConfig.Build(plan), failures, passes);

            // ---- a relay chain: the exit is dialled through the entry
            var exit = ConnectionEntry.Create("latvia exit", ConnectionKind.Http);
            exit.Host = "exit.example.net";
            exit.Port = 8080;
            var chainPlan = new TunnelPlan();
            chainPlan.IncludeTun = true;
            chainPlan.ServerIps.Add("163.5.201.3");
            chainPlan.ExtraOutbounds.Add(ConnectionRoute.BuildOutbound(socks, "hop-1"));
            Dictionary<string, object> exitObject = ConnectionRoute.BuildOutbound(exit, "hop-2");
            exitObject["detour"] = "hop-1";
            chainPlan.ExtraOutbounds.Add(exitObject);
            chainPlan.RouteTag = "hop-2";
            chainPlan.DnsThroughRoute = true;
            RunCheck("two hop relay chain", SingBoxConfig.Build(chainPlan), failures, passes);

            // ---- the OpenVPN route (this is the TunnelBear shape)
            var ovpnEntry = ConnectionEntry.Create("bear", ConnectionKind.OpenVpn);
            ovpnEntry.Host = "198.51.100.9";
            ovpnEntry.Port = 443;
            ovpnEntry.User = "account";
            ovpnEntry.Password = "password";
            OvpnProfile profile = OvpnProfile.Parse(
                SampleOvpn() + "<ca>\n" + SampleCert() + "</ca>\n<tls-auth>\n" + SampleStaticKey() + "</tls-auth>\n", "");
            var ovpnPlan = new TunnelPlan();
            ovpnPlan.IncludeTun = true;
            ovpnPlan.ServerIps.Add("163.5.201.3");
            ovpnPlan.ExtraEndpoints.Add(profile.ToEndpoint("hop-1", ovpnEntry.User, ovpnEntry.Password));
            ovpnPlan.MemberTags.Add("hop-1");
            ovpnPlan.RouteTag = "hop-1";
            ovpnPlan.DnsThroughRoute = true;
            ovpnPlan.DnsOpenVpnTag = "hop-1";
            ovpnPlan.GameDomains.Add("smp3.mcsh.io");
            RunCheck("OpenVPN route with the server pushed resolvers", SingBoxConfig.Build(ovpnPlan), failures, passes);

            // ---- split tunnel without a server address (the DNS only mode)
            var dnsPlan = new TunnelPlan();
            dnsPlan.IncludeTun = false;
            dnsPlan.DnsThroughRoute = true;
            dnsPlan.RouteTag = "direct";
            RunCheck("DNS only mode", SingBoxConfig.Build(dnsPlan), failures, passes);
        }

        private static void CheckOptimizer(List<string> failures, List<string> passes)
        {
            var list = new List<ConnectionEntry>();
            var a = ConnectionEntry.Create("entry", ConnectionKind.Socks5);
            a.Host = "203.0.113.7"; a.Port = 1080; a.LastDelayMs = 30;
            var b = ConnectionEntry.Create("exit", ConnectionKind.Http);
            b.Host = "198.51.100.20"; b.Port = 8080; b.LastDelayMs = 180;
            list.Add(a);
            list.Add(b);

            List<RouteCandidate> candidates = RouteOptimizer.Plan(list, true, 2, false);
            Expect(candidates.Count >= 4, "the optimiser plans direct, single and chained routes", failures, passes);
            bool hasChain = false;
            foreach (RouteCandidate candidate in candidates) if (candidate.IsChain && candidate.Hops == 2) hasChain = true;
            Expect(hasChain, "the optimiser offers a two hop relay", failures, passes);
        }

        /// <summary>Writes the config and asks the bundled engine whether it would run it.</summary>
        private static void RunCheck(string name, string json, List<string> failures, List<string> passes)
        {
            if (!File.Exists(AppPaths.SingBoxExe))
            {
                failures.Add(name + ": the tunnel engine is not bundled, so the configuration cannot be validated");
                return;
            }
            AppPaths.EnsureAll();
            string path = Path.Combine(AppPaths.Cache, "selftest-" + name.Replace(' ', '-') + ".json");
            File.WriteAllText(path, json, new UTF8Encoding(false));
            Shell.Result result = Shell.Run(AppPaths.SingBoxExe, "check -c " + Shell.Quote(path), 30000);
            if (result.Ok) passes.Add(name + " is accepted by the engine");
            else failures.Add(name + " was rejected: " + Short(result.All));
        }

        private static string Short(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            string single = text.Replace("\r", " ").Replace("\n", " ").Trim();
            return single.Length > 300 ? single.Substring(0, 300) : single;
        }
    }
}
