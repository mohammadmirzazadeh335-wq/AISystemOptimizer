# 11. نقشه‌های مهندسی (Drawings)

## 11.1 لیست نقشه‌ها (SLDDRW)

| # | فایل SLDDRW | مقیاس | شامل |
|---|-------------|-------|------|
| 1 | `Main_Assembly.SLDDRW` | 1:20 | نمای جلو، بالا، جانبی، ایزومتریک، ابعاد کلی، BOM |
| 2 | `Frame_Assembly.SLDDRW` | 1:15 | فریم با ابعاد پروفیل، محل سوراخ‌ها |
| 3 | `Compartment.SLDDRW` | 1:5 | جزئیات خانه، ابعاد داخلی، تلرانس |
| 4 | `X_Axis_Assembly.SLDDRW` | 1:5 | ریل، کالسکه، تسمه، کورس X |
| 5 | `Z_Axis_Assembly.SLDDRW` | 1:10 | ریل Z، Lead Screw، کورس Z |
| 6 | `Transfer_Tray.SLDDRW` | 1:5 | سینی، ریل Y، Rack |
| 7 | `Conveyor_Assembly.SLDDRW` | 1:5 | غلتک‌ها، تسمه، موتور |
| 8 | `Front_Panel_UI.SLDDRW` | 1:5 | پنل جلو، برش‌های نمایشگر/دکمه/کیپد |
| 9 | `Electronics_Assembly.SLDDRW` | 1:10 | محفظه الکترونیک، Plate، Cable Tray |

## 11.2 محتوای نقشه اصلی (Main_Assembly.SLDDRW)

### Sheet 1: نمای کلی

- **Front View:** ابعاد خارجی 950×2400، موقعیت 10 خانه با شماره‌گذاری.
- **Top View:** عمق 700mm، موقعیت گنتری و نوار نقاله.
- **Side View:** مقطع عمق، نمایش Y_Travel.
- **Isometric View:** نمای سه‌بعدی با سایه.
- **BOM Table:** لیست قطعات با شماره بالن (Balloon).

### Sheet 2: جزئیات مکانیزم

- **Detail A:** مقطع X-Axis (ریل + واگن + تسمه + Tensioner) — مقیاس 1:2.
- **Detail B:** مقطع Z-Axis (Lead Screw + Belt Sync) — مقیاس 1:5.
- **Section C-C:** برش عمودی از وسط، نمایش 5 ردیف + گنتری.

### ابعاد بحرانی روی نقشه

| بعد | مقدار | تلرانس |
|-----|-------|--------|
| External_Width | 950mm | ±1mm |
| External_Depth | 700mm | ±1mm |
| External_Height | 2400mm | ±2mm |
| Compartment Internal | 400×500×400 | ±0.5mm |
| X_Travel | 480mm | ±0.5mm |
| Z_Travel | 2120mm | ±0.5mm |
| Y_Travel | 450mm | ±1mm |
| Rail Mounting Holes | M5, PCD per datasheet | ±0.05mm |
| UI Cutouts | per parametric | ±0.2mm |

## 11.3 استاندارد نقشه

- **Standard:** ISO (MMGS)
- **Projection:** Third Angle (آمریکایی) — قابل تغییر به First Angle.
- **Font:** Century Gothic (SolidWorks Default)
- **Line Weight:** 0.35mm برای Visible، 0.18mm برای Hidden.
- **Title Block:** شامل نام پروژه، مقیاس، تاریخ، طراح، شماره Rev.

## 11.4 تولید نقشه با API

کد Generator نقشه‌ها را با `DrawingsBuilder.cs` می‌سازد:

```csharp
// Pseudo-code
var drawing = sw.NewDrawing("Main_Assembly.SLDASM");
drawing.CreateView("Front", ViewType.Front, scale: 1/20.0);
drawing.CreateView("Top", ViewType.Top, ...);
drawing.CreateView("Isometric", ViewType.Isometric, ...);
drawing.AddDimensions(auto: true);
drawing.AddBomTable(anchor: BomAnchor.TopRight);
drawing.SaveAs("Main_Assembly.SLDDRW");
```

> نقشه‌ها پس از تولید، نیاز به تنظیم دستی ابعاد و چیدمان دارند — Generator طرح اولیه را می‌سازد و کاربر جزئیات را تنظیم می‌کند.
