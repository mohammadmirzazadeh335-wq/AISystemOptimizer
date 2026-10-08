using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.UI.Converters
{
    /// <summary>Boolean to Visibility (parameter "invert" flips the result).</summary>
    public class BoolToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var flag = value is bool b && b;

            if (parameter is string s && s.Equals("invert", StringComparison.OrdinalIgnoreCase))
                flag = !flag;

            return flag ? Visibility.Visible : Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return value is Visibility visibility && visibility == Visibility.Visible;
        }
    }

    /// <summary>Inverts a boolean.</summary>
    public class InverseBoolConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return value is bool b && !b;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return value is bool b && !b;
        }
    }

    /// <summary>Maps a <see cref="RiskLevel"/> to the fixed risk colour.</summary>
    public class RiskLevelToBrushConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not RiskLevel risk)
                return new SolidColorBrush(Color.FromRgb(0x9A, 0x9A, 0x9A));

            return risk switch
            {
                RiskLevel.Low => new SolidColorBrush(Color.FromRgb(0x10, 0x7C, 0x10)),
                RiskLevel.Medium => new SolidColorBrush(Color.FromRgb(0xF7, 0xA5, 0x01)),
                RiskLevel.High => new SolidColorBrush(Color.FromRgb(0xD8, 0x3B, 0x01)),
                RiskLevel.Critical => new SolidColorBrush(Color.FromRgb(0xC4, 0x2B, 0x1C)),
                _ => new SolidColorBrush(Color.FromRgb(0x9A, 0x9A, 0x9A))
            };
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Maps a <see cref="RiskLevel"/> to a readable label with the traffic-light glyph.</summary>
    public class RiskLevelToTextConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not RiskLevel risk)
                return "Unknown";

            return risk switch
            {
                RiskLevel.Low => "\u25CF LOW",
                RiskLevel.Medium => "\u25CF MEDIUM",
                RiskLevel.High => "\u25CF HIGH",
                RiskLevel.Critical => "\u25CF CRITICAL",
                _ => "\u25CF Unknown"
            };
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Maps a <see cref="ProcessCategory"/> to a short human label.</summary>
    public class ProcessCategoryToTextConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not ProcessCategory category)
                return "Unknown";

            return category switch
            {
                ProcessCategory.Critical => "Critical",
                ProcessCategory.System => "Windows System",
                ProcessCategory.Driver => "Driver",
                ProcessCategory.Security => "Security",
                ProcessCategory.UserApplication => "Application",
                ProcessCategory.BackgroundApplication => "Background",
                ProcessCategory.Game => "Game",
                ProcessCategory.Launcher => "Launcher",
                ProcessCategory.Updater => "Updater",
                ProcessCategory.CloudSync => "Cloud Sync",
                ProcessCategory.Telemetry => "Telemetry",
                ProcessCategory.Suspicious => "Suspicious",
                _ => "Unknown"
            };
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Percentage (0-100) to a brush: green / amber / red bands.</summary>
    public class PercentToBrushConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var percent = value switch
            {
                double d => d,
                float f => f,
                int i => i,
                _ => 0.0
            };

            // The colour thresholds are the same ones used for the score rings.
            if (percent < 50) return new SolidColorBrush(Color.FromRgb(0x10, 0x7C, 0x10));
            if (percent < 75) return new SolidColorBrush(Color.FromRgb(0xF7, 0xA5, 0x01));
            if (percent < 90) return new SolidColorBrush(Color.FromRgb(0xD8, 0x3B, 0x01));
            return new SolidColorBrush(Color.FromRgb(0xC4, 0x2B, 0x1C));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Colour used for the health score (high score = green).</summary>
    public class ScoreToBrushConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var score = value is int i ? i : 0;

            if (score >= 80) return new SolidColorBrush(Color.FromRgb(0x10, 0x7C, 0x10));
            if (score >= 60) return new SolidColorBrush(Color.FromRgb(0xF7, 0xA5, 0x01));
            if (score >= 40) return new SolidColorBrush(Color.FromRgb(0xD8, 0x3B, 0x01));
            return new SolidColorBrush(Color.FromRgb(0xC4, 0x2B, 0x1C));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Formats a byte count as B / KB / MB / GB.</summary>
    public class BytesToReadableConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var bytes = value switch
            {
                long l => l,
                int i => i,
                double d => (long)d,
                _ => 0L
            };

            return Core.Services.MemoryBreakdown.Format(bytes);
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Converts a byte/second rate into a human readable rate string.</summary>
    public class BytesPerSecondConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var bytes = value switch
            {
                long l => l,
                int i => i,
                double d => (long)d,
                _ => 0L
            };

            if (bytes <= 0) return "0 B/s";
            if (bytes < 1024) return $"{bytes} B/s";
            if (bytes < 1024 * 1024) return $"{bytes / 1024.0:F1} KB/s";
            if (bytes < 1024L * 1024 * 1024) return $"{bytes / (1024.0 * 1024):F1} MB/s";
            return $"{bytes / (1024.0 * 1024 * 1024):F2} GB/s";
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Shows "N/A" when a nullable float has no value (honest temperature reporting).</summary>
    public class NullableTemperatureConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is float f && !float.IsNaN(f) && f > 0)
                return $"{f:F0} \u00B0C";

            return "N/A";
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Combines multiple bound strings ("{0} - {1}") for status captions.</summary>
    public class StringFormatConverter : IMultiValueConverter
    {
        public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
        {
            if (values == null || values.Length == 0)
                return string.Empty;

            var format = parameter as string ?? string.Empty;
            return string.Format(CultureInfo.CurrentCulture, format, values);
        }

        public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Null to Visibility (used by the details pane).</summary>
    public class NullToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            var visible = value != null;
            if (parameter is string s && s.Equals("invert", StringComparison.OrdinalIgnoreCase))
                visible = !visible;

            return visible ? Visibility.Visible : Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }

    /// <summary>Maps a <see cref="SignatureStatus"/> to an explanatory label.</summary>
    public class SignatureStatusToTextConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not SignatureStatus status)
                return "Unknown";

            return status switch
            {
                SignatureStatus.MicrosoftSigned => "Microsoft signed",
                SignatureStatus.KnownVendor => "Known publisher",
                SignatureStatus.Unsigned => "Unsigned (not necessarily unsafe)",
                SignatureStatus.Suspicious => "Suspicious signature",
                SignatureStatus.InvalidSignature => "Invalid signature",
                _ => "Unknown"
            };
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }
}
