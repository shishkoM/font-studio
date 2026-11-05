# Font Studio – כיווץ קובץ ה-EXE

## בקצרה

| | לפני | אחרי |
|---|---|---|
| גודל `FontStudio.exe` | יותר מ-200 מ"ב | **19.05 מ"ב** |
| שינויים בקוד התוכנה (`font_studio.py`) | – | **אין** |

המראה וההתנהגות של התוכנה לא השתנו. השינוי הוא רק ב**מה שנארז** בתוך ה-EXE.

---

## למה הקובץ היה כל כך גדול

פקודת הבנייה המקורית ב-GitHub Actions הייתה:

```
pyinstaller --onefile ... --collect-all PySide6 --collect-all fontTools font_studio.py
```

הדגל `--collect-all PySide6` אורז את **כל** Qt, כולל רכיבים כבדים שהתוכנה לא משתמשת בהם:

- **Qt WebEngine**: דפדפן Chromium שלם (מעל 100 מ"ב לבדו)
- QML / Qt Quick, Qt PDF, מולטימדיה, 3D, Charts, רשת, SQL ועוד
- עשרות פלאגינים, קובצי תרגום ו-`opengl32sw.dll` (כ-20 מ"ב)

בפועל התוכנה מייבאת רק שלושה מודולים: **QtCore, QtGui, QtWidgets**.

---

## מה עשיתי, שלב אחרי שלב

הגודל בכל שלב נמדד בבנייה מקומית:

| שלב | פעולה | גודל |
|---|---|---|
| 0 | בנייה מקורית (`--collect-all`) | מעל 200 מ"ב |
| 1 | מעבר ל-`PySide6-Essentials` ובנייה ללא `--collect-all`, עם קובץ spec שמסנן פלאגינים | 26.8 מ"ב |
| 2 | הסרת DLL-ים מיותרים (רשת, SVG, OpenSSL) | 24.0 מ"ב |
| 3 | דחיסת UPX גם ל-DLL-ים של Qt ו-Python | 20.3 מ"ב |
| 4 | הסרת ה-UCRT (מובנה ב-Windows 10/11) | **19.05 מ"ב** |

### 1. רק החבילה הבסיסית של Qt
- ב-`requirements.txt` החלפתי את `PySide6` (שמושך גם את Addons, WebEngine ו-PDF) ב-**`PySide6-Essentials`**, שמכילה רק את המודולים הבסיסיים.
- ויתרתי על `--collect-all`. במקומו PyInstaller אוסף רק את מה שהקוד באמת מייבא.

### 2. קובץ בנייה ייעודי: `packaging/fontstudio.spec`
הקובץ מסנן את מה שנכנס לחבילה:

**פלאגינים של Qt.** מכל הפלאגינים נשארו רק שלושה:

| פלאגין | למה הוא נחוץ |
|---|---|
| `platforms/qwindows.dll` | הצגת חלונות ב-Windows |
| `styles/qmodernwindowsstyle.dll` | המראה של Windows 10/11 (בלעדיו המראה היה משתנה) |
| `imageformats/qico.dll` | טעינת אייקון החלון (`fontstudio.ico`) |

**קבצים שהוסרו:**

| קובץ | למה אפשר בלי |
|---|---|
| `opengl32sw.dll`, `d3dcompiler_47.dll` | OpenGL בתוכנה, לא בשימוש |
| `Qt6Network.dll`, `Qt6Svg.dll` וכו' | נמשכו דרך hooks, אבל אף DLL שבשימוש לא תלוי בהם (נבדק בטבלת ה-imports של כל DLL) |
| `libcrypto-3.dll`, `libssl-3.dll`, `_ssl.pyd`, `_hashlib.pyd` | התוכנה לא מתחברת לרשת. SHA-256 עובד דרך המודול `_sha2` שמובנה ב-Python |
| קובצי תרגום של Qt (`*.qm`) | הקוד לא טוען `QTranslator` |
| `ucrtbase.dll`, `api-ms-win-*.dll` | חלק מ-Windows 10/11, וזו ממילא הדרישה המינימלית של Qt 6 |
| מודולי Python כמו `tkinter`, `unittest`, `pydoc` | לא בשימוש |

### 3. דחיסת UPX, כולל ה-DLL-ים של Qt
PyInstaller מדלג בכוונה על דחיסת UPX במקרים הבאים, ולכן ב-spec יש עקיפות:

1. **DLL-ים עם Control Flow Guard (CFG):** כל ה-DLL-ים של Qt בנויים כך. ה-spec מבטל את הבדיקה ומעביר ל-UPX את הדגל `--force`. הדחיסה מסירה רק את סימון ההקשחה של CFG ולא משנה את הפעולה.
2. **`Qt6Core.dll` מזוהה בטעות כפלאגין:** הוא מכיל את המחרוזת שמסמנת פלאגין. ה-spec מחריג אותו מהבדיקה. הפלאגינים האמיתיים נשארים לא דחוסים, כי Qt צריך לקרוא את המטא-דאטה שלהם.

התוצאה: `Qt6Gui.dll` ירד מ-9.7 ל-3.8 מ"ב, `Qt6Widgets.dll` מ-6.5 ל-2.7 מ"ב, וגם `Qt6Core.dll` ו-`python312.dll` נדחסו.

---

## בדיקות שבוצעו

הרצתי את ה-EXE החדש ואת קוד המקור (`python font_studio.py`) זה לצד זה, על אותם 8 קובצי גופן מ-`C:\Windows\Fonts`:

- ✅ החלון נפתח, האייקון מוצג, והמראה **זהה** בצילומי המסך (עברית מימין לשמאל, צבעים, כפתורים, תצוגה מקדימה של הגופנים).
- ✅ הסריקה מזהה את **אותם 7 גופנים עם אותן שפות** כמו קוד המקור.
- ✅ נוצרים מסד הנתונים (`fontstudio.sqlite3`), קובץ ההגדרות ותיקיית הגיבויים.
- ⚠️ לא נבדקו בלחיצות: החלונות "התנסות", "השוואת גופנים", "צבע התצוגה" וההתקנה ל-Windows. הם בנויים מאותם רכיבי QtWidgets שנכללו, אבל מומלץ לעבור עליהם פעם אחת לפני הפצה.

### תקלה שהתגלתה ותוקנה במהלך העבודה
בניסיון הראשון הוצאתי מהחבילה גם תתי-חבילות של `fontTools` שנראו לא נחוצות. הסריקה לא מצאה אף גופן: השגיאה נבלעה בשקט והקבצים דולגו. הסיבה היא ש-`fontTools.ttLib` טוען חלק מהמודולים שלו רק בזמן ריצה. החזרתי אותם במלואם (`ttLib`, `cffLib`, `misc`), והסריקה עובדת.

---

## 🐞 דיווח באג: קובצי `.ttc` / `.otc` לא נכנסים לספרייה

**הבאג קיים גם בגרסה המקורית ואינו קשור לכיווץ.** לא תיקנתי אותו, כדי לא לשנות את פעולת התוכנה.

**תיאור:** התוכנה מכריזה על תמיכה ב-`.ttc` וב-`.otc` (`EXTENSIONS` בשורה 18), אבל קבצים כאלה תמיד מדולגים בסריקה ולא מופיעים ברשימה.

**שחזור:**
1. להעתיק את `C:\Windows\Fonts\msgothic.ttc` לתיקיית `FontLibrary`.
2. להפעיל את התוכנה או ללחוץ "סריקה".
3. הגופן לא מופיע, בלי הודעת שגיאה (רק מונה הדילוגים עולה).

**סיבה:** הפונקציה `font_metadata()` (שורה 97) פותחת את הקובץ כך:

```python
font = TTFont(str(path), lazy=True, ...)
```

קובץ `.ttc` הוא **אוסף** של כמה גופנים, ו-fontTools דורש לציין איזה מהם לפתוח:

```
TTLibFileIsCollectionError: specify a font number between 0 and 2 (inclusive)
```

השגיאה נתפסת ב-`except Exception` של לולאת הסריקה, והקובץ נספר כ"דולג".

**הצעת תיקון:** לזהות אוסף ולקרוא ממנו לפחות את הגופן הראשון, למשל `TTFont(path, fontNumber=0, ...)`. אפשרות מלאה יותר היא לעבור על כל הגופנים באוסף עם `fontTools.ttLib.TTCollection` ולרשום כל אחד מהם. כדאי גם לבדוק שתצוגת הגופן ב-Qt (`QFontDatabase.addApplicationFont`) מטפלת נכון בכל הגופנים שבאוסף.

---

## קבצים שהשתנו

| קובץ | שינוי |
|---|---|
| `packaging/fontstudio.spec` | **חדש**: הגדרות הבנייה המצומצמת |
| `requirements.txt` | `PySide6` הוחלף ב-`PySide6-Essentials` |
| `.github/workflows/build-windows.yml` | התקנת UPX ובנייה לפי ה-spec, כולל הדפסת גודל הקובץ |
| `.gitignore` | חריגה כדי שקובץ ה-spec ייכלל ב-git (`*.spec` הוחרג בו) |
| `font_studio.py` | **לא שונה** |

## איך בונים

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller
winget install upx          # או: choco install upx
$env:PYINSTALLER_CONFIG_DIR = 'C:\font-studio\build\pyi-cache'
pyinstaller --noconfirm --clean packaging/fontstudio.spec
```

הקובץ נוצר ב-`dist\FontStudio.exe`.

> **שימו לב:** אם בנתיב תיקיית המשתמש יש תווים שאינם באנגלית (למשל שם משתמש בעברית), UPX נכשל בתיקיית המטמון שנמצאת שם כברירת מחדל. לכן מגדירים את `PYINSTALLER_CONFIG_DIR` לנתיב באנגלית בלבד.
>
> **בנייה ב-GitHub Actions:** ה-workflow עודכן, אבל עדיין לא הורץ. הבדיקות כאן נעשו על בנייה מקומית.
