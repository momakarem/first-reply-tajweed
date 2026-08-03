<div dir="rtl">

# 🚀 First Reply Tajweed Bot

**بوت تليجرام ذكي للرد التلقائي بسرعة البرق على أول صورة في جروبات التجويد**

</div>

---

## 📋 Table of Contents

- [ملخص المشروع](#-ملخص-المشروع)
- [كيف بيشتغل؟ (The Big Picture)](#-كيف-بيشتغل-the-big-picture)
- [نظام الـ Triple Window](#-نظام-الـ-triple-window)
- [هيكل الملفات بالتفصيل](#-هيكل-الملفات-بالتفصيل)
- [متغيرات البيئة (.env)](#-متغيرات-البيئة-env)
- [تقنيات مضادة للكشف (Anti-Detection)](#-تقنيات-مضادة-للكشف-anti-detection)
- [أوامر البوت](#-أوامر-البوت)
- [طرق التشغيل](#-طرق-التشغيل)
- [التثبيت والإعداد](#-التثبيت-والإعداد)
- [النشر على EasyPanel/Docker](#-النشر-على-easypaneldocker)
- [Crash Recovery](#-crash-recovery)
- [Technology Stack](#-technology-stack)

---

## 🎯 ملخص المشروع

**First Reply Tajweed** هو نظام بوت تليجرام بيعمل حاجتين في نفس الوقت:

1. **Userbot (حساب شخصي):** بيستخدم مكتبة **Telethon** عشان يتصل بحسابك الشخصي على تليجرام ويراقب جروب معين. أول ما صورة تنزل في الجروب — يرد عليها فوراً (Zero Delay) بنص معين.

2. **Control Bot (بوت تحكم):** بوت تليجرام عادي (عن طريق **python-telegram-bot**) بتتحكم فيه بأوامر `/arm` و `/stop` و `/status` عشان تجدول الرد وتتابع الحالة.

### الهدف الأساسي

البوت مصمم عشان يكون **أول واحد يرد** على صورة بتتنزل في جروب تجويد/قرآن في وقت محدد. بيستخدم تقنيات متقدمة عشان:
- يرد بأقل latency ممكنة (عادة أقل من 500ms)
- يبان كأنه مستخدم عادي (device spoofing + typing simulation)
- يقدر يتعافى من الكراشات والريستارت

---

## 🔄 كيف بيشتغل؟ (The Big Picture)

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                 │
│  ┌──────────────────────┐     ┌───────────────────────────┐     │
│  │     Control Bot      │     │        Userbot            │     │
│  │  (python-telegram-bot)│     │      (Telethon)           │     │
│  │                      │     │                           │     │
│  │  /arm HH:MM ─────────┼────▶│  scheduler.py             │     │
│  │  /stop ──────────────┼────▶│  ┌─Phase 1: Connect─┐    │     │
│  │  /status ────────────┤     │  │─Phase 2: Typing──│    │     │
│  │                      │     │  │─Phase 3: Snipe───│    │     │
│  │  Inline Keyboard     │     │  └──────────────────┘    │     │
│  │  (Group Selection)   │     │                           │     │
│  └──────────────────────┘     │  Event: Photo ──▶ Reply!  │     │
│                               └───────────────────────────┘     │
│                                                                 │
│  state.py ◄──── Shared State (in-memory) ────▶ persistent_state │
│  config.py ◄── .env file                                        │
└─────────────────────────────────────────────────────────────────┘
```

### تدفق العمل (Flow)

1. **المستخدم** يبعت `/arm 11:15` للـ Control Bot
2. **Control Bot** يعرض كيبورد Inline عشان تختار الجروب المستهدف
3. بعد اختيار الجروب → الـ **Scheduler** يشتغل بنظام Triple Window
4. في الوقت المناسب → الـ **Userbot** يتصل بالجروب ويبدأ المراقبة
5. أول ما **صورة** تنزل → يرد عليها **فوراً** (Zero Delay)
6. يبعت notification للمالك بالنتيجة والـ latency
7. يفصل الـ Userbot (الـ Control Bot يفضل شغال)

---

## ⏱ نظام الـ Triple Window

ده قلب النظام — مصمم عشان يوازن بين **السرعة** و**التخفي**:

```
Timeline (بالنسبة لوقت الهدف T):

  T-120s          T-90s           T-60s            T+0s           T+180s
    │               │               │               │               │
    ▼               ▼               ▼               ▼               ▼
╔═══════════╗ ╔═══════════╗ ╔════════════════════════════════╗
║  Phase 1  ║ ║  Phase 2  ║ ║          Phase 3               ║
║  CONNECT  ║ ║  TYPING   ║ ║     SILENT SNIPE ⚡            ║
║ & PRELOAD ║ ║ PRESENCE  ║ ║  (Monitoring + Instant Reply)  ║
╚═══════════╝ ╚═══════════╝ ╚════════════════════════════════╝
   30 ثانية      30 ثانية      60 ثانية + 180 ثانية Grace
```

### Phase 1 — CONNECT & PRELOAD (T-120s → T-90s)
- يعيد الاتصال بالـ Userbot لو كان مفصول
- يتحقق إن الـ session لسه شغال
- يعمل cache للـ target entity
- يحمّل نص الرد في الذاكرة مسبقاً

### Phase 2 — TYPING / PRESENCE PROOF (T-90s → T-60s)
- يبعت typing indicator مستمر لمدة 30 ثانية
- ده بيثبت إن "المستخدم" موجود ونشط (Presence Proof)
- بيخلي الأمر يبان طبيعي

### Phase 3 — SILENT SNIPE (T-60s → T+180s)
- بيفعّل المراقبة الصامتة (`monitoring_active = True`)
- **صفر تأخير** — أول ما صورة تنزل:
  1. `ReadHistoryRequest` (يقرأ الرسالة — سلوك بشري)
  2. يبعت الرد فوراً — **بدون أي `sleep` أو تأخير صناعي**
- فترة سماح 3 دقائق بعد الوقت المستهدف
- لو مفيش صورة خلال الـ Grace → يفصل الـ Userbot

---

## 📁 هيكل الملفات بالتفصيل

### 🔸 `main.py` — نقطة الدخول الرئيسية
**الوظيفة:** يشغّل الـ Userbot والـ Control Bot في نفس الـ event loop.

**المكونات:**
| المكون | الوظيفة |
|--------|---------|
| `_RedactFilter` | فلتر logging بيمنع ظهور قيم حساسة (API_HASH, BOT_TOKEN) في الـ logs عن طريق استبدالها بـ `***REDACTED***` |
| `_try_recover_state()` | يحاول يسترجع حالة مجدولة من الملف المحفوظ بعد crash/restart. بيتعامل مع 4 سيناريوهات: جدول مستقبلي، نافذة نشطة (رد لم يُرسل)، رد تم إرساله، جدول منتهي |
| `_run_control_bot()` | يشغّل الـ Control Bot بـ polling مستمر ويسجّل قائمة الأوامر `/arm` `/stop` `/status` |
| `_async_main()` | الـ main coroutine — يبني الـ Control Bot والـ Userbot، يعمل startup checks، يسترجع الحالة، ويشغّل كل حاجة |
| `main()` | نقطة الدخول — `asyncio.run(_async_main())` |

**تدفق التشغيل:**
```
main() → _async_main()
  ├── build_control_bot()     → إنشاء بوت التحكم
  ├── build_userbot()         → إنشاء واتصال الـ Userbot
  ├── run_all_checks()        → فحوصات ما قبل الإقلاع
  ├── _try_recover_state()    → استرجاع حالة سابقة (لو موجودة)
  ├── _run_control_bot()      → تشغيل بوت التحكم (يفضل شغال)
  └── shutdown_event.wait()   → ينتظر إشارة الإيقاف
```

---

### 🔸 `config.py` — تحميل الإعدادات المركزي
**الوظيفة:** يقرأ كل الإعدادات من متغيرات البيئة (`.env`) ويتحقق منها عند الاستيراد.

**المتغيرات المُحملة:**
| المتغير | النوع | الوصف |
|---------|-------|-------|
| `CAIRO_TZ` | `ZoneInfo` | المنطقة الزمنية — القاهرة |
| `API_ID` | `int` | معرف تطبيق Telethon |
| `API_HASH` | `str` | هاش تطبيق Telethon |
| `PHONE` | `str` | رقم الهاتف بالصيغة الدولية |
| `BOT_TOKEN` | `str` | توكن بوت التحكم |
| `OWNER_ID` | `int` | معرف المالك على تليجرام |
| `GROUPS` | `list[dict]` | قائمة الجروبات (حتى 10 جروبات) |
| `TARGET_CHAT` | `str` | الجروب الافتراضي (أول واحد) |
| `DEFAULT_REPLY_TEXT` | `str` | نص الرد الافتراضي |
| `PRE_WINDOW_MINUTES` | `int` | دقائق قبل الهدف (2 افتراضي) |
| `POST_WINDOW_MINUTES` | `int` | دقائق بعد الهدف (3 افتراضي) |
| `USERBOT_SESSION` | `str` | مسار ملف الـ session |
| `ANTI_SPAM_COOLDOWN_SEC` | `float` | مدة الانتظار ضد السبام (2 ثانية) |
| `STATE_FILE` | `str` | مسار ملف الحالة المحفوظة |
| `ALLOWED_SENDER_IDS` | `list[int]` | قائمة بيضاء للمرسلين (اختياري) |
| `CAPTION_KEYWORD` | `str` | كلمة مفتاحية في الوصف (اختياري) |
| `_SENSITIVE_VALUES` | `frozenset` | القيم الحساسة (لا تُسجّل في logs) |

**سلوك خاص:**
- لو `GROUP_1_NAME/ID` مش موجودة → يرجع لـ `TARGET_CHAT` كـ fallback
- لو مفيش أي جروب → البرنامج يقفل فوراً (`sys.exit`)
- على Linux/macOS: يحذّر لو مجلد `sessions/` قابل للقراءة من الكل

---

### 🔸 `userbot.py` — الحساب الشخصي (Telethon)
**الوظيفة:** يتصل بحسابك الشخصي على تليجرام ويراقب الجروب المستهدف للرد على أول صورة.

**المكونات الرئيسية:**

| الدالة/الثابت | الوظيفة |
|-------------|---------|
| `REPLY_VARIANTS` | 4 صيغ مختلفة للرد (تدوير المحتوى — anti-detection) |
| `_DEVICE_MODEL` | هوية الجهاز المزيفة: `Desktop` |
| `_SYSTEM_VERSION` | نظام التشغيل المزيف: `Windows 11` |
| `_APP_VERSION` | إصدار التطبيق المزيف: `Telegram Desktop 7.0.4` |
| `build_userbot()` | ينشئ ويوصّل الـ Client. يدعم وضعين: StringSession (Docker) أو ملف session (محلي) |
| `send_typing()` | يبعت typing indicator مستمر لمدة محددة (Phase 2) |
| `mark_as_read()` | يبعت `ReadHistoryRequest` — يقرأ الرسالة (سلوك بشري) |
| `disconnect_userbot()` | يفصل الـ Userbot بس (الـ Control Bot يفضل شغال) |
| `reconnect_userbot()` | يعيد الاتصال لو الـ Userbot مفصول (يُستدعى في Phase 1) |
| `reset_for_next_arm()` | يعيد تعيين الـ double-response guard لدورة arm جديدة |
| `switch_target_chat()` | يغيّر الجروب المستهدف أثناء التشغيل (inline keyboard) |
| `_on_photo_message()` | **الـ Handler الرئيسي** — يتفعّل لما صورة تنزل |

**تفاصيل `_on_photo_message()` (المسار الساخن — Hot Path):**
```
1. Guard Check      → هل المراقبة نشطة؟ هل الرد اتبعت قبل كده؟
2. Photo Type Check → هل الميديا فعلاً صورة (MessageMediaPhoto)؟
3. Sender Whitelist → هل المرسل في القائمة البيضاء (لو مفعّلة)؟
4. Caption Filter   → هل الوصف فيه الكلمة المطلوبة (لو مفعّل)؟
5. SET GUARD        → _reply_fired = True (atomic boolean)
6. ReadHistory      → قراءة الرسالة (أول action)
7. Send Reply       → الرد الفوري — بدون أي sleep أو delay
8. Record Latency   → يسجّل الوقت الفعلي من وصول الحدث لإرسال الرد
9. Notify Owner     → يبعت notification بالنتيجة والـ latency
10. Disconnect      → يفصل الـ Userbot
```

**تقنيات الحماية:**
- `_reply_fired` — حارس Boolean ذري ضد الرد المزدوج
- Content Rotation — 4 صيغ مختلفة للرد يختار منهم عشوائي
- Rollback on failure — لو الرد فشل، يرجع الحارس ويفعّل المراقبة تاني

---

### 🔸 `control_bot.py` — بوت التحكم عن بعد
**الوظيفة:** بوت تليجرام للتحكم في النظام عن بعد.

**الأوامر:**
| الأمر | الوظيفة |
|-------|---------|
| `/arm HH:MM [am\|pm]` | جدولة نافذة الرد |
| `/stop` | إيقاف كل الجداول |
| `/status` | عرض الحالة الحالية |

**المكونات:**

| المكون | الوظيفة |
|--------|---------|
| `_owner_only` | Decorator أمني — يرفض أي أمر من غير المالك |
| `_owner_only_callback` | Decorator أمني لـ callback queries |
| `_parse_time()` | محلل ذكي للوقت — يدعم 12h/24h/AM/PM ويختار أقرب وقت مستقبلي |
| `_build_group_keyboard()` | يبني Inline Keyboard بزرار لكل جروب |
| `_do_arm()` | منطق الـ Arming المشترك — يحلل الوقت ويعرض الكيبورد |
| `_finalize_arm()` | ينهي عملية الـ Arming بعد اختيار الجروب |
| `_on_group_selected()` | يتعامل مع اختيار الجروب من الكيبورد |
| `_pending_auto_select` | تايمر 15 ثانية — لو مختارش جروب يختار الأول تلقائياً |

**تدفق `/arm`:**
```
/arm 11:15
  ├── Parse time → 11:15 AM or PM (nearest future)
  ├── Single group? → arm immediately
  └── Multiple groups?
       ├── Show inline keyboard
       ├── Start 15s auto-select timer
       └── Wait for selection (or timeout → first group)
            └── _finalize_arm()
                 ├── switch_target_chat() → switch userbot target
                 ├── Update state
                 ├── arm_scheduler() → start triple window
                 └── Edit message → confirmation
```

**تفاصيل `_parse_time()`:**
- يقبل `11:15` / `11:15am` / `11:15pm` / `11:15 PM`
- بدون AM/PM: يجرب الاتنين ويختار أقرب وقت مستقبلي
- لو الوقت فات النهارده → يجدول لبكرة
- يقبل صيغة 24 ساعة مباشرة (مثلاً `22:30`)

---

### 🔸 `scheduler.py` — المجدول ثلاثي النوافذ
**الوظيفة:** ينفذ نظام Triple Window الموضح أعلاه.

**الثوابت:**
| الثابت | القيمة | الوصف |
|--------|--------|-------|
| `CONNECT_BEFORE` | 120s | T-120s: اتصال وتحضير |
| `TYPING_BEFORE` | 90s | T-90s: بدء الـ typing |
| `SNIPE_BEFORE` | 60s | T-60s: بدء المراقبة الصامتة |
| `GRACE_AFTER` | 180s | T+180s: فترة السماح |

**الدوال:**
| الدالة | الوظيفة |
|--------|---------|
| `_run_triple_window()` | الـ coroutine الرئيسي — ينفذ الـ 3 phases بالترتيب |
| `arm_scheduler()` | يلغي أي مهام سابقة ويبدأ triple window جديد |

**حماية ضد التداخل:**
- قبل كل phase → يتحقق إن `state.scheduled_dt == target_dt`
- لو المستخدم عمل `/arm` جديد → المجدول القديم يلغي نفسه تلقائياً
- `CancelledError` متعامل معاه في كل مرحلة

---

### 🔸 `state.py` — الحالة المشتركة
**الوظيفة:** كائن Singleton بيشاركه الـ Userbot والـ Control Bot في نفس العملية.

**الكلاس `BotState`:**

| الخاصية | النوع | الوصف |
|---------|-------|-------|
| `scheduled_dt` | `datetime?` | وقت الهدف المجدول |
| `monitoring_active` | `bool` | هل المراقبة نشطة؟ |
| `reply_text` | `str` | نص الرد |
| `reply_sent` | `bool` | هل الرد اتبعت؟ |
| `_arm_task` | `Task?` | مهمة الـ scheduler الحالية |
| `_stop_task` | `Task?` | مهمة الإيقاف |
| `last_reply_latency_ms` | `float?` | آخر latency |
| `last_reply_at` | `datetime?` | وقت آخر رد |
| `last_reply_msg_id` | `int?` | ID آخر رسالة رد |
| `target_chat_name` | `str` | اسم الجروب الحالي |
| `selected_group_id` | `str` | ID الجروب المختار |
| `selected_group_name` | `str` | اسم الجروب المختار |
| `recovered_from_disk` | `bool` | هل الحالة مسترجعة من الديسك؟ |

**الدوال:**
| الدالة | الوظيفة |
|--------|---------|
| `arm()` | يعيّن جدول جديد ويحفظ على الديسك |
| `reset()` | إعادة تعيين كاملة + حذف ملف الحالة |
| `activate_monitoring()` | تفعيل المراقبة |
| `deactivate_monitoring()` | إلغاء المراقبة |
| `mark_sent()` | يسجّل إن الرد اتبعت + يحفظ |
| `cancel_arm_tasks()` | يلغي مهام asyncio المعلقة |
| `status_text()` | ينتج نص حالة غني (للأمر `/status`) — يكتشف الـ Phase الحالي تلقائياً |

---

### 🔸 `persistent_state.py` — الحالة الدائمة
**الوظيفة:** يحفظ حالة الـ arming على الديسك عشان يقدر يتعافى بعد crash.

**الملف:** `sessions/armed_state.json`

**آلية الكتابة الآمنة (Atomic Write):**
```
1. ينشئ ملف مؤقت (tmpfile)
2. يكتب فيه البيانات + fsync
3. os.replace() → يستبدل الملف الأصلي
4. لو فشل → يحذف الملف المؤقت
```
**ده بيضمن إنه مستحيل يكون فيه ملف ناقص أو فاسد على الديسك.**

**البيانات المحفوظة:**
```json
{
  "scheduled_dt": "2025-01-15T11:15:00+02:00",
  "reply_text": "مروة محروس 17",
  "reply_sent": false,
  "group_id": "-1001234567890",
  "group_name": "مقراه أهل القرآن",
  "saved_at": "2025-01-15T10:30:00+02:00"
}
```

---

### 🔸 `startup_checks.py` — فحوصات ما قبل الإقلاع
**الوظيفة:** يتحقق إن كل الاتصالات والتصاريح صالحة قبل ما النظام يشتغل.

**الفحوصات:**
| الفحص | الوظيفة |
|-------|---------|
| `check_bot_connection()` | يتحقق إن بوت التحكم متصل ومُصرّح |
| `check_owner_access()` | يتحقق إن البوت يقدر يبعت للمالك |
| `check_session_validity()` | يتحقق إن session الـ Userbot شغال |
| `check_target_chat()` | يتحقق إن الـ Userbot يقدر يوصل للجروب المستهدف |

**لو أي فحص فشل → البرنامج يقفل فوراً بدل ما يشتغل بشكل غلط.**

---

### 🔸 `launcher.py` — واجهة التشغيل المحلية
**الوظيفة:** يعرض banner ملون في الكونسول ويدير التشغيل والإيقاف.

**الميزات:**
- Banner ASCII ملون بـ ANSI colors
- يتحقق من وجود ملف `.env`
- يدعم إيقاف بـ `stop`/`quit`/`Ctrl+C`
- يضبط الـ event loop policy على Windows (`WindowsSelectorEventLoopPolicy`)
- يضبط الـ working directory تلقائياً (مهم للـ exe)

---

### 🔸 `create_session.py` — إنشاء Session String
**الوظيفة:** يشغّل **محلياً** مرة واحدة عشان ينشئ `StringSession` لاستخدامه في Docker/EasyPanel.

**الاستخدام:**
```bash
python create_session.py
# → يطلب رقم الهاتف + كود التحقق
# → يطبع StringSession string
# → انسخه وحطه في TELETHON_SESSION env var
```

---

### 🔸 `build_exe.py` — بناء ملف تنفيذي
**الوظيفة:** يستخدم PyInstaller عشان يبني `FirstReplyBot.exe` ويحطه على الـ Desktop.

**الخطوات:**
1. ينسخ كل الملفات لمجلد مؤقت
2. يشغّل PyInstaller بوضع `--onefile`
3. ينتج `FirstReplyBot.exe` على الـ Desktop
4. ينضف مجلد البناء

**ملفات مطلوبة بجانب الـ exe:**
- `.env` (الإعدادات)
- `sessions/` (ملفات الـ session)

---

### 🔸 `FirstReplyBot.bat` — مشغل Windows
**الوظيفة:** ملف batch يعرض banner ويشغّل `launcher.py` على Windows.

- يضبط الترميز لـ UTF-8 (`chcp 65001`)
- يتحقق من `.env`
- يشغّل `python launcher.py`

---

### 🔸 ملفات Docker

#### `Dockerfile`
- مبني على `python:3.12-slim`
- يثبت المتطلبات → ينسخ الكود → يشغّل `python main.py`
- Healthcheck كل 60 ثانية
- Volume لمجلد `/app/sessions`

#### `docker-compose.yml`
- Service واحد: `first-reply`
- Restart policy: `unless-stopped`
- Named volume: `sessions_data`
- Log rotation: 10MB × 3 files

#### `first-reply.service` (systemd)
- Service لنظام Linux
- Security hardening: `NoNewPrivileges`, `ProtectSystem=strict`
- Auto-restart كل 5 ثواني

#### `start.sh`
- Shell script للـ Docker/production
- يتحقق من كل المتغيرات المطلوبة قبل التشغيل

---

## 🔐 متغيرات البيئة (.env)

| المتغير | مطلوب | مثال | الوصف |
|---------|-------|------|-------|
| `API_ID` | ✅ | `12345678` | من [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | ✅ | `0123456789abcdef...` | من [my.telegram.org](https://my.telegram.org) |
| `PHONE` | ✅ | `+201012345678` | رقمك بالصيغة الدولية |
| `BOT_TOKEN` | ✅ | `7654321098:AAF...` | توكن من @BotFather |
| `OWNER_ID` | ✅ | `987654321` | ID حسابك (من @userinfobot) |
| `GROUP_N_NAME` | ✅ | `مقراه أهل القرآن` | اسم الجروب N (من 1 لـ 10) |
| `GROUP_N_ID` | ✅ | `-1001234567890` | ID الجروب N |
| `TARGET_CHAT` | ❌ | `@mygroup` | Fallback لو مفيش GROUP configs |
| `DEFAULT_REPLY_TEXT` | ❌ | `مروة محروس 17` | نص الرد الافتراضي |
| `ALLOWED_SENDER_IDS` | ❌ | `123,456` | قائمة بيضاء للمرسلين |
| `CAPTION_KEYWORD` | ❌ | `تجويد` | كلمة لازم تكون في الوصف |
| `TELETHON_SESSION` | ❌ | `1BVtsOH...` | StringSession (Docker) |

---

## 🛡 تقنيات مضادة للكشف (Anti-Detection)

| التقنية | التفاصيل |
|---------|----------|
| **Device Spoofing** | يظهر كـ `Telegram Desktop 7.0.4` على `Windows 11` باللغة العربية المصرية |
| **ReadHistoryRequest** | يقرأ الرسائل قبل الرد (زي المستخدم العادي) |
| **Content Rotation** | 4 صيغ مختلفة للرد يختار منهم عشوائي كل مرة: `مروه محروس 17` / `مروه محروس ١٧` / `مروة محروس 17` / `مروة محروس ١٧` |
| **Typing Simulation** | يبعت typing indicator لمدة 30 ثانية قبل المراقبة (Phase 2) |
| **Log Redaction** | القيم الحساسة (API_HASH, BOT_TOKEN) بتتشال من الـ logs تلقائياً |
| **Anti-Spam Cooldown** | 2 ثانية بين كل أمر والتاني |

---

## 🤖 أوامر البوت

### `/arm HH:MM [am|pm]`
جدولة نافذة الرد التلقائي.

**أمثلة:**
```
/arm 11:15        → أقرب 11:15 (صباحاً أو مساءً)
/arm 11:15am      → 11:15 صباحاً
/arm 11:15pm      → 11:15 مساءً
/arm 22:30        → 10:30 مساءً (صيغة 24 ساعة)
```

### `/stop`
إيقاف كل الجداول والمراقبة فوراً.

### `/status`
عرض الحالة الحالية بالتفصيل:
- الجروب المختار
- الوقت المستهدف
- الـ Phase الحالي
- حالة المراقبة
- معلومات آخر رد (latency, وقت الإرسال)

---

## 🖥 طرق التشغيل

### 1. تشغيل محلي على Windows
```bash
# الطريقة 1: ملف Batch
FirstReplyBot.bat

# الطريقة 2: Python مباشرة
python launcher.py

# الطريقة 3: main.py مباشرة
python main.py
```

### 2. تشغيل كملف تنفيذي
```bash
python build_exe.py   # يبني FirstReplyBot.exe على الـ Desktop
```

### 3. Docker
```bash
docker-compose up -d
```

### 4. Linux (systemd)
```bash
sudo cp first-reply.service /etc/systemd/system/
sudo systemctl enable first-reply
sudo systemctl start first-reply
```

### 5. EasyPanel
راجع ملف [DEPLOYMENT.md](DEPLOYMENT.md) للتفاصيل.

---

## ⚙️ التثبيت والإعداد

### المتطلبات
- **Python 3.12+**
- حساب تليجرام شخصي (للـ Userbot)
- بوت تليجرام (من @BotFather)

### الخطوات

```bash
# 1. استنسخ المشروع
git clone <repo-url>
cd First-Reply-Tajweed

# 2. ثبّت المتطلبات
pip install -r requirements.txt

# 3. انسخ ملف الإعدادات
cp .env.example .env

# 4. عدّل .env بقيمك الحقيقية
# API_ID, API_HASH, PHONE, BOT_TOKEN, OWNER_ID, GROUP configs

# 5. شغّل البوت
python launcher.py
# أو
python main.py
```

**أول تشغيل:** هيطلب رقم تليفونك + كود التحقق من تليجرام عشان ينشئ الـ session.

---

## 🔄 Crash Recovery

النظام بيتعافى تلقائياً من 4 سيناريوهات بعد أي crash أو restart:

| السيناريو | السلوك |
|-----------|--------|
| **جدول مستقبلي** | يتعاد جدولته تلقائياً |
| **نافذة نشطة + الرد لم يُرسل** | يستكمل المراقبة بباقي الوقت |
| **نافذة نشطة + الرد اتبعت** | يمسح الحالة (مفيش حاجة تتعمل) |
| **الوقت انتهى** | يمسح الحالة |

**المالك بيوصله notification على تليجرام بأي عملية استرجاع.**

---

## 🧰 Technology Stack

| التقنية | الاستخدام |
|---------|----------|
| [Telethon](https://github.com/LonamiWebs/Telethon) `>=1.36.0` | Userbot — MTProto client للحساب الشخصي |
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) `>=21.0` | Control Bot — Bot API (async) |
| [python-dotenv](https://github.com/theskumar/python-dotenv) `>=1.0.0` | تحميل ملف `.env` |
| Python `3.12+` | اللغة الأساسية |
| Docker | containerization |
| PyInstaller | بناء ملف exe |

---

## 📄 License

مشروع خاص — جميع الحقوق محفوظة.

---

<div dir="rtl">

> **ملاحظة:** هذا البوت مصمم للاستخدام الشخصي في جروبات التجويد والقرآن الكريم. استخدمه بمسؤولية. ❤️

</div>
