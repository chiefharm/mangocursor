"""Shared Google Drive folder listing — filenames do not have to contain dates."""

from __future__ import annotations

from app.drive import folder_id_from_value, parse_folder_html

HTML = r"""
<title>выписки - Google Drive</title>
<script>window['_DRIVE_ivd'] = '[[["1HVFywq-wA_TAymo82EzG9-4zfQb7YUrX",["1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"],"\u0412\u044b\u043f\u0438\u0441\u043a\u0430_\u043f\u043e_\u0441\u0447\u0451\u0442\u0443.pdf","application\/pdf",0,null,0,0,0,1787993901621,1787993901621,null,null,868176]]]';</script>
"""


def test_folder_id_from_link() -> None:
    url = "https://drive.google.com/drive/folders/1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"
    assert folder_id_from_value(url) == "1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"
    assert folder_id_from_value("1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj") == "1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"


def test_parse_folder_html_files() -> None:
    files = parse_folder_html(HTML, folder_id="1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj")
    assert len(files) == 1
    assert files[0].id == "1HVFywq-wA_TAymo82EzG9-4zfQb7YUrX"
    assert files[0].name.endswith(".pdf")
    assert files[0].mime == "application/pdf"
