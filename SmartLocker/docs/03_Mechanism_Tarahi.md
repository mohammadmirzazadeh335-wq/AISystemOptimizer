# 3. مکانیزم انتقال امانت

## 3.1 معماری کلی مکانیزم

```
 نمای جانبی (Side View, مقطع عمق):

    ┌──── Rear ────┐          ┌── Front ──┐
    │  Compartment │ 15mm gap │  Gantry   │  UI Panel
    │  (500 deep)  │          │  X/Z/Y    │
    │              │◄────────►│           │
    │  Tray Pusher │  Y=450   │ Transfer  │  Conveyor I/O
    │  (Rack)      │  stroke  │ Tray 380  │
    └──────────────┘          └───────────┘
         500mm                  120mm+80mm
```

**سه محور اصلی:**

| محور | جهت | وظیفه | کورس | محرک |
|------|-----|-------|------|------|
| **X** | افقی (چپ↔راست) | انتخاب ستون (1 یا 2) | 480mm | Stepper NEMA23 + GT2 Belt + 2× Pulley |
| **Z** | عمودی (پایین↔بالا) | انتخاب ردیف (1 تا 5) | 2120mm | Stepper NEMA23 + Lead Screw T8×8 + Belt Sync |
| **Y** | عمق (عقب↔جلو) | ورود/خروج سینی به داخل خانه | 450mm | NEMA17 + Rack-Pinion |

> **چرا Y لازم است؟** صرفاً قرار دادن نوار نقاله جلوی خانه برای برداشت وسیله کافی نیست (الزام §6). سینی باید به داخل خانه حرکت کند، زیر امانت برود یا آن را هل دهد و خارج کند. بدون Y، امانت داخل خانه باقی می‌ماند.

## 3.2 محور X — حرکت افقی

### اجزا

| قطعه | فایل | مشخصات |
|------|------|--------|
| Linear Rail X | `Linear_Rail_X.SLDPRT` | MGN15H, L=900mm, 2 عدد موازی (بالا و پایین گنتری) |
| Guide Block X | `Linear_Guide_Block_X.SLDPRT` | MGN15H Block, 4 عدد (2 per rail) |
| X Carriage Plate | `X_Carriage.SLDPRT` | ورق آلومینیوم 5mm، 500×200mm، سوراخ‌های نصب Z |
| Drive Pulley X | `Pulley_GT2_20T.SLDPRT` | GT2-20T, Bore 8mm, عرض 10mm |
| Idler Pulley X | `Pulley_Idler_X.SLDPRT` | GT2 Idler 20T با بلبرینگ 625ZZ |
| Timing Belt X | `Belt_GT2_X.SLDPRT` | GT2, عرض 10mm، طول بسته ~2200mm |
| Motor Mount X | `Motor_Mount_X.SLDPRT` | براکت L شکل، آلومینیوم 5mm |
| Stepper Motor X | `Motor_NEMA23_X.SLDPRT` | Placeholder NEMA23, 56×56×56mm |
| Belt Tensioner X | `Belt_Tensioner_X.SLDPRT` | اسلات + پیچ M5 + فنر |
| Shaft X | `Shaft_Drive_X.SLDPRT` | شفت فولادی Ø8mm, L=920mm |
| Bearing Block X | `Bearing_Block_X.SLDPRT` | SK8, 2 عدد |

### مسیر تسمه X

```
  Motor (left) ── Drive Pulley ──┐
                                  │  Belt outer loop
  Idler Pulley (right) ──────────┘
              │
              └── Carriage clamped to belt (Belt Clamp)
```

- **فاصله مرکز تا مرکز پولی‌ها:** 850mm
- **طول تسمه بسته:** 2×850 + π×Ø15.6 ≈ 1750mm (محاسبه دقیق در Equations)
- **نقطه اتصال کالسکه:** Belt Clamp روی تسمه، با 2 پیچ M3 — کالسکه با حرکت تسمه جابه‌جا می‌شود.
- **Tensioning:** Idler روی اسلات 20mm قابل تنظیم + پیچ M5.

### کورس و محدودیت

- **X_Travel = 480mm** — فاصله مرکز ستون 1 تا مرکز ستون 2 + حاشیه 80mm هر طرف برای توقف نرم.
- **Limit Mate:** `LimitDistance` بین `X_Carriage` و `Frame_Left` — min 0mm, max 480mm.
- **Mechanical Stop:** 2× Stop Block با ضربه‌گیر لاستیکی در دو انتها.

## 3.3 محور Z — حرکت عمودی

### اجزا

| قطعه | فایل | مشخصات |
|------|------|--------|
| Linear Rail Z | `Linear_Rail_Z.SLDPRT` | MGN15H, L=2200mm, 2 عدد عمودی (چپ و راست) |
| Guide Block Z | `Linear_Guide_Block_Z.SLDPRT` | MGN15H, 4 عدد |
| Z Carriage (Vertical Lift) | `Z_Carriage.SLDPRT` | ورق آلومینیوم 5mm، 900×200mm |
| Lead Screw Z | `Lead_Screw_T8x8.SLDPRT` | T8×8, Ø8mm, L=2150mm, 2 عدد (چپ و راست) |
| Lead Screw Nut | `Lead_Screw_Nut_T8.SLDPRT` | Brass Nut, Flange |
| Sync Belt Z | `Belt_GT2_Z_Sync.SLDPRT` | GT2 10mm، اتصال دو Lead Screw برای همگام‌سازی |
| Sync Pulley Z | `Pulley_GT2_20T_Z.SLDPRT` | GT2-20T, 2 عدد پایین + 2 عدد بالا |
| Motor Mount Z | `Motor_Mount_Z.SLDPRT` | براکت پایین، آلومینیوم 8mm |
| Stepper Motor Z | `Motor_NEMA23_Z.SLDPRT` | NEMA23 2.2Nm, پایین مرکز |
| Bearing Block Z Top/Bottom | `Bearing_Block_Z.SLDPRT` | KP08, 4 عدد |

### چرا Lead Screw + Belt Sync؟

- **Lead Screw:** برای محور عمودی، تسمه به‌تنهایی تحت بار وزن گنتری (15kg + 10kg سازه) ممکن است لغزش یا کشیدگی داشته باشد. Lead Screw با Pitch 8mm، خودنگهدار نسبی و دقت 0.05mm می‌دهد.
- **Belt Sync:** دو Lead Screw چپ و راست با تسمه همگام می‌شوند تا کج‌شدن (Racking) رخ ندهد. یک موتور، هر دو را می‌چرخاند.

### مسیر حرکت Z

```
  Bottom: Motor → Pulley → Belt → Lead Screw Left
                        └──────→ Lead Screw Right (via Sync Belt)
  Top:    Idler Pulleys + Bearing Blocks
  Carriage: 2× Nut (چپ و راست) + 4× Guide Block
```

- **Z_Travel = 2120mm** — از Z=50mm (ردیف 1) تا Z=2170mm (ردیف 5).
- **Limit Mate:** `LimitDistance` بین `Z_Carriage` و `Bottom_Plate` — min 0, max 2120mm.
- **Mechanical Stop:** بالا و پایین + Limit Switch Placeholder.

### محاسبه سرعت Z

- Lead Screw Pitch = 8mm/rev
- Stepper 200 step/rev × 16 microstep = 3200 step/rev
- هر step = 8/3200 = 0.0025mm — با سرعت 400 step/s → 200mm/s (مطابق فرض).

## 3.4 محور Y — سینی کشویی (Pusher)

### اجزا

| قطعه | فایل | مشخصات |
|------|------|--------|
| Transfer Tray | `Transfer_Tray.SLDPRT` | آلومینیوم 3mm، 380W×400D×30H (لبه 10mm) |
| Y Linear Rail | `Linear_Rail_Y.SLDPRT` | MGN12H, L=500mm، روی Z_Carriage |
| Y Guide Block | `Linear_Guide_Block_Y.SLDPRT` | MGN12H, 2 عدد |
| Y Rack | `Rack_Y.SLDPRT` | Rack Module 1, L=450mm |
| Y Pinion | `Pinion_Y.SLDPRT` | 20T, Module 1, Bore 5mm |
| Y Motor | `Motor_NEMA17_Y.SLDPRT` | NEMA17 Placeholder, روی Z_Carriage |
| Y Motor Mount | `Motor_Mount_Y.SLDPRT` | براکت کوچک 3mm |
| Tray Edge Guide | `Tray_Guide.SLDPRT` | لبه نگهدارنده امانت، 2 عدد جانبی |
| Position Sensor Y | `Sensor_Placeholder_Y.SLDPRT` | Optical Endstop, 2 عدد |

### عملکرد Y

1. **حالت دریافت:** سینی در حالت عقب (Y=0) روی گنتری. امانت از Conveyor ورودی روی سینی می‌غلتد.
2. **حرکت به خانه:** گنتری به X,Z خانه مقصد می‌رود. سپس Y به جلو (Y=450) — سینی به داخل خانه می‌رود، امانت را هل می‌دهد/رها می‌کند.
3. **حالت تحویل:** برعکس — سینی به داخل خانه (Y=450) می‌رود، زیر امانت (یا با لبه جلویی آن را می‌کشد) و به عقب (Y=0) برمی‌گردد.
4. **لبه سینی:** لبه جلویی 30mm ارتفاع دارد تا امانت را بکشد؛ کف سینی با نوار سیلیکونی اصطکاک بالا.

## 3.5 نوار نقاله ورودی/خروجی

| قطعه | فایل | مشخصات |
|------|------|--------|
| Conveyor Belt | `Conveyor_Belt.SLDPRT` | PVC Belt, عرض 350mm, طول 600mm |
| Drive Roller | `Roller_Drive.SLDPRT` | Ø40mm, L=380mm, شفت Ø12mm |
| Idler Roller | `Roller_Idler.SLDPRT` | Ø40mm, L=380mm |
| Conveyor Frame | `Conveyor_Frame.SLDPRT` | 2× Side Plate 3mm |
| Conveyor Motor | `Motor_Conveyor.SLDPRT` | DC Gear Motor JGB37-520 |
| Belt Tensioner Conveyor | `Belt_Tensioner_Conveyor.SLDPRT` | اسلات + پیچ |

- **موقعیت:** جلوی دستگاه، ارتفاع 400mm از کف (هم‌سطح سینی در Z پایین).
- **عملکرد:** امانت روی نوار قرار می‌گیرد → سنسور تشخیص → نوار به سمت سینی می‌چرخد → امانت روی سینی منتقل می‌شود.

## 3.6 سنسورها (Placeholder)

| سنسور | تعداد | محل | فایل |
|--------|-------|-----|------|
| Endstop X | 2 | دو انتهای ریل X | `Sensor_Endstop_X.SLDPRT` |
| Endstop Z | 2 | بالا و پایین ریل Z | `Sensor_Endstop_Z.SLDPRT` |
| Endstop Y | 2 | جلو و عقب ریل Y | `Sensor_Endstop_Y.SLDPRT` |
| Presence Sensor (خانه) | 10 | داخل هر خانه، سقف | `Sensor_Presence.SLDPRT` |
| Conveyor Sensor | 1 | ورودی نوار | `Sensor_Conveyor.SLDPRT` |
| Door Sensor | 10 | هر درب | `Sensor_Door.SLDPRT` |

> تمام سنسورها Placeholder مکعبی 15×15×10mm با براکت نصب هستند — ابعاد پارامتریک، قابل تعویض با مدل واقعی.

## 3.7 محاسبات اولیه بار و موتور

### نیروی موردنیاز X

- جرم متحرک X: گنتری Z (10kg) + سینی + امانت (17kg) + موتور Y (0.3kg) ≈ 27kg
- اصطکاک ریل MGN15: μ≈0.005 → F_friction = 27×9.81×0.005 ≈ 1.3N
- شتاب 0.5 m/s² → F_accel = 27×0.5 = 13.5N
- جمع ≈ 15N → با ضریب 2 → 30N
- Pulley radius 7.8mm → Torque = 30N × 0.0078m = 0.23Nm — NEMA23 با 1.2Nm کافی است (ضریب 5).

### نیروی موردنیاز Z

- جرم متحرک Z: کل گنتری + بار ≈ 27kg
- نیروی وزن: 27×9.81 = 265N
- Lead Screw راندمان ~40% → Torque = (F×Pitch)/(2π×η) = (265×0.008)/(2π×0.4) ≈ 0.84Nm
- با ضریب 1.5 → 1.26Nm — NEMA23 2.2Nm کافی است.

> این محاسبات اولیه هستند و باید با تست واقعی تأیید شوند — ادعای قطعی تحمل بار بدون تست نشده است (الزام §5).

## 3.8 فضای موردنیاز مکانیزم

| فضای اضافه | مقدار | توضیح |
|------------|-------|-------|
| X Mechanism Depth | 80mm | ریل + کالسکه + تسمه جلوی خانه‌ها |
| Z Mechanism Bottom | 50mm | موتور + پولی‌های پایین |
| Z Mechanism Top | 30mm | بلبرینگ و پولی بالا |
| Y Mechanism | روی Z_Carriage | بدون فضای اضافه خارجی |
| Cable Chain Z | 30mm | کنار ریل Z |
| **جمع اضافه به عمق** | 120mm | در محاسبه External_Depth لحاظ شده |
| **جمع اضافه به ارتفاع** | 80mm | در External_Height لحاظ شده |

