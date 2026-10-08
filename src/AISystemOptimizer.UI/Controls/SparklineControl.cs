using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Media;

namespace AISystemOptimizer.UI.Controls
{
    /// <summary>
    /// A small, dependency-free real-time line chart.
    ///
    /// It draws a polyline plus a translucent fill beneath it, entirely with
    /// <see cref="DrawingContext"/> primitives, so the application needs no charting
    /// NuGet package (keeps the optimiser itself light and offline capable).
    /// </summary>
    public class SparklineControl : FrameworkElement
    {
        #region Dependency properties

        public static readonly DependencyProperty ValuesProperty =
            DependencyProperty.Register(
                nameof(Values),
                typeof(IEnumerable<double>),
                typeof(SparklineControl),
                new FrameworkPropertyMetadata(
                    null,
                    FrameworkPropertyMetadataOptions.AffectsRender,
                    OnValuesChanged));

        public static readonly DependencyProperty LineBrushProperty =
            DependencyProperty.Register(
                nameof(LineBrush),
                typeof(Brush),
                typeof(SparklineControl),
                new FrameworkPropertyMetadata(
                    Brushes.DodgerBlue,
                    FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty FillBrushProperty =
            DependencyProperty.Register(
                nameof(FillBrush),
                typeof(Brush),
                typeof(SparklineControl),
                new FrameworkPropertyMetadata(
                    null,
                    FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty MaximumProperty =
            DependencyProperty.Register(
                nameof(Maximum),
                typeof(double),
                typeof(SparklineControl),
                new FrameworkPropertyMetadata(100.0, FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty LineThicknessProperty =
            DependencyProperty.Register(
                nameof(LineThickness),
                typeof(double),
                typeof(SparklineControl),
                new FrameworkPropertyMetadata(1.5, FrameworkPropertyMetadataOptions.AffectsRender));

        /// <summary>Ring buffer of samples to draw (oldest first).</summary>
        public IEnumerable<double>? Values
        {
            get => (IEnumerable<double>?)GetValue(ValuesProperty);
            set => SetValue(ValuesProperty, value);
        }

        /// <summary>Colour of the line.</summary>
        public Brush LineBrush
        {
            get => (Brush)GetValue(LineBrushProperty);
            set => SetValue(LineBrushProperty, value);
        }

        /// <summary>Optional fill under the line (defaults to a 20% version of the line colour).</summary>
        public Brush? FillBrush
        {
            get => (Brush?)GetValue(FillBrushProperty);
            set => SetValue(FillBrushProperty, value);
        }

        /// <summary>Value that maps to the top of the chart (100 for percentages).</summary>
        public double Maximum
        {
            get => (double)GetValue(MaximumProperty);
            set => SetValue(MaximumProperty, value);
        }

        /// <summary>Stroke thickness in device independent pixels.</summary>
        public double LineThickness
        {
            get => (double)GetValue(LineThicknessProperty);
            set => SetValue(LineThicknessProperty, value);
        }

        #endregion

        #region Change handling

        private static void OnValuesChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        {
            if (d is not SparklineControl control)
                return;

            // Unhook the old collection to avoid leaks when the VM rebuilds its buffer.
            if (e.OldValue is INotifyCollectionChanged oldCollection)
                oldCollection.CollectionChanged -= control.OnCollectionChanged;

            if (e.NewValue is INotifyCollectionChanged newCollection)
                newCollection.CollectionChanged += control.OnCollectionChanged;

            control.InvalidateVisual();
        }

        private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
        {
            InvalidateVisual();
        }

        #endregion

        #region Rendering

        protected override void OnRender(DrawingContext drawingContext)
        {
            base.OnRender(drawingContext);

            var values = Values;

            if (values == null)
                return;

            var points = new List<double>();

            foreach (var value in values)
            {
                points.Add(double.IsNaN(value) || double.IsInfinity(value) ? 0 : value);
            }

            if (points.Count < 2)
                return;

            var width = ActualWidth;
            var height = ActualHeight;

            if (width <= 1 || height <= 1)
                return;

            var maximum = Maximum <= 0 ? 100.0 : Maximum;
            var stepX = width / (points.Count - 1);

            var geometry = new StreamGeometry();

            using (var context = geometry.Open())
            {
                var firstY = height - Math.Clamp(points[0] / maximum, 0, 1) * height;
                context.BeginFigure(new Point(0, firstY), isFilled: false, isClosed: false);

                for (int i = 1; i < points.Count; i++)
                {
                    var x = i * stepX;
                    var y = height - Math.Clamp(points[i] / maximum, 0, 1) * height;
                    context.LineTo(new Point(x, y), isStroked: true, isSmoothJoin: true);
                }
            }

            geometry.Freeze();

            // Fill under the curve, when requested.
            var fill = FillBrush;

            if (fill == null && LineBrush is SolidColorBrush solid)
            {
                var translucent = Color.FromArgb(40, solid.Color.R, solid.Color.G, solid.Color.B);
                fill = new SolidColorBrush(translucent);
            }

            if (fill != null)
            {
                var fillGeometry = geometry.Clone();

                using (var context = fillGeometry.Open())
                {
                    var lastX = (points.Count - 1) * stepX;
                    var lastY = height - Math.Clamp(points[^1] / maximum, 0, 1) * height;

                    context.BeginFigure(new Point(lastX, lastY), isFilled: true, isClosed: true);
                    context.LineTo(new Point(lastX, height), isStroked: false, isSmoothJoin: false);
                    context.LineTo(new Point(0, height), isStroked: false, isSmoothJoin: false);
                    context.LineTo(new Point(0, height - Math.Clamp(points[0] / maximum, 0, 1) * height),
                        isStroked: false, isSmoothJoin: false);
                }

                fillGeometry.Freeze();
                drawingContext.DrawGeometry(fill, null, fillGeometry);
            }

            var pen = new Pen(LineBrush, LineThickness)
            {
                LineJoin = PenLineJoin.Round,
                StartLineCap = PenLineCap.Round,
                EndLineCap = PenLineCap.Round
            };

            pen.Freeze();
            drawingContext.DrawGeometry(null, pen, geometry);
        }

        #endregion
    }
}
