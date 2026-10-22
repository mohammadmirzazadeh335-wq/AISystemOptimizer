# 8. رابط کاربری جلویی

## 8.1 نمای کلی پنل جلو

```
 ┌─────────────────────────────────────┐
 │         Front_Panel_Frame           │  1.5mm Steel, 950×500mm (نیمه بالایی جلو)
 │                                     │
 │   ┌──────────┐                      │
 │   │ Display  │  1 inch (25.4mm)     │  ارتفاع 1200mm از کف
 │   │  Mount   │                      │
 │   └──────────┘                      │
 │                                     │
 │   [BTN1]  [BTN2]   دو دکمه فشاری    │  زیر نمایشگر، فاصله 20mm
 │                                     │
 │   ┌────────────────┐                │
 │   │  Keypad 4×3    │  صفحه‌کلید عددی │  زیر دکمه‌ها، 100×80mm
 │   │  (12 keys)     │                │
 │   └────────────────┘                │
 │                                     │
 │   ┌────────────────┐                │
 │   │  Input/Output  │  شکاف 400×50mm │  ارتفاع 400mm از کف
 │   │  Slot          │                │
 │   └────────────────┘                │
 └─────────────────────────────────────┘
```

## 8.2 قطعات UI

| قطعه | فایل | ابعاد فرضی | پارامتریک |
|------|------|------------|-----------|
| Display Placeholder | `Display_Placeholder.SLDPRT` | 26×26×8mm (1" مربع) | ✅ `Display_Width/Height/Depth` |
| Display Mount | `Display_Mount.SLDPRT` | قاب 40×40×10mm، 4× سوراخ M3 | ✅ |
| Display Cutout | — | برش 28×28mm روی Front_Panel | ✅ `Display_Cutout_Width/Height` |
| Button Placeholder | `Button_Placeholder.SLDPRT` | Ø16mm, H=12mm, Tactile | ✅ `Button_Diameter` |
| Button Mount | `Button_Mount.SLDPRT` | سوراخ Ø16.2mm + خار ضد چرخش | ✅ |
| Button Cutout | — | 2× سوراخ Ø16.5mm روی Front_Panel | فاصله 40mm |
| Keypad Placeholder | `Keypad_Placeholder.SLDPRT` | 100×80×10mm, 12-key | ✅ `Keypad_Width/Height` |
| Keypad Mount | `Keypad_Mount.SLDPRT` | قاب 110×90×12mm, 4× M3 | ✅ |
| Keypad Cutout | — | برش 102×82mm | ✅ `Keypad_Cutout_Width/Height` |
| Front_Panel_Frame | `Front_Panel_Frame.SLDPRT` | 950×700×1.5mm (بخش جلو) | — |

## 8.3 جزئیات طراحی هر قطعه

### Display_Mount

- **Feature Tree:**
  ```
  Display_Mount
  ├── Equations (Display_Width=26, Display_Height=26)
  ├── Sketch_Base (40×40mm مستطیل)
  ├── Boss_Extrude (10mm, قاب)
  ├── Sketch_Cutout (26×26mm)
  ├── Cut_Extrude (Through All — محل نمایشگر)
  ├── Sketch_Mounting_Holes (4× Ø3.2mm, PCD 34mm)
  ├── Hole_Cut (4×)
  ├── Sketch_Cable_Opening (10×8mm پشت)
  ├── Cable_Cut
  └── Fillet (R1mm)
  ```
- **نصب:** 4× پیچ M3×8 از پشت پنل، دسترسی از داخل.
- **فضای پشت پنل:** 50mm عمق تا گنتری — کافی برای PCB نمایشگر.

### Button_Mount (×2)

- سوراخ Ø16.5mm روی پنل (تلرانس +0.2mm برای جا زدن دکمه).
- خار ضد چرخش: شیار 2×1mm.
- براکت پشت: حلقه نگهدارنده با مهره پلاستیکی (Placeholder).
- **فاصله دو دکمه:** 40mm مرکز تا مرکز، 30mm زیر نمایشگر.

### Keypad_Mount

- قاب 110×90mm که Keypad داخل آن قرار می‌گیرد.
- 4× بوش M3 برای پیچ از پشت.
- برش پنل 102×82mm (1mm لقی هر طرف).
- کابل از سوراخ 15×10mm پشت قاب خارج می‌شود.

## 8.4 پنل جلویی (Front_Panel_Frame)

- ورق 1.5mm با **Sheet Metal** — خم 10mm لبه برای استحکام.
- برش‌ها:
  - Display Cutout: 28×28mm
  - Button Cutouts: 2× Ø16.5mm
  - Keypad Cutout: 102×82mm
  - I/O Slot: 400×50mm (ورودی/خروجی امانت)
- تمام برش‌ها با **Sketch پارامتریک** تعریف شده‌اند — تغییر `Display_Cutout_Width` برش را تغییر می‌دهد.

## 8.5 پارامترهای UI

```plaintext
Display_Width         = 26      (1 inch = 25.4mm, گرد به 26)
Display_Height        = 26
Display_Depth         = 8
Display_Cutout_Width  = 28
Display_Cutout_Height = 28
Button_Diameter       = 16
Button_Hole_Diameter  = 16.5
Button_Spacing        = 40
Keypad_Width          = 100
Keypad_Height         = 80
Keypad_Cutout_Width   = 102
Keypad_Cutout_Height  = 82
IO_Slot_Width         = 400
IO_Slot_Height        = 50
```

> این مقادیر فرضی هستند (الزام §10) و با تغییر Global Variable قابل تطبیق با قطعه واقعی هستند. الگوی سوراخ‌ها نیز پارامتریک است.

## 8.6 دسترسی و تعمیر

- پنل جلویی با 8× پیچ M5 به فریم جلو متصل است — با باز کردن پیچ‌ها، کل پنل جدا می‌شود.
- کابل‌های UI از Cable Tray کناری به محفظه الکترونیک می‌روند — بدون تداخل با گنتری.
- نمایشگر و کیپد از پشت با 4 پیچ قابل تعویض هستند — بدون نیاز به جدا کردن پنل کامل.
