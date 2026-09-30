import os
import base64
import binascii
import tempfile

import fitz  # PyMuPDF
import functions_framework
from flask import Response, jsonify


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
    "NotoSansJP-VariableFont_wght.ttf"
)


# ============================================================
# CORS
# ============================================================

def add_cors_headers(response):
    """
    Power Apps / Copilot Studioなどからのアクセスを許可する。

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
    ] = "Content-Type"

    return response


# ============================================================
# 共通レスポンス
# ============================================================

def json_response(
    payload,
    status=200
):
    response = jsonify(
        payload
    )

    response.status_code = status

    return add_cors_headers(
        response
    )


def error_response(
    message,
    status
):
    return json_response(
        {
            "error": message
        },
        status
    )


# ============================================================
# Base64処理
# ============================================================

def normalize_base64(value):
    """
    通常のBase64とData URL形式の両方を受け付ける。

    通常:
        JVBERi0xLjQK...

    Data URL:
        data:application/pdf;base64,JVBERi0xLjQK...
    """

    if not isinstance(value, str):
        raise ValueError(
            "fileContent は文字列で指定してください。"
        )

    value = value.strip()

    if not value:
        raise ValueError(
            "fileContent が空です。"
        )

    if value.startswith("data:"):
        if "," not in value:
            raise ValueError(
                "fileContent のData URL形式が正しくありません。"
            )

        value = value.split(
            ",",
            1
        )[1]

    # 改行や空白を除去
    return "".join(
        value.split()
    )


def decode_pdf_base64(value):
    """
    Base64文字列をPDFバイト列へ変換する。
    """

    normalized_value = normalize_base64(
        value
    )

    try:
        pdf_bytes = base64.b64decode(
            normalized_value,
            validate=True
        )
    except (
        binascii.Error,
        ValueError
    ) as error:
        raise ValueError(
            "fileContent をBase64として"
            "デコードできませんでした。"
        ) from error

    if not pdf_bytes:
        raise ValueError(
            "デコード後のPDFデータが空です。"
        )

    # PDFの一般的なシグネチャを確認
    if not pdf_bytes.startswith(
        b"%PDF-"
    ):
        raise ValueError(
            "fileContent はPDFデータではありません。"
        )

    return pdf_bytes


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

    if not os.path.exists(
        FONT_PATH
    ):
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

        # insert_text() のY座標は文字のベースライン位置
        visual_y = (
            margin_top
            + font_size
        )

        visual_point = fitz.Point(
            visual_x,
            visual_y
        )

        # ----------------------------------------------------
        # 見た目座標からPDF内部座標へ変換
        # ----------------------------------------------------

        pdf_point = (
            visual_point
            * page.derotation_matrix
        )

        # ----------------------------------------------------
        # ページ回転を打ち消す
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

    Content-Type:
        application/json

    Request:
        {
            "fileContent": "Base64形式のPDF",
            "fileName": "input.pdf",
            "text": "追加する文字列"
        }

    Response:
        {
            "fileContent": "Base64形式の編集済みPDF",
            "fileName": "edited_input.pdf",
            "contentType": "application/pdf"
        }
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
        return json_response(
            {
                "status": "ok",
                "message": "PDF Editor API is running."
            },
            200
        )

    # ========================================================
    # POST以外は禁止
    # ========================================================

    if request.method != "POST":
        return error_response(
            "POSTメソッドを使用してください。",
            405
        )

    # ========================================================
    # Content-Typeチェック
    # ========================================================

    if not request.is_json:
        return error_response(
            "Content-Type は application/json "
            "を指定してください。",
            415
        )

    # ========================================================
    # JSONチェック
    # ========================================================

    request_data = request.get_json(
        silent=True
    )

    if not isinstance(
        request_data,
        dict
    ):
        return error_response(
            "JSON本文を読み込めませんでした。",
            400
        )

    file_content = request_data.get(
        "fileContent"
    )

    file_name = request_data.get(
        "fileName",
        "input.pdf"
    )

    text = request_data.get(
        "text"
    )

    # ========================================================
    # 必須項目チェック
    # ========================================================

    if not file_content:
        return error_response(
            "fileContent が指定されていません。",
            400
        )

    if not text or not isinstance(
        text,
        str
    ):
        return error_response(
            "text が指定されていません。",
            400
        )

    text = text.strip()

    if not text:
        return error_response(
            "text が空です。",
            400
        )

    if not isinstance(
        file_name,
        str
    ):
        file_name = "input.pdf"

    # パス情報を除去
    file_name = os.path.basename(
        file_name.strip()
    )

    if not file_name:
        file_name = "input.pdf"

    if not file_name.lower().endswith(
        ".pdf"
    ):
        file_name = (
            file_name
            + ".pdf"
        )

    # ========================================================
    # 一時ファイル
    # ========================================================

    input_path = None
    output_path = None

    try:
        # ----------------------------------------------------
        # Base64からPDFへ変換
        # ----------------------------------------------------

        pdf_bytes = decode_pdf_base64(
            file_content
        )

        # ----------------------------------------------------
        # 入力PDFを書き込む
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_input:
            input_path = tmp_input.name

            tmp_input.write(
                pdf_bytes
            )

        # ----------------------------------------------------
        # PDFとして開けるか確認
        # ----------------------------------------------------

        try:
            test_doc = fitz.open(
                input_path
            )

            if test_doc.page_count == 0:
                test_doc.close()

                return error_response(
                    "PDFにページがありません。",
                    400
                )

            test_doc.close()

        except Exception:
            return error_response(
                "fileContentをPDFとして"
                "読み込めませんでした。",
                400
            )

        # ----------------------------------------------------
        # 出力PDF
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as tmp_output:
            output_path = tmp_output.name

        # ====================================================
        # PDF編集処理
        # ====================================================

        add_text_to_first_page_top_right(
            input_pdf=input_path,
            output_pdf=output_path,
            text=text
        )

        # ====================================================
        # 編集済みPDFを読み込む
        # ====================================================

        with open(
            output_path,
            "rb"
        ) as output_file:
            output_pdf_bytes = (
                output_file.read()
            )

        # ====================================================
        # Base64へ変換
        # ====================================================

        output_base64 = base64.b64encode(
            output_pdf_bytes
        ).decode(
            "ascii"
        )

        original_name_without_extension = (
            os.path.splitext(
                file_name
            )[0]
        )

        output_file_name = (
            f"edited_{original_name_without_extension}.pdf"
        )

        # ====================================================
        # JSONレスポンス
        # ====================================================

        return json_response(
            {
                "fileContent": output_base64,
                "fileName": output_file_name,
                "contentType": "application/pdf"
            },
            200
        )

    # ========================================================
    # 入力エラー
    # ========================================================

    except ValueError as error:
        print(
            "PDF Input Error:",
            repr(error)
        )

        return error_response(
            str(error),
            400
        )

    # ========================================================
    # サーバーエラー
    # ========================================================

    except Exception as error:
        print(
            "PDF Edit Error:",
            repr(error)
        )

        return error_response(
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
                and os.path.exists(path)
            ):
                try:
                    os.remove(
                        path
                    )
                except Exception:
                    pass
