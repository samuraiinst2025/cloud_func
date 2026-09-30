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

# 表示上のページ端からの余白（pt）
MARGIN_RIGHT = 20
MARGIN_TOP = 20

# 文字が長い場合に確保する最低左余白
MIN_X = 20

# この main.py が存在するディレクトリ
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

# GitHubリポジトリに配置した日本語フォント
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
    Copilot StudioやPower Platformからの呼び出しを許可する。

    検証中はAccess-Control-Allow-Originを「*」にしている。
    本番環境では必要なオリジンに制限することを推奨。
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
        "Content-Type, "
        "Authorization, "
        "Accept, "
        "Origin"
    )

    response.headers[
        "Access-Control-Expose-Headers"
    ] = "Content-Type"

    return response


# ============================================================
# JSONレスポンス
# ============================================================

def json_response(payload, status=200):
    """
    JSONレスポンスを返す。
    """

    response = jsonify(
        payload
    )

    response.status_code = status

    return add_cors_headers(
        response
    )


def error_response(message, status=400):
    """
    エラー内容をJSON形式で返す。
    """

    return json_response(
        {
            "success": False,
            "error": message
        },
        status
    )


# ============================================================
# Base64処理
# ============================================================

def normalize_base64(value):
    """
    Base64文字列を正規化する。

    次の形式に対応する。

    1. 通常のBase64
       JVBERi0xLjQK...

    2. Data URL
       data:application/pdf;base64,JVBERi0xLjQK...
    """

    if not isinstance(value, str):
        raise ValueError(
            "fileContentは文字列で指定してください。"
        )

    value = value.strip()

    if not value:
        raise ValueError(
            "fileContentが空です。"
        )

    # Data URLの場合、カンマより後ろだけを使用する
    if value.lower().startswith("data:"):
        if "," not in value:
            raise ValueError(
                "fileContentのData URL形式が正しくありません。"
            )

        value = value.split(
            ",",
            1
        )[1]

    # Base64内に含まれる改行、空白、タブを除去する
    return "".join(
        value.split()
    )


def decode_pdf_base64(value):
    """
    Base64文字列をPDFのバイト列へ変換する。
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
            "fileContentをBase64として"
            "デコードできませんでした。"
        ) from error

    if not pdf_bytes:
        raise ValueError(
            "デコード後のPDFデータが空です。"
        )

    # 一般的なPDFシグネチャ
    if not pdf_bytes.startswith(
        b"%PDF-"
    ):
        raise ValueError(
            "fileContentはPDFデータではありません。"
        )

    return pdf_bytes


def encode_pdf_base64(pdf_bytes):
    """
    PDFのバイト列をBase64文字列へ変換する。
    """

    return base64.b64encode(
        pdf_bytes
    ).decode(
        "ascii"
    )


# ============================================================
# ファイル名処理
# ============================================================

def sanitize_pdf_filename(file_name):
    """
    入力ファイル名を安全なPDFファイル名に整形する。
    """

    if not isinstance(file_name, str):
        return "input.pdf"

    file_name = os.path.basename(
        file_name.strip()
    )

    if not file_name:
        return "input.pdf"

    if not file_name.lower().endswith(
        ".pdf"
    ):
        file_name = (
            file_name
            + ".pdf"
        )

    return file_name


def create_output_filename(input_file_name):
    """
    編集済みPDFのファイル名を生成する。
    """

    input_file_name = sanitize_pdf_filename(
        input_file_name
    )

    base_name, _ = os.path.splitext(
        input_file_name
    )

    return f"edited_{base_name}.pdf"


# ============================================================
# PDF検証
# ============================================================

def validate_pdf_file(pdf_path):
    """
    PDFとして開けるか、ページが存在するか確認する。
    """

    document = None

    try:
        document = fitz.open(
            pdf_path
        )

        if document.page_count == 0:
            raise ValueError(
                "PDFにページがありません。"
            )

        # 破損PDFなどを検出するために1ページ目を読み込む
        document.load_page(
            0
        )

    except ValueError:
        raise

    except Exception as error:
        raise ValueError(
            "アップロードされたファイルを"
            "PDFとして読み込めませんでした。"
        ) from error

    finally:
        if document is not None:
            document.close()


# ============================================================
# 文字描画位置計算
# ============================================================

def calculate_text_position(
    page,
    text_width,
    font_size,
    margin_right,
    margin_top
):
    """
    表示上の右上に文字を追加するための座標を計算する。

    page.rectはページの回転を反映した表示上のサイズとなる。
    """

    page_width = float(
        page.rect.width
    )

    page_height = float(
        page.rect.height
    )

    # 表示上の右端から文字幅と余白を引く
    visual_x = (
        page_width
        - margin_right
        - text_width
    )

    # 文字列が長い場合でも完全にページ外へ出ないようにする
    visual_x = max(
        MIN_X,
        visual_x
    )

    # insert_textのY座標は文字の上端ではなくベースライン
    visual_y = (
        margin_top
        + font_size
    )

    # ページの高さを超えないように保護する
    visual_y = min(
        visual_y,
        page_height - margin_top
    )

    return fitz.Point(
        visual_x,
        visual_y
    )


# ============================================================
# PDF編集
# ============================================================

def add_text_to_first_page_top_right(
    input_pdf,
    output_pdf,
    text,
    font_size=FONT_SIZE,
    margin_right=MARGIN_RIGHT,
    margin_top=MARGIN_TOP,
):
    """
    PDFの1ページ目右上に指定文字列を追加する。

    ・2ページ目以降は変更しない
    ・日本語フォントを使用する
    ・0度、90度、180度、270度のページ回転に対応する
    """

    if not isinstance(text, str):
        raise ValueError(
            "追加文字列は文字列で指定してください。"
        )

    text = text.strip()

    if not text:
        raise ValueError(
            "追加する文字列が指定されていません。"
        )

    if not os.path.exists(
        FONT_PATH
    ):
        raise FileNotFoundError(
            "日本語フォントが見つかりません: "
            f"{FONT_PATH}"
        )

    document = fitz.open(
        input_pdf
    )

    try:
        if document.page_count == 0:
            raise ValueError(
                "PDFにページがありません。"
            )

        # 1ページ目だけを対象にする
        page = document.load_page(
            0
        )

        font_alias = "JPFont"

        # ページに日本語フォントを登録する
        page.insert_font(
            fontname=font_alias,
            fontfile=FONT_PATH
        )

        # 文字幅計算用フォント
        font = fitz.Font(
            fontfile=FONT_PATH
        )

        text_width = font.text_length(
            text,
            fontsize=font_size
        )

        rotation = (
            page.rotation % 360
        )

        visual_point = calculate_text_position(
            page=page,
            text_width=text_width,
            font_size=font_size,
            margin_right=margin_right,
            margin_top=margin_top
        )

        print(
            "PDF DRAW DEBUG:",
            {
                "text": repr(text),
                "font_size": font_size,
                "text_width": text_width,
                "page_width": page.rect.width,
                "page_height": page.rect.height,
                "page_rotation": rotation,
                "visual_x": visual_point.x,
                "visual_y": visual_point.y
            }
        )

        # ----------------------------------------------------
        # 回転なしPDF
        # ----------------------------------------------------

        if rotation == 0:
            insert_point = visual_point
            text_rotation = 0

        # ----------------------------------------------------
        # 回転ありPDF
        # ----------------------------------------------------

        else:
            # 表示上の座標をPDF内部の座標へ戻す
            insert_point = (
                visual_point
                * page.derotation_matrix
            )

            # ページ回転を打ち消して表示上は横書きにする
            text_rotation = (
                360 - rotation
            ) % 360

        print(
            "PDF INSERT DEBUG:",
            {
                "insert_x": insert_point.x,
                "insert_y": insert_point.y,
                "text_rotation": text_rotation
            }
        )

        # 文字を追加する
        page.insert_text(
            insert_point,
            text,
            fontsize=font_size,
            fontname=font_alias,
            fontfile=FONT_PATH,
            color=(0, 0, 0),
            rotate=text_rotation,
            overlay=True
        )

        # garbage=4で未使用オブジェクトを整理する
        # deflate=Trueで可能な範囲で圧縮する
        document.save(
            output_pdf,
            garbage=4,
            deflate=True
        )

    finally:
        document.close()


# ============================================================
# HTTPエントリポイント
# ============================================================

@functions_framework.http
def edit_pdf(request):
    """
    Cloud Run / Functions Framework HTTP Endpoint

    GET:
        稼働状態確認

    POST Content-Type:
        application/json

    Request:
        {
            "fileContent": "Base64形式のPDF",
            "fileName": "sample.pdf",
            "text": "承認済み"
        }

    Response:
        {
            "success": true,
            "fileContent": "Base64形式の編集済みPDF",
            "fileName": "edited_sample.pdf",
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
    # 稼働確認
    # ========================================================

    if request.method == "GET":
        return json_response(
            {
                "success": True,
                "status": "running",
                "message": "PDF Editor API is running.",
                "fontExists": os.path.exists(
                    FONT_PATH
                )
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
    # Content-Type確認
    # ========================================================

    if not request.is_json:
        return error_response(
            "Content-Typeにはapplication/jsonを"
            "指定してください。",
            415
        )

    # ========================================================
    # JSON取得
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

    print(
        "REQUEST JSON KEYS:",
        list(
            request_data.keys()
        )
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

    print(
        "REQUEST VALUES:",
        {
            "fileName": repr(file_name),
            "text": repr(text),
            "fileContentExists": bool(file_content),
            "fileContentLength": (
                len(file_content)
                if isinstance(file_content, str)
                else None
            )
        }
    )

    # ========================================================
    # 必須項目確認
    # ========================================================

    if not file_content:
        return error_response(
            "fileContentが指定されていません。",
            400
        )

    if not isinstance(text, str):
        return error_response(
            "textが指定されていません。",
            400
        )

    text = text.strip()

    if not text:
        return error_response(
            "textが空です。",
            400
        )

    file_name = sanitize_pdf_filename(
        file_name
    )

    output_file_name = create_output_filename(
        file_name
    )

    # ========================================================
    # 一時ファイル
    # ========================================================

    input_path = None
    output_path = None

    try:
        # ----------------------------------------------------
        # Base64をPDFバイト列へ変換
        # ----------------------------------------------------

        input_pdf_bytes = decode_pdf_base64(
            file_content
        )

        print(
            "INPUT PDF SIZE:",
            len(input_pdf_bytes)
        )

        # ----------------------------------------------------
        # 入力PDFの一時ファイル作成
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as temporary_input:

            input_path = temporary_input.name

            temporary_input.write(
                input_pdf_bytes
            )

        # ----------------------------------------------------
        # 入力PDF検証
        # ----------------------------------------------------

        validate_pdf_file(
            input_path
        )

        # ----------------------------------------------------
        # 出力PDFの一時ファイル作成
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as temporary_output:

            output_path = temporary_output.name

        # ====================================================
        # PDF編集
        # ====================================================

        add_text_to_first_page_top_right(
            input_pdf=input_path,
            output_pdf=output_path,
            text=text,
            font_size=FONT_SIZE,
            margin_right=MARGIN_RIGHT,
            margin_top=MARGIN_TOP
        )

        # ====================================================
        # 出力PDF読み込み
        # ====================================================

        with open(
            output_path,
            "rb"
        ) as output_file:

            output_pdf_bytes = output_file.read()

        if not output_pdf_bytes:
            raise RuntimeError(
                "編集済みPDFが生成されませんでした。"
            )

        print(
            "OUTPUT PDF SIZE:",
            len(output_pdf_bytes)
        )

        # 開けるPDFになっているか再確認する
        validate_pdf_file(
            output_path
        )

        # ====================================================
        # 出力PDFをBase64へ変換
        # ====================================================

        output_base64 = encode_pdf_base64(
            output_pdf_bytes
        )

        # ====================================================
        # 正常レスポンス
        # ====================================================

        return json_response(
            {
                "success": True,
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
            "PDF INPUT ERROR:",
            repr(error)
        )

        return error_response(
            str(error),
            400
        )

    # ========================================================
    # フォントエラー
    # ========================================================

    except FileNotFoundError as error:
        print(
            "FONT ERROR:",
            repr(error)
        )

        return error_response(
            str(error),
            500
        )

    # ========================================================
    # その他のエラー
    # ========================================================

    except Exception as error:
        print(
            "PDF EDIT ERROR:",
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

                except Exception as cleanup_error:
                    print(
                        "TEMP FILE CLEANUP ERROR:",
                        repr(cleanup_error)
                    )
