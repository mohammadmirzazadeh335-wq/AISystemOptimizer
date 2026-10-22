# 5. حرکت واقعی قطعات در SolidWorks — Mateها

## 5.1 اصول کلی

- **شاسی ثابت:** `Main_Frame` و تمام پنل‌ها و جداکننده‌ها با `Fix` یا `Coincident` به Origin قفل شده‌اند — هیچ حرکتی ندارند.
- **قطعات متحرک:** فقط `X_Carriage`, `Z_Carriage`, `Transfer_Tray`, `Rollers`, `Pulleys` آزاد هستند.
- **هیچ قطعه‌ای بدون دلیل Fix نشده** — هر Mate اضافی که حرکت را قفل کند حذف شده است.
- **نام‌گذاری Mateها:** انگلیسی معنادار، مثل `X_LimitDistance_0_480`, `Z_Rail_Coincident_Top`.

## 5.2 لیست کامل Mateها

### گروه 1: ثابت‌سازی شاسی (Grounded)

| Mate | نوع | بین | توضیح |
|------|-----|-----|-------|
| `Frame_Fix` | Fix | Main_Frame ↔ Origin | شاسی مرجع ثابت |
| `Bottom_Plate_Coincident` | Coincident | Bottom_Plate ↔ Frame Bottom Face | کف روی فریم |
| `Side_Panel_Left_Coincident` | Coincident | Side_Panel ↔ Frame Left Face | |
| `Side_Panel_Right_Coincident` | Coincident | ↔ Frame Right | |
| `Rear_Panel_Coincident` | Coincident | ↔ Frame Rear | |
| `Front_Panel_Frame_Coincident` | Coincident | ↔ Frame Front | |
| `Divider_Vertical_Coincident` | Coincident | Divider ↔ Mid Plane | وسط |
| `Divider_Horizontal_01..04_Coincident` | Coincident + Distance | Divider ↔ Frame, Z=401.5,803,1204.5,1606 | هر 401.5mm |
| `Compartment_Floor_01..10_Coincident` | Coincident | Floor ↔ Divider/Shelf | |

### گروه 2: محور X

| Mate | نوع | بین | پارامتر |
|------|-----|-----|---------|
| `X_Rail_Top_Coincident` | Coincident | Linear_Rail_X_Top ↔ Front_Frame_Top_Face | ریل روی فریم جلو |
| `X_Rail_Bottom_Coincident` | Coincident | Linear_Rail_X_Bottom ↔ Front_Frame_Bottom_Face | |
| `X_Rail_Top_Parallel` | Parallel | Rail Axis ↔ Frame X Axis | هم‌راستا |
| `X_Block_Top_Coincident` | Coincident | Guide_Block ↔ Rail Groove | واگن روی ریل (Width Mate جایگزین) |
| `X_Block_Bottom_Coincident` | Coincident | Guide_Block ↔ Rail | |
| `X_Carriage_To_Blocks_Coincident` | Coincident | X_Carriage ↔ 4× Guide_Block Top Face | کالسکه روی واگن‌ها |
| `X_Carriage_Concentric_Blocks` | Concentric | Mounting Holes ↔ Block Holes | سوراخ‌ها هم‌محور |
| **`X_LimitDistance`** | **LimitDistance** | X_Carriage Left Face ↔ Frame Left Face | **Min 0mm, Max 480mm** |
| `X_Carriage_Distance_Y` | Distance | X_Carriage ↔ Frame Front Plane | Y=0 (ثابت، فقط X حرکت می‌کند) |
| `X_Carriage_Distance_Z` | Distance | X_Carriage ↔ Frame Mid Height | Z=1000 (ثابت برای X تنها) — در واقع Z_Carriage جدا |

> **نکته مهم:** برای جلوگیری از Over-Defined، فقط **یک** LimitDistance برای X و یک Coincident برای هر ریل کافی است. Mateهای Distance اضافی روی محورهای قفل‌شده حذف شده‌اند.

### گروه 3: محور Z

| Mate | نوع | بین |
|------|-----|-----|
| `Z_Rail_Left_Coincident` | Coincident | Linear_Rail_Z_Left ↔ X_Carriage Left Face |
| `Z_Rail_Right_Coincident` | Coincident | ↔ X_Carriage Right Face |
| `Z_Block_Coincident` | Coincident | Guide_Block_Z ↔ Rail_Z |
| `Z_Carriage_To_Blocks` | Coincident | Z_Carriage ↔ 4× Guide_Block_Z |
| **`Z_LimitDistance`** | **LimitDistance** | Z_Carriage Bottom ↔ Bottom_Plate Top | Min 0, Max 2120mm |
| `Z_Lead_Screw_Concentric` | Concentric | Lead_Screw ↔ Bearing_Block Bore |
| `Z_Lead_Screw_Coincident` | Coincident | Lead_Screw Shoulder ↔ Bearing Face |
| `Z_Nut_Coincident` | Coincident | Lead_Screw_Nut ↔ Z_Carriage Hole |

### گروه 4: محور Y (سینی)

| Mate | نوع | بین |
|------|-----|-----|
| `Y_Rail_Coincident` | Coincident | Linear_Rail_Y ↔ Z_Carriage Top Face |
| `Y_Block_Coincident` | Coincident | Guide_Block_Y ↔ Rail_Y |
| `Transfer_Tray_To_Blocks` | Coincident | Transfer_Tray ↔ 2× Guide_Block_Y |
| **`Y_LimitDistance`** | **LimitDistance** | Transfer_Tray Rear ↔ Z_Carriage Rear | Min 0, Max 450mm |
| `Y_Rack_Coincident` | Coincident | Rack_Y ↔ Transfer_Tray Bottom |
| `Y_Pinion_Concentric` | Concentric | Pinion_Y ↔ Y_Motor Shaft |
| `Y_Rack_Pinion_Distance` | Distance | Rack Teeth ↔ Pinion Pitch Circle | 0mm (مماس) |

### گروه 5: تسمه و پولی

| Mate | نوع | بین | توضیح |
|------|-----|-----|-------|
| `Pulley_Drive_Concentric` | Concentric | Pulley_GT2 ↔ Shaft_Drive | پولی روی شفت |
| `Pulley_Drive_Coincident` | Coincident | Pulley Face ↔ Shaft Shoulder | |
| `Pulley_Idler_Concentric` | Concentric | Idler Pulley ↔ Idler Shaft | هرزگرد |
| `Belt_Path_Coincident` | Coincident | Belt_GT2 Inner Face ↔ Pulley Groove | مسیر تسمه مماس بر پولی |
| `Belt_Tensioner_Distance` | Distance | Tensioner Block ↔ Frame | قابل تنظیم 0–20mm |
| `Belt_Chain_Mate` | Belt/Chain (Optional) | Drive Pulley ↔ Idler Pulley | نسبت 1:1 — در صورت پشتیبانی SW2025 |

> **توضیح تسمه (§7):** نمایش واقعی حرکت تسمه بسته در SolidWorks محدودیت دارد. دو روش ارائه شده:
> 1. **Belt/Chain Mate** (در صورت سازگاری نسخه) — حرکت چرخشی پولی‌ها همگام می‌شود.
> 2. **Fallback:** تسمه به‌صورت Part ثابت (مسیر شماتیک) مدل شده و حرکت کالسکه با LimitDistance کنترل می‌شود. پولی‌ها با Concentric آزادند تا با موس بچرخند — این برای تست سینماتیک کافی است و در مستندات توضیح داده شده.

### گروه 6: نوار نقاله

| Mate | نوع | بین |
|------|-----|-----|
| `Roller_Drive_Concentric` | Concentric | Roller_Drive ↔ Conveyor_Frame Holes |
| `Roller_Idler_Concentric` | Concentric | Roller_Idler ↔ Frame Holes |
| `Roller_Drive_Coincident` | Coincident | Roller Shoulder ↔ Frame Face |
| `Conveyor_Belt_Coincident` | Coincident | Belt Inner ↔ Roller Surface | مماس |
| `Conveyor_Frame_Coincident` | Coincident | Conveyor_Frame ↔ Bottom_Plate | ثابت |

## 5.3 Mateهای ممنوعه (پرهیز شده)

- ❌ Fix کردن X_Carriage یا Z_Carriage (حرکت قفل می‌شود)
- ❌ دو LimitDistance روی یک محور (Over-defined)
- ❌ Coincident اضافی روی محور حرکت (مثلاً Coincident بین X_Carriage و Frame در جهت X)
- ❌ Lock Rotation روی شفت‌ها (پولی باید بچرخد)
- ❌ Mate متناقض (مثلاً Distance 0 + Limit 0–480 روی یک جفت Face)

## 5.4 تست حرکت با موس

1. باز کردن `Main_Assembly.SLDASM` در SolidWorks.
2. در FeatureManager: `X_Carriage` را انتخاب → با موس Drag در جهت X — باید از 0 تا 480mm حرکت کند و در انتها با Stop برخورد نرم داشته باشد.
3. `Z_Carriage` را Drag در جهت Z — 0 تا 2120mm.
4. `Transfer_Tray` را Drag در جهت Y — 0 تا 450mm.
5. پولی‌ها را بچرخانید — تسمه (در صورت Belt Mate) باید همگام بچرخد.
6. **Interference Detection:** Tools → Interference Detection → Check — باید فقط تماس‌های مجاز (تسمه-پولی، واگن-ریل) گزارش شود.

## 5.5 Motion Study

| Study | نوع | موتور | سناریو |
|-------|-----|-------|--------|
| `Motion_X_Full` | Animation | Linear Motor X: 0→480mm, 3sec | جارو X |
| `Motion_Z_Full` | Animation | Linear Motor Z: 0→2120mm, 8sec | جارو Z |
| `Motion_To_Compartment_06` | Animation | X:0→601.5, Z:0→1003, Y:0→450 | رفت به خانه 06 |
| `Motion_Deposit_Cycle` | Motion Analysis | Sequence: X,Z → Y → Y back → Home | چرخه کامل دریافت |
| `Motion_Retrieval_Cycle` | Motion Analysis | Y→450 → Y→0 → X,Z Home → Conveyor | چرخه تحویل |

> موتورها از نوع **Linear Motor** با پروفیل سرعت ذوزنقه‌ای (Accel 500mm/s²) تعریف شده‌اند.
