# 2. سازه و بدنه

## 2.1 فلسفه طراحی سازه

- **ماژولار:** فریم از پروفیل 40×40 استاندارد، قابل مونتاژ با پیچ و براکت گوشه‌ای. امکان تغییر ارتفاع/عرض با تغییر یک Global Variable.
- **قابل ساخت:** تمام پنل‌ها با برش لیزر ورق + خم + سوراخ‌کاری. بدون نیاز به قالب تزریق.
- **سرویس‌پذیر:** پنل عقب و پنل کناری با پیچ، قابل باز شدن برای دسترسی به مکانیزم و الکترونیک.
- **پایدار:** 4 پایه قابل تنظیم M10 با لاستیک ضدلغزش، تحمل 400kg.

## 2.2 لیست قطعات سازه

| # | نام فایل (انگلیسی) | تعداد | جنس | ضخامت/مقطع | توضیح |
|---|---------------------|-------|-----|-------------|-------|
| 1 | `Main_Frame.SLDPRT` | 1 | AL 6063-T5 | 40×40×2mm | فریم اصلی — 4 ستون عمودی + 8 تیر افقی |
| 2 | `Vertical_Support.SLDPRT` | 4 | AL 6063 | 40×40×2 | ستون‌های عمودی 2400mm |
| 3 | `Horizontal_Beam_Top.SLDPRT` | 4 | AL | 40×40 | تیرهای بالا |
| 4 | `Horizontal_Beam_Bottom.SLDPRT` | 4 | AL | 40×40 | تیرهای پایین |
| 5 | `Horizontal_Beam_Middle.SLDPRT` | 4 | AL | 40×40 | تیرهای میانی برای تقسیم ارتفاع |
| 6 | `Side_Panel_Left.SLDPRT` | 1 | Steel ST12 | 1.5mm | پنل جانبی چپ، سوراخ تهویه |
| 7 | `Side_Panel_Right.SLDPRT` | 1 | Steel | 1.5mm | با دریچه سرویس 400×600 |
| 8 | `Rear_Panel.SLDPRT` | 1 | Steel | 1.5mm | پنل عقب، 2 تکه برای دسترسی |
| 9 | `Front_Panel_Frame.SLDPRT` | 1 | Steel | 1.5mm | قاب پنل جلو، برش UI |
| 10 | `Top_Cover.SLDPRT` | 1 | Steel | 1.5mm | درب بالا، لولایی |
| 11 | `Bottom_Plate.SLDPRT` | 1 | Steel | 2.0mm | کف، تحمل بار کل |
| 12 | `Compartment_Divider_Vertical.SLDPRT` | 1 | Galv | 1.5mm | جداکننده عمودی میانی، H=2000 |
| 13 | `Compartment_Divider_Horizontal.SLDPRT` | 4 | Galv | 1.5mm | جداکننده افقی بین ردیف‌ها |
| 14 | `Compartment_Floor.SLDPRT` | 10 | Galv | 1.5mm | کف هر خانه (400×500) — از یک فایل با Pattern |
| 15 | `Compartment_Shelf.SLDPRT` | 5 | Galv | 1.5mm | طبقه — نگهدارنده کف‌ها |
| 16 | `Compartment_Door.SLDPRT` | 10 | Steel | 2.0mm | درب هر خانه، 398×398 (لقی 1mm هر طرف) |
| 17 | `Hinge_Concealed.SLDPRT` | 20 | Steel | — | لولای مخفی 270°، 2 عدد هر درب |
| 18 | `Door_Lock_Bracket.SLDPRT` | 10 | Steel | 2mm | براکت قفل الکترومگنت |
| 19 | `Mounting_Bracket_Corner.SLDPRT` | 24 | Steel | 3mm | براکت گوشه‌ای فریم |
| 20 | `Mounting_Bracket_Rail.SLDPRT` | 8 | Steel | 3mm | براکت نصب ریل |
| 21 | `Foot_Adjustable.SLDPRT` | 4 | Steel+Rubber | M10 | پایه قابل تنظیم، ارتفاع 50±15mm |
| 22 | `Service_Access_Panel.SLDPRT` | 2 | Steel | 1.5mm | دریچه سرویس کناری و عقب |
| 23 | `Fastener_M5x12.SLDPRT` | ~120 | Steel | M5×12 | پیچ پنل (Placeholder) |
| 24 | `Fastener_M8x20.SLDPRT` | ~48 | Steel | M8×20 | پیچ فریم |

> **نکته پارامتریک:** تمام ابعاد ورق‌ها (طول، عرض، محل سوراخ‌ها) با Equations به `Compartment_Width/Height/Length` متصل است. تغییر ابعاد خانه، تمام پنل‌ها و جداکننده‌ها را به‌روزرسانی می‌کند.

## 2.3 جزئیات هر قطعه

### Main_Frame (فریم اصلی)

- **Feature Tree:**
  ```
  Main_Frame
  ├── Equations (Frame_Profile=40, External_Width=950, etc.)
  ├── Reference Geometry
  │   ├── Origin
  │   ├── Plane_Front, Plane_Top, Plane_Right
  │   └── Axis_Vertical, Axis_Horizontal
  ├── Sketch_Frame_Profile (مقطع 40×40، ضخامت دیواره 2mm)
  ├── Sweep_Vertical_Supports (4× Sweep along vertical lines)
  ├── Sweep_Horizontal_Top (4× Sweep)
  ├── Sweep_Horizontal_Bottom (4× Sweep)
  ├── Sweep_Horizontal_Middle (4× Sweep at Z=600, 1200)
  ├── Sketch_Mounting_Holes (HoleWizard M8)
  ├── Mounting_Holes_Cut
  ├── Sketch_Rail_Mounting_Points
  ├── Rail_Mounting_Holes_Cut (M5 for MGN15)
  ├── Fillet_Frame_Edges (R2)
  └── Chamfer_Bottom (1×45°)
  ```
- **ویژگی:** تمام Sweepها از یک Sketch مقطع مشترک استفاده می‌کنند (Master Sketch) — تغییر مقطع، کل فریم را تغییر می‌دهد.

### Compartment (خانه — Instance)

- فایل پایه `Compartment.SLDPRT` یک خانه را تعریف می‌کند (کف + دیواره‌های جانبی + دیواره عقب).
- در Assembly با **Linear Pattern** یا **10 Instance** تکرار می‌شود — نه 10 فایل جداگانه.
- دیواره‌های مشترک (جداکننده‌ها) به‌صورت جداگانه مدل شده‌اند تا ضخامت مضاعف ایجاد نشود.

### Compartment_Door

- ابعاد: 398×398×2mm (400 منهای 1mm لقی هر طرف).
- لولا: 2× Hinge_Concealed در سمت راست (برای ستون چپ) یا چپ (برای ستون راست) — بازشو 100° به بیرون.
- قفل: الکترومگنت 12V Placeholder در سمت مخالف لولا.
- سنسور: Reed Switch Placeholder برای تشخیص باز/بسته بودن.
- **فضای باز شدن:** درب 398mm عرض دارد و 90° باز می‌شود؛ نیاز به 400mm فضای آزاد جلویی دارد که با فاصله گنتری (15mm) + فضای UI تأمین شده. در طراحی، درب‌ها فقط هنگام سرویس یا توسط مکانیزم داخلی باز نمی‌شوند — درب‌ها برای دسترسی کاربر نهایی نیستند؛ امانت از طریق سینی وارد/خارج می‌شود. (در صورت نیاز به درب کاربری، فضای بازشو در Front_Panel لحاظ شده.)

### Side_Panel و Rear_Panel

- ورق 1.5mm با **Sheet Metal Features:** Base Flange + Edge Flange (خم 90° برای اتصال به فریم).
- سوراخ‌های تهویه: Linear Pattern اسلات 20×5mm، 10 ردیف.
- دریچه سرویس: برش 400×600mm با درب لولایی و قفل پیچی.

## 2.4 اتصالات و Fasteners

- فریم: پیچ M8×20 + مهره T-Slot (برای پروفیل آلومینیوم) — 48 عدد.
- پنل‌ها: پیچ M5×12 خودکار + واشر — 120 عدد.
- ریل‌ها: پیچ M5×16 سر تخت — 64 عدد.
- پایه‌ها: پیچ M10×30 + مهره تنظیم ارتفاع.
- تمام Fastenerها به‌صورت Part جداگانه با **Toolbox Placeholder** مدل شده‌اند و در Assembly با **Pattern Driven** تکرار می‌شوند.

## 2.5 تلرانس و لقی

| محل | لقی/تلرانس | دلیل |
|-----|-----------|------|
| درب تا فریم | 1mm هر طرف | جلوگیری از گیرکردن، جبران انبساط |
| جداکننده تا پنل | 0.5mm | مونتاژ آسان |
| ریل تا براکت | ±0.1mm | دقت حرکتی |
| سینی تا دیواره خانه | 10mm هر طرف (سینی 380mm در خانه 400mm) | جلوگیری از برخورد |
| بار تا سقف خانه | 20mm (بار 380mm ارتفاع در خانه 400mm) | فضای تنفس |

## 2.6 قابلیت ساخت

- **برش ورق:** تمام پنل‌ها و جداکننده‌ها با لیزر CO2 قابل برش هستند. فایل DXF از هر Part قابل Export است.
- **خم‌کاری:** لبه‌های پنل با پرس برک خم 90° (شعاع 2mm).
- **سوراخ‌کاری:** HoleWizard M5/M8 با استاندارد ISO.
- **جوش:** در نسخه فولادی، اتصالات فریم با جوش MIG؛ در نسخه آلومینیومی، فقط پیچ و براکت (بدون جوش).
- **رنگ:** پودری RAL 7035 (خاکستری روشن) برای پنل‌ها، آنودایز برای پروفیل آلومینیوم.
