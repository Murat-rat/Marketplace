"""Application-wide stylesheet."""

PRIMARY = "#2f5bea"
PRIMARY_HOVER = "#2449c4"
DANGER = "#c62828"
TEXT = "#1d2433"
MUTED = "#5b6478"
BORDER = "#d5dae5"
BACKGROUND = "#f3f5fa"
CARD = "#ffffff"

STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QStackedWidget, #Page {{
    background: {BACKGROUND};
}}
#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#Title {{
    font-size: 18pt;
    font-weight: 600;
}}
#Subtitle, #Muted {{
    color: {MUTED};
}}
#FieldLabel {{
    font-weight: 600;
}}
#FieldError {{
    color: {DANGER};
    font-size: 9pt;
}}
#FormError {{
    color: {DANGER};
    background: #fdecec;
    border: 1px solid #f5c2c2;
    border-radius: 6px;
    padding: 8px;
}}
#Notice {{
    color: #1e5631;
    background: #e8f5ec;
    border: 1px solid #b9dfc4;
    border-radius: 6px;
    padding: 8px;
}}
QLineEdit, QPlainTextEdit {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{
    border: 1px solid {DANGER};
}}
QPushButton#Primary {{
    background: {PRIMARY};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 9px 14px;
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background: {PRIMARY_HOVER};
}}
QPushButton#Primary:disabled {{
    background: #9fb2ef;
}}
QPushButton#Secondary {{
    background: transparent;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton#Secondary:hover {{
    background: #eef1f8;
}}
QPushButton#Link {{
    background: transparent;
    border: none;
    color: {PRIMARY};
    padding: 2px;
}}
QPushButton#Link:hover {{
    text-decoration: underline;
}}
QRadioButton {{
    spacing: 6px;
}}
#SectionTitle {{
    font-size: 13pt;
    font-weight: 600;
}}
#ProductCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
#ProductCard:hover {{
    border: 1px solid {PRIMARY};
}}
#CardTitle {{
    font-weight: 600;
}}
#ImagePlaceholder {{
    background: #eef1f7;
    border-radius: 6px;
    color: {MUTED};
}}
#Price {{
    font-size: 12pt;
    font-weight: 700;
}}
#BigPrice {{
    font-size: 20pt;
    font-weight: 700;
}}
#Rating {{
    color: #b7791f;
}}
#Available {{
    color: #1e7a3c;
    font-weight: 600;
}}
#OutOfStock {{
    color: {DANGER};
    font-weight: 600;
}}
QTreeWidget#CategoryTree {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QTreeWidget#CategoryTree::item {{
    padding: 5px 4px;
    border-radius: 4px;
}}
QTreeWidget#CategoryTree::item:selected {{
    background: #e7ecfd;
    color: {PRIMARY};
}}
QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 9px;
    min-width: 150px;
}}
QPushButton#Thumb {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QPushButton#Thumb:hover {{
    border: 1px solid {PRIMARY};
}}
#Badge {{
    background: #e7ecfd;
    color: {PRIMARY};
    border-radius: 10px;
    padding: 3px 10px;
    font-weight: 600;
}}
"""
