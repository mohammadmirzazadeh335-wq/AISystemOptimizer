using System;
using System.Diagnostics;
using System.Threading;
using AISystemOptimizer.Core.Services;
using AISystemOptimizer.Core.Utilities;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Regression tests for the v1.0.0 startup hang: on a machine whose WMI repository or
    /// performance-counter store is broken, unbounded reads froze the window while it was
    /// "gathering system information". Every external read now goes through
    /// <see cref="BoundedReader"/>, and these tests pin down that contract.
    /// </summary>
    public class BoundedReaderTests
    {
        [Fact]
        public void AFastReadReturnsItsValue()
        {
            var value = BoundedReader.Read(() => 42, 0, 2000, "test fast");

            Assert.Equal(42, value);
        }

        [Fact]
        public void AStuckReadReturnsTheFallbackInsideTheLimit()
        {
            var stopwatch = Stopwatch.StartNew();

            var value = BoundedReader.Read(() =>
            {
                Thread.Sleep(10_000); // a "broken WMI" that never answers
                return 7;
            }, -1, 250, "test stuck");

            stopwatch.Stop();

            Assert.Equal(-1, value);
            Assert.True(stopwatch.ElapsedMilliseconds < 3000,
                $"the caller waited {stopwatch.ElapsedMilliseconds} ms; the limit must hold");
        }

        [Fact]
        public void AStuckReadIsRecordedSoTheLogCanTell()
        {
            var before = BoundedReader.AbandonedReads;

            BoundedReader.Read(() => { Thread.Sleep(10_000); return 0; }, 0, 200, "test abandonment");

            Assert.True(BoundedReader.AbandonedReads > before);
            Assert.Equal("test abandonment", BoundedReader.LastAbandonedSource);
        }

        [Fact]
        public void AThrowingReadReturnsTheFallback()
        {
            var value = BoundedReader.Read<int>(() => throw new InvalidOperationException("WMI is broken"),
                5, 2000, "test throw");

            Assert.Equal(5, value);
        }

        [Fact]
        public void TryRunReportsFalseWhenTheWorkOutlivesTheLimit()
        {
            var finished = BoundedReader.TryRun(() => Thread.Sleep(10_000), 200, "test tryrun");

            Assert.False(finished);
        }

        [Fact]
        public void TryRunReportsTrueWhenTheWorkFinishes()
        {
            var touched = false;

            var finished = BoundedReader.TryRun(() => touched = true, 2000, "test tryrun ok");

            Assert.True(finished);
            Assert.True(touched);
        }
    }

    /// <summary>
    /// The startup path must always come back, even on a host where the Windows-specific
    /// sources do not exist. v1.0.0 could stay on "gathering system information" forever;
    /// the scan and the live sampler must now be finite by construction.
    /// </summary>
    public class StartupScanTests
    {
        [Fact]
        public void QuickScanCompletesAndStampsTheSnapshot()
        {
            var scanner = new SystemScanner();

            var info = scanner.QuickScan();

            Assert.NotNull(info);
            Assert.True(info.CollectedAt > DateTime.MinValue);
        }

        [Fact]
        public void AFullScanCompletesOnThisHost()
        {
            var scanner = new SystemScanner();

            var info = scanner.Scan();

            Assert.NotNull(info);
            Assert.True(scanner.LastScanTime > DateTime.MinValue);
        }
    }
}
