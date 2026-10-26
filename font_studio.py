# -*- coding: utf-8 -*-
"""Font Studio - Hebrew RTL font library and preview manager."""
from __future__ import annotations
import os, sys, json, sqlite3, hashlib, shutil, re, threading, time, traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QObject, Signal, QRunnable, QThreadPool, QSize, QSortFilterProxyModel
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QColor, QPen, QFontMetrics, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSlider, QCheckBox, QListView, QProgressBar, QFileDialog, QMessageBox,
    QDialog, QTextEdit, QSpinBox, QDialogButtonBox, QFrame, QMenu, QSplitter, QToolButton, QStatusBar, QStyle, QColorDialog)

APP_NAME = "Font Studio"
SAMPLE_SENTENCE = "דג סקרן שט לו בים זך אך לפתע פגש חבורה נחמדה שצצה כך"
SAMPLE_ALPHABET = "אבגדהוזחטיכלמנסעפצקרשת"
EXTENSIONS = {'.ttf', '.otf', '.ttc', '.otc'}
LANGUAGE_LABELS = [('all', 'כל השפות'), ('he', 'עברית'), ('en', 'אנגלית / לטינית'), ('ar', 'ערבית'), ('ru', 'קירילית'), ('el', 'יוונית'), ('zh', 'סינית'), ('ja', 'יפנית'), ('ko', 'קוריאנית')]
LANGUAGE_SAMPLES = {
    'he': SAMPLE_SENTENCE, 'en': 'The quick brown fox jumps over the lazy dog',
    'ar': 'نص عربي لتجربة شكل الخط ووضوح الحروف', 'ru': 'Съешь же ещё этих мягких французских булок',
    'el': 'Ταχίστη αλώπηξ βαφής ψημένη γη', 'zh': '天地玄黃 宇宙洪荒', 'ja': 'いろはにほへと ちりぬるを',
    'ko': '키스의 고유조건은 입술끼리 만나야 하고 특별한 기술은 필요치 않다'
}
SCRIPT_RANGES = {
    'he': [(0x0590,0x05FF),(0xFB1D,0xFB4F)], 'en': [(0x0041,0x005A),(0x0061,0x007A)],
    'ar': [(0x0600,0x06FF),(0x0750,0x077F),(0xFB50,0xFDFF),(0xFE70,0xFEFF)],
    'ru': [(0x0400,0x052F)], 'el': [(0x0370,0x03FF),(0x1F00,0x1FFF)],
    'zh': [(0x3400,0x4DBF),(0x4E00,0x9FFF),(0xF900,0xFAFF)],
    'ja': [(0x3040,0x30FF),(0x31F0,0x31FF)], 'ko': [(0xAC00,0xD7AF),(0x1100,0x11FF)]
}
def font_languages(font):
    # Determine actual script coverage from cmap metadata, never from filename.
    try: codepoints = set((font.getBestCmap() or {}).keys())
    except Exception: codepoints = set()
    return [lang for lang, ranges in SCRIPT_RANGES.items() if any(a <= cp <= b for cp in codepoints for a,b in ranges)]


def app_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent

ROOT = app_root()
try:
    DATA_DIR = ROOT / 'FontStudioData'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    probe = DATA_DIR / '.write-test'; probe.write_text('ok', encoding='utf-8'); probe.unlink()
except OSError:
    DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'FontStudio'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR = ROOT / 'FontLibrary'
try:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    p = LIBRARY_DIR / '.write-test'; p.write_text('ok', encoding='utf-8'); p.unlink()
except OSError:
    LIBRARY_DIR = DATA_DIR / 'FontLibrary'
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'fontstudio.sqlite3'
CONFIG_PATH = DATA_DIR / 'settings.json'
BACKUP_DIR = DATA_DIR / 'Backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {'preview_size': 28, 'sample_mode': 'משפט', 'theme': 'בהירה', 'preview_color': '#4e3a98', 'last_scan_done': False}

def load_settings():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        return {**DEFAULT_SETTINGS, **data}
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    tmp = CONFIG_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(CONFIG_PATH)

def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', s).strip(' .')
    return (s or 'Font')[:120]

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def font_metadata(path: Path):
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(str(path), lazy=True, recalcBBoxes=False, recalcTimestamp=False)
        try:
            names = font['name']
            def name(ids):
                for nid in ids:
                    try:
                        value = names.getDebugName(nid)
                        if value and value.strip(): return value.strip()
                    except Exception: pass
                return ''
            family = name([16, 1]) or path.stem
            subfamily = name([17, 2]) or 'Regular'
            weight_class = None
            try: weight_class = int(font['OS/2'].usWeightClass)
            except Exception: pass
            weight = subfamily if weight_class is None else f'{subfamily} ({weight_class})'
            languages = font_languages(font)
            return family, subfamily, weight, languages
        finally: font.close()
    except Exception as e:
        raise ValueError(str(e)) from e

class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=NORMAL')
            self.conn.execute('PRAGMA busy_timeout=30000')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS fonts (
                id INTEGER PRIMARY KEY, family TEXT NOT NULL, subfamily TEXT NOT NULL, weight TEXT NOT NULL,
                path TEXT NOT NULL, source_path TEXT, size INTEGER NOT NULL, sha256 TEXT NOT NULL UNIQUE,
                favorite INTEGER NOT NULL DEFAULT 0, installed INTEGER NOT NULL DEFAULT 0,
                missing INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL, languages TEXT NOT NULL DEFAULT '[]')''')
            columns = {r[1] for r in self.conn.execute('PRAGMA table_info(fonts)')}
            if 'languages' not in columns:
                self.conn.execute("ALTER TABLE fonts ADD COLUMN languages TEXT NOT NULL DEFAULT '[]'")
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_fonts_family ON fonts(family COLLATE NOCASE)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_fonts_sha ON fonts(sha256)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_fonts_fav ON fonts(favorite)')
    def backup(self):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        dest = BACKUP_DIR / f'FontStudioData-{stamp}.sqlite3'
        with self.lock:
            out = sqlite3.connect(dest)
            try: self.conn.backup(out)
            finally: out.close()
        cfg = BACKUP_DIR / f'settings-{stamp}.json'
        if CONFIG_PATH.exists(): shutil.copy2(CONFIG_PATH, cfg)
        # Bound backup growth: keep newest 20 database backups and matching settings snapshots.
        for p in sorted(BACKUP_DIR.glob('FontStudioData-*.sqlite3'), key=lambda x: x.stat().st_mtime, reverse=True)[20:]:
            try: p.unlink()
            except OSError: pass
    def rows(self, query='', favorites=False, language='all'):
        sql = '''SELECT family, COUNT(*) count, GROUP_CONCAT(DISTINCT subfamily) weights,
                 MAX(favorite) favorite, MAX(installed) installed, SUM(missing) missing, MIN(path) path
                 FROM fonts WHERE 1=1'''
        args=[]
        if query:
            sql += ' AND (family LIKE ? OR subfamily LIKE ? OR weight LIKE ?)'
            q=f'%{query}%'; args += [q,q,q]
        if favorites: sql += ' AND favorite=1'
        if language != 'all':
            sql += ' AND languages LIKE ?'; args.append(f'%\"{language}\"%')
        sql += ' GROUP BY family COLLATE NOCASE ORDER BY family COLLATE NOCASE LIMIT 50000'
        with self.lock: return [dict(r) for r in self.conn.execute(sql,args).fetchall()]
    def family_fonts(self, family):
        with self.lock:
            return [dict(r) for r in self.conn.execute('SELECT * FROM fonts WHERE family=? COLLATE NOCASE ORDER BY subfamily COLLATE NOCASE', (family,)).fetchall()]
    def toggle_favorite(self, family):
        self.backup()
        with self.lock, self.conn:
            cur=self.conn.execute('SELECT MAX(favorite) FROM fonts WHERE family=? COLLATE NOCASE',(family,)).fetchone()[0]
            new=0 if cur else 1
            self.conn.execute('UPDATE fonts SET favorite=? WHERE family=? COLLATE NOCASE',(new,family))
    def close(self): self.conn.close()

class WorkerSignals(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)
    error = Signal(str)

class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__(); self.fn=fn; self.signals=WorkerSignals()
    def run(self):
        try: self.signals.done.emit(self.fn(self.signals.progress.emit))
        except Exception: self.signals.error.emit(traceback.format_exc())

class FontListModel(QAbstractListModel):
    FamilyRole = Qt.ItemDataRole.UserRole + 1
    def __init__(self): super().__init__(); self.items=[]
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.items)
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        item=self.items[index.row()]
        if role == self.FamilyRole: return item
        if role == Qt.ItemDataRole.DisplayRole: return item['family']
        if role == Qt.ItemDataRole.SizeHintRole: return QSize(700, 128)
        return None
    def replace(self, items):
        self.beginResetModel(); self.items=items; self.endResetModel()

class FontDelegate:
    """Kept as a helper; the list view uses a lightweight QWidget per visible row via QListView delegate below."""

from PySide6.QtWidgets import QStyledItemDelegate
class FamilyDelegate(QStyledItemDelegate):
    def __init__(self, owner):
        super().__init__(owner); self.owner=owner; self._font_ids={}
    def font_for_item(self, item):
        path=item.get('path','')
        if path and Path(path).is_file():
            if path not in self._font_ids:
                self._font_ids[path]=QFontDatabase.addApplicationFont(path)
            fid=self._font_ids[path]
            families=QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if families: return QFont(families[0])
        return QFont(item.get('family','Segoe UI'))
    def paint(self, painter, option, index):
        item=index.data(FontListModel.FamilyRole) or {}
        painter.save(); rect=option.rect.adjusted(7,5,-7,-5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#e3def7'))); painter.setBrush(QColor('#f7f5ff' if option.state & QStyle.StateFlag.State_Selected else '#ffffff'))
        painter.drawRoundedRect(rect,12,12)
        right=rect.right()-18; y=rect.top()+24
        painter.setPen(QColor('#27223b')); painter.setFont(QFont('Segoe UI', 13, QFont.Weight.DemiBold))
        painter.drawText(right-500,y,500,24,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,item.get('family',''))
        painter.setFont(QFont('Segoe UI', 9)); painter.setPen(QColor('#77718a'))
        weights=', '.join((item.get('weights') or '').split(','))
        painter.drawText(right-650,y+25,650,20,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter, f"{item.get('count',0)} סגנונות  •  {weights[:110]}")
        lang=self.owner.current_language()
        sample=(SAMPLE_ALPHABET if self.owner.settings.get('sample_mode')=='אלפבית' else SAMPLE_SENTENCE) if lang in ('all','he') else LANGUAGE_SAMPLES.get(lang, SAMPLE_SENTENCE)
        font=self.font_for_item(item); font.setPointSize(int(self.owner.settings.get('preview_size',28)))
        painter.setFont(font); painter.setPen(QColor(self.owner.settings.get('preview_color','#4e3a98'))) 
        sample_rect=rect.adjusted(18,55,-300,-8)
        painter.drawText(sample_rect,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,sample)
        # Clickable action chips are painted by the delegate, avoiding thousands of QWidget controls.
        actions=[('התנסות', 'try'), ('התקנה', 'install'), ('☆' if not item.get('favorite') else '★', 'favorite')]
        x=rect.right()-112
        painter.setFont(QFont('Segoe UI',8,QFont.Weight.DemiBold))
        for label, key in actions:
            w=76 if key!='favorite' else 30
            button_rect=__import__('PySide6.QtCore',fromlist=['QRect']).QRect(x-w+1,rect.top()+72,w,28)
            painter.setPen(QPen(QColor('#d8cffb'))); painter.setBrush(QColor('#eee9ff'))
            painter.drawRoundedRect(button_rect,7,7)
            painter.setPen(QColor('#5c3bd6')); painter.drawText(button_rect,Qt.AlignmentFlag.AlignCenter,label)
            x-=w+5
        painter.setPen(QColor('#6d4aff')); painter.setFont(QFont('Segoe UI',9,QFont.Weight.DemiBold))
        painter.drawText(rect.left()+14,rect.top()+24,150,20,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'★' if item.get('favorite') else '☆')
        painter.setPen(QColor('#8c859f')); painter.setFont(QFont('Segoe UI',8))
        status = 'חסר קובץ' if item.get('missing') else ('מותקן' if item.get('installed') else 'לא מותקן')
        painter.drawText(rect.left()+14,rect.top()+48,160,20,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,status)
        painter.restore()
    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent, QRect
        if event.type() != QEvent.Type.MouseButtonRelease or event.button() != Qt.MouseButton.LeftButton:
            return False
        item=index.data(FontListModel.FamilyRole) or {}
        rect=option.rect.adjusted(7,5,-7,-5); x=rect.right()-112; y=rect.top()+72
        for label, key in [('התנסות','try'),('התקנה','install'),('☆','favorite')]:
            w=76 if key!='favorite' else 30
            hit=QRect(x-w+1,y,w,28)
            if hit.contains(event.position().toPoint()):
                if key=='try': self.owner.try_family(item.get('family',''))
                elif key=='install': self.owner.install_family(item.get('family',''))
                else: self.owner.db.toggle_favorite(item.get('family','')); self.owner.refresh()
                return True
            x-=w+5
        return False
    def sizeHint(self, option, index): return QSize(700, 128)

class TryDialog(QDialog):
    """Live preview: the editable text itself uses the selected font and preview color."""
    def __init__(self, family, fonts, parent=None):
        super().__init__(parent); self.setWindowTitle(f'התנסות בגופן — {family}'); self.setMinimumSize(680,430); self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.parent_window=parent; self._font_ids={}
        layout=QVBoxLayout(self)
        top=QHBoxLayout(); top.addWidget(QLabel('משקל:'))
        self.weight=QComboBox(); self.fonts=fonts
        for f in fonts: self.weight.addItem(f['subfamily'], f['path'])
        top.addWidget(self.weight,2); top.addWidget(QLabel('גודל:'))
        self.size=QSpinBox(); self.size.setRange(8,160); self.size.setValue(int(parent.settings.get('preview_size',36)) if parent else 36); top.addWidget(self.size); layout.addLayout(top)
        self.text=QTextEdit(); self.text.setPlainText(SAMPLE_SENTENCE); self.text.setLayoutDirection(Qt.LayoutDirection.RightToLeft); self.text.setPlaceholderText('הקלד כאן — הטקסט יוצג ישירות בגופן הנבחר'); layout.addWidget(self.text,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(self.reject); buttons.accepted.connect(self.accept); layout.addWidget(buttons)
        self.weight.currentIndexChanged.connect(self.refresh); self.size.valueChanged.connect(self.refresh); self.refresh()
        # Focus the editor as soon as the dialog appears, so typing works immediately.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.text.setFocus)
    def refresh(self):
        path=self.weight.currentData(); fid=-1
        if path and Path(path).is_file():
            if path not in self._font_ids: self._font_ids[path]=QFontDatabase.addApplicationFont(path)
            fid=self._font_ids[path]
        families=QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        font=QFont(families[0] if families else 'Segoe UI'); font.setPointSize(self.size.value())
        # Qt's application font registration exposes the family; explicitly apply the selected face/style too.
        selected = self.weight.currentText().split(' (', 1)[0].strip()
        if selected and selected.lower() not in ('regular', 'normal', 'book'): font.setStyleName(selected)
        self.text.setFont(font)
        color=self.parent_window.settings.get('preview_color','#4e3a98') if self.parent_window else '#4e3a98'
        self.text.setStyleSheet(f'QTextEdit {{ color: {color}; }}')

class FontStudio(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Font Studio'); self.setWindowIcon(QIcon(str(Path(getattr(sys, '_MEIPASS', ROOT)) / 'assets' / 'fontstudio.ico'))); self.resize(1180,850); self.setMinimumSize(900,600); self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.db=Database(); self.settings=load_settings(); self.pool=QThreadPool.globalInstance(); self.cancel_event=threading.Event(); self.busy=False
        self.model=FontListModel(); self.init_ui(); self.apply_theme(); self.refresh()
        if not self.settings.get('last_scan_done'):
            self.statusBar().showMessage('סריקה ראשונית תתחיל כעת. ניתן להמשיך להשתמש בממשק.')
            QTimer.singleShot(350, self.scan_default_locations)
    def init_ui(self):
        central=QWidget(); self.setCentralWidget(central); root=QVBoxLayout(central); root.setContentsMargins(22,18,22,18); root.setSpacing(12)
        header=QHBoxLayout(); title=QLabel('Font Studio'); title.setObjectName('title'); header.addWidget(title); header.addStretch()
        self.theme=QComboBox(); self.theme.addItems(['בהירה','כהה']); self.theme.setCurrentText(self.settings.get('theme','בהירה')); self.theme.currentTextChanged.connect(self.change_theme); header.addWidget(QLabel('ערכת נושא')); header.addWidget(self.theme); self.color_btn=QPushButton('צבע התצוגה'); self.color_btn.clicked.connect(self.choose_preview_color); header.addWidget(self.color_btn); root.addLayout(header)
        subtitle=QLabel('ספריית הגופנים שלך — חיפוש, תצוגה, השוואה והתקנה'); subtitle.setObjectName('subtitle'); root.addWidget(subtitle)
        controls=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText('חיפוש לפי משפחת גופן או משקל…'); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh); controls.addWidget(self.search,1)
        self.favorites=QCheckBox('מועדפים בלבד'); self.favorites.toggled.connect(self.refresh); controls.addWidget(self.favorites)
        self.language=QComboBox(); self.language.setToolTip('הצג רק גופנים שתומכים בכתב של השפה שנבחרה')
        for code,label in LANGUAGE_LABELS: self.language.addItem(label,code)
        self.language.setCurrentIndex(max(0,self.language.findData(self.settings.get('language','all')))); self.language.currentIndexChanged.connect(self.change_language); controls.addWidget(self.language)
        self.scan_btn=QPushButton('סריקה / ייבוא תיקייה'); self.scan_btn.clicked.connect(self.choose_folder); controls.addWidget(self.scan_btn)
        self.cancel_btn=QPushButton('ביטול סריקה'); self.cancel_btn.setVisible(False); self.cancel_btn.clicked.connect(self.cancel_scan); controls.addWidget(self.cancel_btn)
        self.compare_btn=QPushButton('השוואת גופנים'); self.compare_btn.clicked.connect(self.compare_selected); controls.addWidget(self.compare_btn); root.addLayout(controls)
        preview=QHBoxLayout(); preview.addWidget(QLabel('גודל תצוגה')); self.preview_slider=QSlider(Qt.Orientation.Horizontal); self.preview_slider.setRange(14,64); self.preview_slider.setValue(int(self.settings.get('preview_size',28))); self.preview_slider.valueChanged.connect(self.change_preview_size); preview.addWidget(self.preview_slider,1); self.size_label=QLabel(str(self.preview_slider.value())); preview.addWidget(self.size_label)
        preview.addWidget(QLabel('טקסט')); self.sample_mode=QComboBox(); self.sample_mode.addItems(['משפט','אלפבית']); self.sample_mode.setCurrentText(self.settings.get('sample_mode','משפט')); self.sample_mode.currentTextChanged.connect(self.change_sample); preview.addWidget(self.sample_mode); root.addLayout(preview)
        self.list=QListView(); self.list.setModel(self.model); self.list.setItemDelegate(FamilyDelegate(self)); self.list.setUniformItemSizes(True); self.list.setSpacing(2); self.list.setSelectionMode(QListView.SelectionMode.ExtendedSelection); self.list.doubleClicked.connect(self.try_selected); self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.list.customContextMenuRequested.connect(self.context_menu); root.addWidget(self.list,1)
        self.progress=QProgressBar(); self.progress.setVisible(False); self.progress.setTextVisible(True); root.addWidget(self.progress)
        self.statusBar().showMessage('מוכן'); self.statusBar().setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    def apply_theme(self):
        if self.settings.get('theme')=='כהה':
            self.setStyleSheet("QMainWindow,QWidget {background:#191722;color:#f3f0fb;} QLineEdit,QComboBox,QTextEdit,QSpinBox,QListView {background:#242130;border:1px solid #49425f;border-radius:8px;padding:7px;color:#f3f0fb;} QPushButton {background:#6d4aff;color:white;border:0;border-radius:9px;padding:9px 13px;} QPushButton:hover {background:#8064ff;} QLabel#title {font-size:28px;font-weight:700;color:#c7b8ff;} QLabel#subtitle {color:#b8b0cc;} QProgressBar {border:1px solid #49425f;border-radius:6px;text-align:center;} QProgressBar::chunk {background:#6d4aff;}")
        else:
            self.setStyleSheet("QMainWindow,QWidget {background:#f4f2f9;color:#27223b;} QLineEdit,QComboBox,QTextEdit,QSpinBox,QListView {background:white;border:1px solid #e2deed;border-radius:8px;padding:7px;color:#27223b;} QPushButton {background:#6d4aff;color:white;border:0;border-radius:9px;padding:9px 13px;} QPushButton:hover {background:#8064ff;} QLabel#title {font-size:28px;font-weight:700;color:#5c3bd6;} QLabel#subtitle {color:#77718a;} QProgressBar {border:1px solid #e2deed;border-radius:6px;text-align:center;background:white;} QProgressBar::chunk {background:#6d4aff;}")
    def change_theme(self, value): self.settings['theme']=value; save_settings(self.settings); self.apply_theme(); self.refresh()
    def choose_preview_color(self):
        color=QColorDialog.getColor(QColor(self.settings.get('preview_color','#4e3a98')),self,'בחר צבע תצוגה')
        if color.isValid():
            self.settings['preview_color']=color.name(); save_settings(self.settings); self.list.viewport().update()
    def choose_preview_color(self):
        current=QColor(self.settings.get('preview_color','#4e3a98'))
        color=QColorDialog.getColor(current,self,'בחר צבע תצוגה')
        if color.isValid():
            self.settings['preview_color']=color.name(); save_settings(self.settings); self.list.viewport().update()
    def change_preview_size(self, value): self.settings['preview_size']=value; self.size_label.setText(str(value)); save_settings(self.settings); self.list.viewport().update()
    def change_sample(self, value): self.settings['sample_mode']=value; save_settings(self.settings); self.list.viewport().update()
    def current_language(self): return self.language.currentData() if hasattr(self,'language') else self.settings.get('language','all')
    def change_language(self, _value):
        self.settings['language']=self.current_language(); save_settings(self.settings); self.refresh(); self.list.viewport().update()
    def refresh(self):
        try: self.model.replace(self.db.rows(self.search.text().strip(), self.favorites.isChecked(), self.current_language()))
        except Exception as e: self.statusBar().showMessage(f'שגיאה בטעינת הרשימה: {e}')
    def scan_default_locations(self):
        locations=[]
        if os.name=='nt':
            locations += [Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts', Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Microsoft'/'Windows'/'Fonts']
        locations.append(LIBRARY_DIR)
        # First launch imports only the app's own library to avoid copying the whole Windows font folder by default.
        self.run_scan([LIBRARY_DIR], initial=True)
    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'בחר תיקייה לייבוא גופנים',str(Path.home()))
        if folder: self.run_scan([Path(folder)])
    def set_busy(self, busy):
        self.busy=busy; self.scan_btn.setEnabled(not busy); self.cancel_btn.setVisible(busy); self.cancel_btn.setEnabled(busy); self.progress.setVisible(busy)
        if busy: self.progress.setRange(0,0)
        else: self.progress.setRange(0,100)
    def run_scan(self, roots, initial=False):
        if self.busy: QMessageBox.information(self,'פעולה מתבצעת','כבר מתבצעת סריקה או פעולת ייבוא.'); return
        self.db.backup(); self.set_busy(True); self.cancel_event.clear()
        def work(progress):
            candidates=[]
            for root in roots:
                if not root.exists(): continue
                for base, dirs, files in os.walk(root):
                    dirs[:]=[d for d in dirs if d not in {'System Volume Information','$RECYCLE.BIN','Backups','.git'}]
                    for fn in files:
                        if Path(fn).suffix.lower() in EXTENSIONS: candidates.append(Path(base)/fn)
            total=len(candidates); imported=duplicates=skipped=0
            progress(0,max(total,1),f'נמצאו {total:,} קבצים. מתחיל בדיקה…')
            for i, src in enumerate(candidates,1):
                if self.cancel_event.is_set(): break
                try:
                    size=src.stat().st_size
                    if not size: skipped+=1; continue
                    digest=file_hash(src)
                    with self.db.lock: exists=self.db.conn.execute('SELECT id, languages FROM fonts WHERE sha256=?',(digest,)).fetchone()
                    if exists:
                        # Backfill language coverage for records created by an older version.
                        if not exists['languages'] or exists['languages'] == '[]':
                            try:
                                _, _, _, languages = font_metadata(src)
                                with self.db.lock, self.db.conn:
                                    self.db.conn.execute('UPDATE fonts SET languages=? WHERE id=?',(json.dumps(languages),exists['id']))
                            except Exception: pass
                        duplicates+=1; progress(i,max(total,1),f'קובץ {i:,} מתוך {total:,} — כפילות'); continue
                    family,subfamily,weight,languages=font_metadata(src)
                    dest_name=f'{safe_name(family)} - {safe_name(subfamily)}-{digest[:10]}{src.suffix.lower()}'
                    dest=LIBRARY_DIR/dest_name
                    # Don't copy a file into itself; external files are copied, source stays unchanged.
                    try: is_managed = src.resolve().parent == LIBRARY_DIR.resolve()
                    except OSError: is_managed = False
                    if is_managed:
                        # Normalize names in our own library only; never rename external source files.
                        if src.resolve()!=dest.resolve() and not dest.exists():
                            try: src.rename(dest)
                            except OSError: dest=src
                        elif dest.exists() and src.resolve()!=dest.resolve():
                            dest=src
                    elif src.resolve()!=dest.resolve():
                        if dest.exists(): dest=LIBRARY_DIR/f'{safe_name(family)} - {safe_name(subfamily)}-{digest[:16]}{src.suffix.lower()}'
                        if not dest.exists(): shutil.copy2(src,dest)
                    else: dest=src
                    with self.db.lock, self.db.conn:
                        self.db.conn.execute('INSERT OR IGNORE INTO fonts(family,subfamily,weight,path,source_path,size,sha256,added_at,languages) VALUES(?,?,?,?,?,?,?,?,?)',
                            (family,subfamily,weight,str(dest),str(src),size,digest,time.time(),json.dumps(languages)))
                    imported+=1
                except Exception as e:
                    skipped+=1
                if i%10==0 or i==total: progress(i,max(total,1),f'נבדקו {i:,} מתוך {total:,}')
            return {'found':total,'imported':imported,'duplicates':duplicates,'skipped':skipped,'cancelled':self.cancel_event.is_set(),'initial':initial}
        worker=Worker(work); worker.signals.progress.connect(self.on_progress); worker.signals.done.connect(self.scan_done); worker.signals.error.connect(self.worker_error); self.pool.start(worker)
    def cancel_scan(self):
        self.cancel_event.set(); self.cancel_btn.setEnabled(False); self.statusBar().showMessage('הביטול יתבצע בצורה בטוחה לאחר סיום בדיקת הקובץ הנוכחי…')
    def on_progress(self, current, total, message):
        self.progress.setRange(0,max(1,total)); self.progress.setValue(min(current,total)); self.statusBar().showMessage(message)
    def scan_done(self, result):
        self.set_busy(False); self.refresh()
        if result.get('initial'):
            self.settings['last_scan_done']=True; save_settings(self.settings)
        msg=(f"נמצאו: {result['found']:,}\nנוספו: {result['imported']:,}\nכפילויות שדולגו: {result['duplicates']:,}\nקבצים שלא ניתן היה לייבא: {result['skipped']:,}")
        if result.get('cancelled'): msg+='\nהפעולה בוטלה.'
        QMessageBox.information(self,'סיכום סריקה',msg); self.statusBar().showMessage('הסריקה הסתיימה')
    def worker_error(self, err): self.set_busy(False); QMessageBox.critical(self,'שגיאה בפעולת רקע',err[-2500:])
    def selected_family(self):
        idx=self.list.currentIndex(); return idx.data(FontListModel.FamilyRole) if idx.isValid() else None
    def try_selected(self):
        item=self.selected_family()
        if item: self.try_family(item['family'])
    def try_family(self, family):
        fonts=self.db.family_fonts(family)
        dlg=TryDialog(family,fonts,self); dlg.exec()
    def context_menu(self, pos):
        idx=self.list.indexAt(pos); item=idx.data(FontListModel.FamilyRole) if idx.isValid() else None
        if not item: return
        menu=QMenu(self); act_try=menu.addAction('התנסות בגופן'); act_fav=menu.addAction('הוסף / הסר מועדף'); act_install=menu.addAction('התקן את כל משקלי המשפחה…'); act_details=menu.addAction('פרטי משפחה')
        chosen=menu.exec(self.list.mapToGlobal(pos))
        if chosen==act_try: self.try_selected()
        elif chosen==act_fav:
            self.db.toggle_favorite(item['family']); self.refresh()
        elif chosen==act_install: self.install_family(item['family'])
        elif chosen==act_details:
            fs=self.db.family_fonts(item['family']); QMessageBox.information(self,'פרטי משפחה',item['family']+'\n\n'+'\n'.join(f"{f['subfamily']} — {f['path']}" for f in fs))
    def install_family(self, family):
        fonts=self.db.family_fonts(family); existing=[f for f in fonts if not Path(f['path']).exists()]
        fonts=[f for f in fonts if Path(f['path']).exists()]
        if not fonts: QMessageBox.warning(self,'אין קבצים זמינים','לא נמצאו קובצי גופן תקינים למשפחה.'); return
        preview='\n'.join(f"• {f['subfamily']} — {'מותקן/עשוי להיות מותקן' if f['installed'] else 'יועתק להתקנה'}" for f in fonts)
        if QMessageBox.question(self,'אישור התקנה',f"להתקין את כל {len(fonts)} המשקלים של {family}?\n\n{preview}\n\nלא ניתן להבטיח שכל יישום יעדכן את רשימת הגופנים מיד.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes: return
        if os.name!='nt': QMessageBox.warning(self,'Windows בלבד','התקנת גופנים זמינה ב-Windows בלבד.'); return
        self.db.backup()
        try:
            import winreg
            target=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'Microsoft' / 'Windows' / 'Fonts'; target.mkdir(parents=True,exist_ok=True)
            keypath=r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,keypath) as key:
                for f in fonts:
                    src=Path(f['path']); dest=target/src.name
                    if not dest.exists(): shutil.copy2(src,dest)
                    label=f"{family} ({f['subfamily']})"
                    winreg.SetValueEx(key,label,0,winreg.REG_SZ,str(dest))
                    with self.db.lock,self.db.conn: self.db.conn.execute('UPDATE fonts SET installed=1 WHERE id=?',(f['id'],))
            QMessageBox.information(self,'ההתקנה הושלמה',f'הועברו לרישום המשתמש {len(fonts)} קובצי גופן. ייתכן שיהיה צורך להפעיל מחדש יישומים.'); self.refresh()
        except Exception as e: QMessageBox.critical(self,'ההתקנה נכשלה',str(e))
    def compare_selected(self):
        indexes=self.list.selectionModel().selectedIndexes()
        if len(indexes)<2: QMessageBox.information(self,'השוואת גופנים','בחר לפחות שתי משפחות (Ctrl או Shift לבחירה מרובה).'); return
        dialog=QDialog(self); dialog.setWindowTitle('השוואת גופנים'); dialog.resize(900,500); dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft); lay=QVBoxLayout(dialog)
        text=QLineEdit(SAMPLE_SENTENCE); text.setPlaceholderText('הקלד טקסט להשוואה'); lay.addWidget(text)
        size=QSpinBox(); size.setRange(8,100); size.setValue(self.settings.get('preview_size',28)); lay.addWidget(size)
        splitter=QSplitter(Qt.Orientation.Horizontal); lay.addWidget(splitter,1)
        labels=[]
        for ix in indexes[:8]:
            item=ix.data(FontListModel.FamilyRole); label=QLabel(item['family']+'\n\n'+text.text()); label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setWordWrap(True); path=item.get('path',''); fid=QFontDatabase.addApplicationFont(path) if path and Path(path).is_file() else -1; fams=QFontDatabase.applicationFontFamilies(fid) if fid>=0 else []; label.setFont(QFont(fams[0] if fams else item['family'],size.value())); splitter.addWidget(label); labels.append((label,item['family'],path))
        def update():
            for label,family,path in labels:
                label.setText(family+'\n\n'+text.text()); fid=QFontDatabase.addApplicationFont(path) if path and Path(path).is_file() else -1; fams=QFontDatabase.applicationFontFamilies(fid) if fid>=0 else []; label.setFont(QFont(fams[0] if fams else family,size.value()))
        text.textChanged.connect(update); size.valueChanged.connect(update); dialog.exec()
    def closeEvent(self,event):
        try: save_settings(self.settings); self.db.close()
        except Exception: pass
        event.accept()

from PySide6.QtCore import QTimer

def main():
    app=QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    icon_base = Path(getattr(sys, '_MEIPASS', ROOT))
    icon_path = icon_base / 'assets' / 'fontstudio.ico'
    if icon_path.exists(): app.setWindowIcon(QIcon(str(icon_path)))
    # Show an immediate lightweight startup window before database and UI initialization.
    splash = QWidget(); splash.setWindowTitle(APP_NAME); splash.setWindowIcon(QIcon(str(icon_path)))
    splash.setFixedSize(360, 170); splash.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    layout = QVBoxLayout(splash)
    title = QLabel('Font Studio'); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet('font-size:24px;font-weight:700;padding:8px;'); layout.addWidget(title)
    spinner = QLabel('◌  טוען את ספריית הגופנים…'); spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    spinner.setStyleSheet('font-size:15px;padding:8px;'); layout.addWidget(spinner)
    splash.show(); app.processEvents()
    win = FontStudio(); win.show(); splash.close()
    sys.exit(app.exec())

if __name__=='__main__': main()
