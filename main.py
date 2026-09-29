import os
import tempfile

import fitz  # PyMuPDF
import functions_framework
from flask import Response


# ============================================================
# 設定
# ============================================================

FONT_SIZE = 12

# 見た目上のページ端からの余白（pt）
MARGIN_RIGHT = 20
MARGIN_TOP = 20

# この main.py が存在するディレクトリ
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

# GitHubリポジトリに同梱した日本語フォント
FONT_PATH = os.path.join(
    BASE_DIR,
    "fonts",
    "NotoSansJP-Regular.ttf"
)


# ============================================================
# CORS
# ============================================================

def add_cors_headers(response):
    """
    Power Apps / Copilot Studio などからの
    ブラウザ経由アクセスを許可する。

    PoC中は * で許可。
    本番環境では必要なOriginだけに制限推奨。
    """

    response.headers[
        "Access-Control-Allow-Origin"
    ] = "*"

    response.headers[
        "Access-Control-Allow-Methods"
    ] = "POST, GET, OPTIONS"

    response.headers[
        "Access-Control-Allow-Headers"
    ] = (
        "Content-Type, Authorization, "
        "Accept, Origin"
    )

    response.headers[
        "Access-Control-Expose-Headers"
    ] = "Content-Disposition"

    return response


# ============================================================
# 共通レスポンス
# ============================================================

def text_response(
    message,
    status=200
):
    response = Response(
        message,
        status=status,
        mimetype="text/plain"
    )

    return add_cors_headers(
        response
    )


# ============================================================
# PDF編集
# ============================================================

def add_text_to_first_page_top_right(
    input_pdf: str,
    output_pdf: str,
    text: str,
    font_size: int = FONT_SIZE,
    margin_right: float = MARGIN_RIGHT,
    margin_top: float = MARGIN_TOP,
):
    """
    PDFの1ページ目だけを編集する。

    ユーザーから指定された文字列を、
    PDFを実際に表示したときの
    「右上」に横書きで追加する。

    90 / 180 / 270度などの
    ページ回転情報にも対応する。

    2ページ目以降は変更しない。
    """

    # --------------------------------------------------------
    # 入力チェック
    # --------------------------------------------------------

    if not text:
        raise ValueError(
            "追加する文言が指定されていません。"
        )

    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(
            "日本語フォントが見つかりません: "
            f"{FONT_PATH}"
        )

    # --------------------------------------------------------
    # PDFを開く
    # --------------------------------------------------------

    doc = fitz.open(
        input_pdf
    )

    try:

        if doc.page_count == 0:
            raise ValueError(
                "PDFにページがありません。"
            )

        # ====================================================
        # 1ページ目だけ取得
        # ====================================================

        page = doc[0]

        # ----------------------------------------------------
        # 日本語フォントを登録
        # ----------------------------------------------------

        font_alias = "JPFont"

        page.insert_font(
            fontname=font_alias,
            fontfile=FONT_PATH
        )

        # 文字幅計算用フォント
        font = fitz.Font(
            fontfile=FONT_PATH
        )

        # ----------------------------------------------------
        # 文字幅を計算
        # ----------------------------------------------------

        text_width = font.text_length(
            text,
            fontsize=font_size
        )

        # ----------------------------------------------------
        # ページ回転情報
        # ----------------------------------------------------

        rotation = (
            page.rotation % 360
        )

        # ----------------------------------------------------
        # 見た目上の右上座標
        # ----------------------------------------------------

        visual_x = (
            page.rect.width
            - margin_right
            - text_width
        )

        # insert_text() のY座標は
        # 文字のベースライン位置
        visual_y = (
            margin_top
            + font_size
        )

        visual_point = fitz.Point(
            visual_x,
            visual_y
        )

        # ----------------------------------------------------
        # 見た目座標 → PDF内部座標
        # ----------------------------------------------------

        pdf_point = (
            visual_point
            * page.derotation_matrix
        )

        # ----------------------------------------------------
        # ページ回転を打ち消す
        #
        # PDFを実際に表示したときに
        # 横書きになるようにする
        # ----------------------------------------------------

        text_rotation = (
            360 - rotation
        ) % 360

        # ----------------------------------------------------
        # 文字追加
        # ----------------------------------------------------

        page.insert_text(
            pdf_point,
            text,
            fontsize=font_size,
            fontname=font_alias,
            color=(0, 0, 0),
            rotate=text_rotation
        )

        # ----------------------------------------------------
        # 保存
        #
        # 高速化のため、
        # 再圧縮や不要な最適化は行わない
        # ----------------------------------------------------

        doc.save(
            output_pdf
        )

    finally:

        doc.close()


# ============================================================
# HTTPエントリポイント
# ============================================================

@functions_framework.http
def edit_pdf(request):
    """
    Cloud Run / Functions Framework HTTP Endpoint

    想定URL:
        POST /edit-pdf

    Content-Type:
        multipart/form-data

    Parameters:
        file : PDF
        text : 追加する文字列

    Response:
        application/pdf
    """

    # ========================================================
    # CORS Preflight
    # ========================================================

    if request.method == "OPTIONS":

        response = Response(
            status=204
        )

        return add_cors_headers(
            response
        )

    # ========================================================
    # 動作確認用GET
    # ========================================================

    if request.method == "GET":

        return text_response(
            "PDF Editor API is running.",
            200
        )

    # ========================================================
    # POST以外は禁止
    # ========================================================

    if request.method != "POST":

        return text_response(
            "POSTメソッドを使用してください。",
            405
        )

    # ========================================================
    # PDFチェック
    # ========================================================

    if "file" not in request.files:

        return text_response(
            "PDFファイルが指定されていません。",
            400
        )

    uploaded_file = (
        request.files["file"]
    )

    if not uploaded_file.filename:

        return text_response(
            "PDFファイル名が指定されていません。",
            400
        )

    # ========================================================
    # textチェック
    # ========================================================

    text = request.form.get(
        "text"
    )

    if not text:

        return text_response(
            "text が指定されていません。",
            400
        )

    # ========================================================
    # 一時ファイル
    # ========================================================

    input_path = None
    output_path = None

    try:

        # ----------------------------------------------------
        # 入力PDF
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_input:

            input_path = (
                tmp_input.name
            )

        uploaded_file.save(
            input_path
        )

        # ----------------------------------------------------
        # PDFとして開けるか簡易確認
        # ----------------------------------------------------

        try:

            test_doc = fitz.open(
                input_path
            )

            test_doc.close()

        except Exception:

            return text_response(
                "アップロードされたファイルを"
                "PDFとして読み込めませんでした。",
                400
            )

        # ----------------------------------------------------
        # 出力PDF
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_output:

            output_path = (
                tmp_output.name
            )

        # ====================================================
        # PDF編集処理
        # ====================================================

        add_text_to_first_page_top_right(
            input_pdf=input_path,
            output_pdf=output_path,
            text=text
        )

        # ====================================================
        # 編集済PDFを読み込む
        # ====================================================

        with open(
            output_path,
            "rb"
        ) as file:

            pdf_bytes = (
                file.read()
            )

        # ====================================================
        # PDFレスポンス
        # ====================================================

        response = Response(
            pdf_bytes,
            status=200,
            mimetype="application/pdf"
        )

        response.headers[
            "Content-Disposition"
        ] = (
            'attachment; '
            'filename="edited.pdf"'
        )

        return add_cors_headers(
            response
        )

    # ========================================================
    # エラー
    # ========================================================

    except Exception as error:

        print(
            "PDF Edit Error:",
            repr(error)
        )

        return text_response(
            "PDF編集に失敗しました: "
            f"{str(error)}",
            500
        )

    # ========================================================
    # 一時ファイル削除
    # ========================================================

    finally:

        for path in [
            input_path,
            output_path
        ]:

            if (
                path
                and
                os.path.exists(path)
            ):

                try:

                    os.remove(
                        path
                    )

                except Exception:

                    pass
