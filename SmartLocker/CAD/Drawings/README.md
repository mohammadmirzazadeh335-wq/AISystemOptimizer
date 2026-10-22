# نقشه‌های مهندسی (SLDDRW)

## لیست 9 نقشه

| # | فایل | مقیاس | محتوا |
|---|------|-------|-------|
| 1 | `Main_Assembly.SLDDRW` | 1:20 | Front/Top/Side/Isometric + BOM + ابعاد خارجی/داخلی |
| 2 | `Frame_Assembly.SLDDRW` | 1:15 | فریم با مقاطع پروفیل + سوراخ‌ها |
| 3 | `Compartment.SLDDRW` | 1:5 | خانه 400×500×400 + تلرانس |
| 4 | `X_Axis_Assembly.SLDDRW` | 1:5 | ریل/کالسکه/تسمه، کورس X 480mm |
| 5 | `Z_Axis_Assembly.SLDDRW` | 1:10 | ریل Z/Lead Screw/کورس Z 2120mm |
| 6 | `Transfer_Tray.SLDDRW` | 1:5 | سینی 380×400×30 + Rack |
| 7 | `Conveyor_Assembly.SLDDRW` | 1:5 | غلتک‌ها/تسمه/موتور |
| 8 | `Front_Panel_UI.SLDDRW` | 1:5 | پنل جلو + برش‌های نمایشگر/دکمه/کیپد |
| 9 | `Electronics_Assembly.SLDDRW` | 1:10 | محفظه الکترونیک + Cable Tray |

## محتوای هر نقشه

- **Views:** Front, Top, Side + Isometric + Detail/Section (برای نقاط کلیدی)
- **Dimensions:** ابعاد بحرانی + تلرانس (ISO MMGS, Third Angle)
- **Title Block:** نام پروژه، مقیاس، تاریخ، طراح، Rev
- **BOM (فقط Main_Assembly):** جدول قطعات با Balloon

## تولید با API

```csharp
// DrawingsBuilder.cs (pseudo)
var drawing = swApp.NewDrawing("Main_Assembly.SLDASM");
drawing.CreateView("Front", ViewType.Front, scale: 1/20.0);
drawing.CreateView("Top",   ViewType.Top,   ...);
drawing.CreateView("Iso",   ViewType.Isometric, ...);
drawing.AddDimensions(auto: true);
drawing.AddBomTable(BomAnchor.TopRight);
drawing.SaveAs("Main_Assembly.SLDDRW");
```

> Generator طرح اولیه را می‌سازد؛ تنظیم نهایی ابعاد و چیدمان دستی است.
