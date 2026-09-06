CARD_STYLE = """
    QFrame#card {
        background: #ffffff;
        border-radius: 12px;
        border: 1px solid #e5e5ea;
    }
"""

HEADER_STYLE = """
    QLabel#header {
        font-size: 28px;
        font-weight: 700;
        color: #1c1c1e;
    }
"""

SUBTITLE_STYLE = """
    QLabel#subtitle {
        font-size: 13px;
        color: #8e8e93;
    }
"""

BUTTON_PRIMARY = """
    QPushButton {
        background: #007aff;
        color: white;
        border: none;
        border-radius: 10px;
        padding: 12px 24px;
        font-size: 15px;
        font-weight: 600;
    }
    QPushButton:hover { background: #0066d6; }
    QPushButton:pressed { background: #0055b3; }
"""

BUTTON_SECONDARY = """
    QPushButton {
        background: #f2f2f7;
        color: #007aff;
        border: none;
        border-radius: 10px;
        padding: 12px 24px;
        font-size: 15px;
        font-weight: 600;
    }
    QPushButton:hover { background: #e5e5ea; }
    QPushButton:pressed { background: #d1d1d6; }
"""

STATUS_ROW = """
    QLabel#status_label {
        font-size: 15px;
        color: #1c1c1e;
    }
    QLabel#status_value {
        font-size: 15px;
        font-weight: 600;
    }
"""

LOG_STYLE = """
    QTextEdit {
        background: #f9f9fb;
        border: 1px solid #e5e5ea;
        border-radius: 8px;
        font-size: 12px;
        color: #3a3a3c;
        padding: 8px;
    }
"""

CALIBRATION_STEP = """
    QLabel#step_title {
        font-size: 16px;
        font-weight: 600;
        color: #1c1c1e;
    }
    QLabel#step_desc {
        font-size: 13px;
        color: #636366;
    }
"""

MAIN_BG = """
    QMainWindow { background: #f2f2f7; }
    QWidget#central { background: #f2f2f7; }
"""
