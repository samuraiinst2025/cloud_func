import os
import tempfile

import fitz  # PyMuPDF
import functions_framework
from flask import Response

@functions_framework.http
def edit_pdf(request):

FONT_SIZE = 12
MARGIN_RIGHT = 20
MARGIN_TOP = 20

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FONT_PATH = os.path.join(
    BASE_DIR,
    "fonts",
    "NotoSansJP-Regular.ttf"
)


def add_text_to_first_page_top_right(
    input_pdf: str,
    output_pdf: str,
    text: str,
    font_size: int = FONT_SIZE,
    margin_right: float = MARGIN_RIGHT,
    margin_top: float = MARGIN_TOP,
):
    if not text:
        raise ValueError("追加する文言が指定されていません。")

    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(
            f"日本語フォントが見つかりません: {FONT_PATH}"
        )

    doc = fitz.open(input_pdf)

    try:
        if doc.page_count == 0:
            raise ValueError("PDFにページがありません。")

        # 1ページ目のみ
        page = doc[0]

        font_alias = "JPFont"

        # フォントをPDFへ登録
        page.insert_font(
            fontname=font_alias,
            fontfile=FONT_PATH
        )

        # 文字幅計算用
        font = fitz.Font(
            fontfile=FONT_PATH
        )

        text_width = font.text_length(
            text,
            fontsize=font_size
        )

        rotation = page.rotation % 360

        # 見た目上の右上
        visual_x = (
            page.rect.width
            - margin_right
            - text_width
        )

        visual_y = (
            margin_top
            + font_size
        )

        visual_point = fitz.Point(
            visual_x,
            visual_y
        )

        # 見た目座標 → PDF内部座標
        pdf_point = (
            visual_point
            * page.derotation_matrix
        )

        # ページ回転を打ち消す
        text_rotation = (
            360 - rotation
        ) % 360

        page.insert_text(
            pdf_point,
            text,
            fontsize=font_size,
            fontname=font_alias,
            color=(0, 0, 0),
            rotate=text_rotation
        )

        # 不要な最適化・再圧縮は行わない
        doc.save(output_pdf)

    finally:
        doc.close()


@functions_framework.http
def edit_pdf(request):
    """
    POST multipart/form-data

    file: PDF
    text: 追加する文言
    """

    if request.method != "POST":
        return (
            "POSTメソッドを使用してください。",
            405
        )

    if "file" not in request.files:
        return (
            "PDFファイルが指定されていません。",
            400
        )

    text = request.form.get("text")

    if not text:
        return (
            "text が指定されていません。",
            400
        )

    uploaded_file = request.files["file"]

    input_path = None
    output_path = None

    try:
        # 入力PDF一時保存
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_input:

            input_path = tmp_input.name

            uploaded_file.save(
                input_path
            )

        # 出力用一時ファイル
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_output:

            output_path = tmp_output.name

        # PDF編集
        add_text_to_first_page_top_right(
            input_pdf=input_path,
            output_pdf=output_path,
            text=text
        )

        # 編集済PDFを返却
        with open(output_path, "rb") as f:
            pdf_bytes = f.read()

        return Response(
            pdf_bytes,
            status=200,
            mimetype="application/pdf",
            headers={
                "Content-Disposition":
                    'attachment; filename="edited.pdf"'
            }
        )

    except Exception as e:
        return (
            f"PDF編集に失敗しました: {str(e)}",
            500
        )

    finally:
        for path in [
            input_path,
            output_path
        ]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
