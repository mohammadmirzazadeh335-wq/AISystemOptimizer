# 9. محفظه الکترونیک و مسیر کابل‌ها

## 9.1 موقعیت محفظه الکترونیک

```
 نمای جانبی:

  ───────── Top_Cover (40mm Frame + 1.5mm Plate)
  ┌──────────────────────────────┐ 100mm Electronics Bay
  │  Arduino  Motor Driver  PSU  │  روی Electronics_Mounting_Plate
  │  Terminal Block  Sensors Hub │  800×500mm, 5mm Al
  ├──────────────────────────────┤ Top of Compartments (Z=2000)
  │                              │
  │     Compartments (5 Rows)    │
  │                              │
  └──────────────────────────────┘
  ───────── Bottom_Plate
```

- **موقعیت:** بالای سقف خانه‌ها (Z=2000 تا 2100)، زیر Top_Cover.
- **ابعاد محفظه:** 800W × 500D × 100H mm — کاملاً خارج از مسیر گنتری X/Z.
- **دسترسی:** Top_Cover لولایی (بازشو 90° به عقب) + پنل کناری Service_Access_Panel.
- **فاصله از مکانیزم:** گنتری حداکثر Z=2120mm می‌رود، اما محفظه از Z=2200 شروع می‌شود → 80mm فاصله + Top Cover.

## 9.2 لیست قطعات الکترونیک (Placeholder)

| قطعه | فایل | ابعاد فرضی (L×W×H) | محل نصب |
|------|------|---------------------|---------|
| Arduino Placeholder | `Arduino_Placeholder.SLDPRT` | 75×55×15mm (Uno) | روی Plate، گوشه چپ |
| Motor Driver X | `Motor_Driver_Placeholder.SLDPRT` | 80×50×25mm (DM542) | کنار Arduino |
| Motor Driver Z | `Motor_Driver_Placeholder_02.SLDPRT` | 80×50×25mm | کنار Driver X |
| Motor Driver Y | `Motor_Driver_Placeholder_03.SLDPRT` | 60×40×20mm | کوچک‌تر |
| Power Supply 24V | `Power_Supply_Placeholder.SLDPRT` | 200×110×50mm (Meanwell 24V 15A) | مرکز، تهویه |
| Terminal Block | `Terminal_Block_Placeholder.SLDPRT` | 100×40×30mm | لبه جلویی Plate |
| Sensor Hub | `Sensor_Placeholder_Hub.SLDPRT` | 60×40×15mm | کنار Arduino |
| Electronics Mounting Plate | `Electronics_Mounting_Plate.SLDPRT` | 800×500×3mm, Al | روی 4× Stand-off |
| Stand-off | `Standoff_M3x20.SLDPRT` | M3×20mm, 4 عدد | فاصله Plate از سقف |

> تمام Placeholderها مکعب ساده با رنگ متفاوت (سبز برای برد، سیاه برای PSU) هستند — ابعاد پارامتریک، قابل تعویض با مدل واقعی.

### Electronics_Mounting_Plate

- **Feature Tree:**
  ```
  Electronics_Mounting_Plate
  ├── Equations (Plate_Width=800, Plate_Depth=500)
  ├── Sketch_Base (800×500 مستطیل)
  ├── Boss_Extrude (3mm)
  ├── Sketch_Mounting_Holes (4× Ø3.5mm گوشه‌ها)
  ├── Hole_Cut (4×)
  ├── Sketch_Arduino_Holes (4× Ø3.2mm, Pattern Uno)
  ├── Arduino_Holes_Cut
  ├── Sketch_Driver_Slots (اسلات تهویه 20×5mm)
  ├── Vent_Cut (Linear Pattern)
  ├── Sketch_Cable_Entry (2× Opening 30×20mm)
  ├── Cable_Entry_Cut
  └── Fillet (R3mm)
  ```

## 9.3 مسیر کابل‌ها

### اصول

1. کابل‌های ثابت (برق اصلی، سنسورهای ثابت) از **Cable_Tray** کناری می‌گذرند.
2. کابل‌های متحرک (موتور X/Z/Y، سنسورهای روی گنتری) از **Cable Chain (Energy Chain)** کنار ریل Z می‌گذرند.
3. هیچ کابلی با تسمه، پولی یا ریل تماس ندارد.

### Cable_Tray (ثابت)

| قطعه | فایل | مشخصات |
|------|------|--------|
| Cable_Tray_Main | `Cable_Tray.SLDPRT` | U-Channel 40×30×2mm, L=2000mm، عمودی کنار فریم |
| Cable_Tray_Horizontal | `Cable_Tray_Horizontal.SLDPRT` | 40×30×2mm, L=800mm، بالای سقف |
| Cable_Clip | `Cable_Clip.SLDPRT` | کلیپس پلاستیکی Ø10mm، هر 200mm |
| Cable_Entry_Opening | — | 2× Opening 30×20mm روی Bottom_Plate و Top Cover |
| Cable_Exit_Opening | — | 1× Opening 30×20mm روی پنل جلو (به UI) |

- **مسیر:** PSU (بالا) → Cable_Tray عمودی → Bottom (موتورها) + Front (UI)
- **ظرفیت:** 10× کابل 2.5mm² + 5× کابل سیگنال.

### Cable Chain (متحرک — Energy Chain Placeholder)

| قطعه | فایل | مشخصات |
|------|------|--------|
| Cable_Chain_Z | `Cable_Chain_Z.SLDPRT` | Placeholder زنجیر کابل 30×20×2200mm، شعاع خم 50mm |
| Chain_Mount_Top | `Cable_Chain_Mount_Top.SLDPRT` | براکت بالای ریل Z |
| Chain_Mount_Bottom | `Cable_Chain_Mount_Bottom.SLDPRT` | براکت روی Z_Carriage |

- **موقعیت:** کنار ریل Z چپ، فاصله 30mm از تسمه Z Sync.
- **حرکت:** با Z_Carriage بالا/پایین می‌رود، بدون کشیدگی.
- **کابل‌های داخل:** 4× Motor Phase + 2× Endstop + 1× Sensor Bus.
- **مدل:** به‌صورت Part مستطیلی با مفصل‌های Placeholder — در نسخه واقعی از IGUS E2.10 استفاده می‌شود.

### دیاگرام مسیر کابل

```
  [Electronics Bay Top]
        │
        ├── Cable_Tray_Horizontal (به UI Panel جلو)
        │         └── Display, Buttons, Keypad
        │
        └── Cable_Tray_Main (عمودی کنار فریم)
                  │
                  ├── Cable_Chain_Z (متحرک)
                  │         ├── Motor X (روی X_Carriage)
                  │         ├── Motor Z (پایین)
                  │         ├── Motor Y (روی Z_Carriage)
                  │         └── Sensors X/Z/Y
                  │
                  ├── Conveyor Motor (پایین جلو)
                  └── Door Locks (هر خانه — از Tray عمودی منشعب)
```

## 9.4 فاصله از مکانیزم (الزام §8.8)

| محفظه/مسیر | فاصله از نزدیک‌ترین قطعه متحرک | وضعیت |
|------------|----------------------------------|-------|
| Electronics Bay تا Z_Carriage (بالاترین نقطه) | 80mm (Z=2120 تا 2200) | ✅ |
| Cable_Tray تا تسمه X | 40mm | ✅ |
| Cable_Tray تا ریل Z | 25mm | ✅ |
| Cable_Chain تا تسمه Z Sync | 30mm | ✅ |
| Cable_Chain تا Lead Screw | 20mm | ✅ |
| کابل UI تا گنتری | 15mm (پشت پنل جلو) | ✅ |

## 9.5 تهویه و ایمنی

- دریچه تهویه 100×50mm روی Top_Cover برای PSU.
- فیوز 10A Placeholder روی Terminal Block.
- اتصال زمین (Earth) به فریم فلزی — تمام پنل‌ها با پیچ به فریم متصل و Conductive هستند.
