import json
import anthropic
import gspread
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from janome.tokenizer import Tokenizer
from collections import Counter
from registry import COL_YEAR, COL_TERM, COL_COURSE, COL_SHEET, parse_registry, sort_terms

# 授業名とスプレッドシートの対応はコードに書かず、
# secrets の REGISTRY_SHEET_URL で指定した科目台帳（Google Sheet）から読み込む

# 列名（ダッシュボード内で使う名前）
COL_TIMESTAMP = "時間"
COL_STUDENT_ID = "学籍番号"
COL_STUDENT_NAME = "氏名"
COL_QUERY = "質問・感想"
COL_RESPONSE = "応答"

# チャットボット（main.py）は append_row([時間, 学籍番号, 氏名, 質問, 応答]) の順で保存するため、
# ヘッダー名に関係なく列の位置で読み込む
SHEET_COLUMNS = [COL_TIMESTAMP, COL_STUDENT_ID, COL_STUDENT_NAME, COL_QUERY, COL_RESPONSE]

# ストップワード（分析から除外する単語）
STOP_WORDS = {
    # 日本語ストップワード
    "する", "ある", "いる", "なる", "れる", "られる", "こと", "もの",
    "ため", "よう", "さ", "て", "に", "は", "が", "を", "の", "で",
    "と", "も", "な", "か", "た", "し", "ない", "です", "ます",
    "思う", "考える", "わかる", "知る", "見る", "言う", "できる",
    "それ", "これ", "あれ", "どれ", "そう", "どう", "いう",
    "教える", "ください", "について", "場合", "とき", "何", "なん",
    # 英語ストップワード（冠詞・前置詞・代名詞など）
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "it", "this", "that",
    "are", "was", "were", "be", "been", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "can", "may",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us",
    "my", "your", "his", "its", "our", "how", "what", "when", "where",
    "who", "which", "why", "not", "no", "so", "as", "if", "about",
    "lecture", "think", "know", "use", "used", "using", "than", "more",
    "also", "parts", "part", "just", "get", "make",
}

# 英語→日本語 正規化マップ（同じ意味の単語を統一）
NORMALIZE_MAP = {
    # 共通
    "system": "システム",
    "systems": "システム",
    "data": "データ",
    "user": "ユーザー",
    "users": "ユーザー",
    "design": "設計",
    "ai": "AI",
    "lecture": "講義",
    # 情報ネットワーク工学入門
    "network": "ネットワーク",
    "networks": "ネットワーク",
    "protocol": "プロトコル",
    "protocols": "プロトコル",
    "packet": "パケット",
    "packets": "パケット",
    "router": "ルータ",
    "routers": "ルータ",
    "routing": "ルーティング",
    "address": "アドレス",
    "server": "サーバ",
    "client": "クライアント",
    "layer": "レイヤ",
    "ip": "IP",
    "tcp": "TCP",
    "udp": "UDP",
    "http": "HTTP",
    "dns": "DNS",
    "lan": "LAN",
    "osi": "OSI",
    # 情報システム実験
    "experiment": "実験",
    "report": "レポート",
    "program": "プログラム",
    "database": "データベース",
    "sql": "SQL",
    "python": "Python",
    # ソフトウェア工学
    "software": "ソフトウェア",
    "requirement": "要求",
    "requirements": "要求",
    "test": "テスト",
    "testing": "テスト",
    "agile": "アジャイル",
    "waterfall": "ウォーターフォール",
    "scrum": "スクラム",
    "uml": "UML",
    "model": "モデル",
    "class": "クラス",
    "object": "オブジェクト",
    "module": "モジュール",
    "quality": "品質",
    "project": "プロジェクト",
}

# ─────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("📊 チャットボット分析ダッシュボード")
        st.markdown("---")
        password = st.text_input("パスワードを入力してください", type="password")
        if st.button("ログイン"):
            if password == st.secrets["DASHBOARD_PASSWORD"]:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.stop()

# ─────────────────────────────────────────────
# Google Sheets接続
# ─────────────────────────────────────────────
@st.cache_resource
def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GSPREAD_SERVICE_ACCOUNT"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_resource
def get_tokenizer():
    return Tokenizer()

def open_spreadsheet(sheet_ref: str):
    """URLならURLで、それ以外はスプレッドシート名で開く"""
    client = get_gspread_client()
    if sheet_ref.startswith("http"):
        return client.open_by_url(sheet_ref)
    return client.open(sheet_ref)

@st.cache_data(ttl=300)  # 5分キャッシュ
def load_registry() -> pd.DataFrame:
    rows = open_spreadsheet(st.secrets["REGISTRY_SHEET_URL"]).sheet1.get_all_values()
    return parse_registry(rows)

@st.cache_data(ttl=300)  # 5分キャッシュ
def load_data(sheet_ref: str) -> pd.DataFrame:
    worksheet = open_spreadsheet(sheet_ref).sheet1  # 各ファイルの最初のシートを取得
    rows = worksheet.get_all_values()
    if not rows:
        return pd.DataFrame(columns=SHEET_COLUMNS)

    # 1行目がヘッダー行（日時として解釈できない）なら除外
    if pd.isna(pd.to_datetime(rows[0][0], errors="coerce")):
        rows = rows[1:]

    # 列数を5列に揃える（足りない列は空文字で埋める）
    n = len(SHEET_COLUMNS)
    rows = [(r + [""] * n)[:n] for r in rows if any(c.strip() for c in r)]
    df = pd.DataFrame(rows, columns=SHEET_COLUMNS)
    if df.empty:
        return df

    df[COL_TIMESTAMP] = pd.to_datetime(df[COL_TIMESTAMP], errors="coerce")
    for col in [COL_STUDENT_ID, COL_STUDENT_NAME, COL_QUERY, COL_RESPONSE]:
        df[col] = df[col].astype(str).str.strip()
    # 空の質問は分析対象外
    df[COL_QUERY] = df[COL_QUERY].replace("", pd.NA)
    return df

# ─────────────────────────────────────────────
# 分析関数
# ─────────────────────────────────────────────
def extract_keywords(texts: pd.Series, top_n: int = 20) -> pd.DataFrame:
    """janomeで形態素解析し、頻出名詞・動詞を抽出（英語正規化付き）"""
    tokenizer = get_tokenizer()
    word_list = []
    for text in texts.dropna():
        for token in tokenizer.tokenize(str(text)):
            part = token.part_of_speech.split(",")[0]
            word = token.surface
            # 英語を小文字に統一してからストップワードチェック
            word_lower = word.lower()
            if word_lower in STOP_WORDS:
                continue
            # 英語→日本語に正規化
            word = NORMALIZE_MAP.get(word_lower, word)
            if part in ("名詞", "動詞") and len(word) > 1 and word not in STOP_WORDS:
                word_list.append(word)
    counter = Counter(word_list)
    df = pd.DataFrame(counter.most_common(top_n), columns=["キーワード", "出現回数"])
    return df

def classify_question(text: str) -> str:
    """質問タイプを簡易分類"""
    text = str(text).lower()
    if any(w in text for w in ["エラー", "動かない", "うまくいかない", "できない", "error", "exception", "traceback", "bug"]):
        return "トラブル・エラー"
    elif any(w in text for w in ["とは", "って何", "何ですか", "とはなんですか", "what is", "what are", "what's"]):
        return "概念理解（〜とは？）"
    elif any(w in text for w in ["なぜ", "なんで", "どうして", "理由", "why", "reason"]):
        return "理由・原因（なぜ？）"
    elif any(w in text for w in ["どうやって", "どのように", "方法", "使い方", "手順", "やり方", "how to", "how can", "how do"]):
        return "方法・手順（どうやって？）"
    elif any(w in text for w in ["違い", "比べ", "比較", "どちら", "difference", "compare", "vs", "versus", "better"]):
        return "比較・違い"
    elif any(w in text for w in ["課題", "レポート", "提出", "締切", "締め切り", "テスト", "試験", "成績", "assignment", "deadline", "exam"]):
        return "課題・試験・授業運営"
    elif any(w in text for w in ["思う", "感じ", "感想", "面白", "難し", "すご", "i think", "i feel", "interesting", "difficult", "amazing"]):
        return "感想・コメント"
    else:
        return "その他"

# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
st.set_page_config(page_title="チャットボット分析ダッシュボード", page_icon="📊", layout="wide")

check_password()

st.title("📊 チャットボット分析ダッシュボード")

SHEET_OPEN_ERRORS = (
    gspread.exceptions.SpreadsheetNotFound,
    gspread.exceptions.NoValidUrlKeyFound,
    gspread.exceptions.APIError,
)

# ─── サイドバー ───
with st.sidebar:
    st.header("⚙️ フィルター")

    # 科目台帳の読み込み
    try:
        registry = load_registry()
    except SHEET_OPEN_ERRORS:
        st.error(
            "科目台帳を開けません。secrets の REGISTRY_SHEET_URL が正しいか、"
            "台帳がサービスアカウントに共有されているか確認してください。"
        )
        st.stop()
    except ValueError as e:
        st.error(str(e))
        st.stop()

    if registry.empty:
        st.warning("科目台帳に科目が登録されていません")
        st.stop()

    # 年度・学期・授業の選択（既定は最新の年度の最後の学期）
    years = sorted(registry[COL_YEAR].unique(), reverse=True)
    selected_year = st.selectbox("年度", years, format_func=lambda y: f"{y}年度")
    in_year = registry[registry[COL_YEAR] == selected_year]

    terms = sort_terms(in_year[COL_TERM].unique())
    selected_term = st.selectbox("学期", terms, index=len(terms) - 1)
    in_term = in_year[in_year[COL_TERM] == selected_term]

    selected_class = st.selectbox("授業を選択", in_term[COL_COURSE].tolist())
    sheet_ref = in_term.loc[in_term[COL_COURSE] == selected_class, COL_SHEET].iloc[0]

    # データ読み込み
    try:
        df = load_data(sheet_ref)
    except SHEET_OPEN_ERRORS:
        st.error(
            f"「{selected_class}」のスプレッドシートを開けません。"
            "台帳のURLが正しいか、サービスアカウントに共有されているか確認してください。"
        )
        st.stop()

    if df.empty:
        st.warning("データがありません")
        st.stop()

    # 期間フィルター（日付範囲で自由に指定）
    st.markdown("---")
    st.subheader("期間")
    period_label = "全期間"
    if not df[COL_TIMESTAMP].dropna().empty:
        min_date = df[COL_TIMESTAMP].min().date()
        max_date = df[COL_TIMESTAMP].max().date()
        date_range = st.date_input(
            "期間を選択（開始日 〜 終了日）",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        # 開始日のみ選択中（終了日が未確定）の場合にも対応
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df = df[
                (df[COL_TIMESTAMP].dt.date >= start_date)
                & (df[COL_TIMESTAMP].dt.date <= end_date)
            ]
            period_label = f"{start_date.strftime('%Y/%m/%d')} 〜 {end_date.strftime('%Y/%m/%d')}"
        else:
            start_date = date_range[0] if isinstance(date_range, tuple) else date_range
            df = df[df[COL_TIMESTAMP].dt.date >= start_date]
            period_label = f"{start_date.strftime('%Y/%m/%d')} 〜"

    # 学生フィルター
    st.markdown("---")
    st.subheader("学生")
    all_students = ["全員"] + sorted(df[COL_STUDENT_NAME].replace("", pd.NA).dropna().unique().tolist())
    selected_student = st.selectbox("学生を選択", all_students)
    if selected_student != "全員":
        df = df[df[COL_STUDENT_NAME] == selected_student]

    st.markdown("---")
    if st.button("🔄 データを再読み込み"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"{selected_year}年度 {selected_term}｜{selected_class}")

# フィルター後のスライスに列を追加するため、独立したコピーにする
df = df.copy()
df["質問タイプ"] = df[COL_QUERY].apply(classify_question)

# ─── KPIカード ───
n_students = df[COL_STUDENT_ID].nunique()
col1, col2, col3, col4 = st.columns(4)
col1.metric("総質問数", len(df))
col2.metric("ユニーク学生数", n_students)
col3.metric("1人あたり平均質問数", f"{len(df) / n_students:.1f}" if n_students > 0 else "-")
col4.metric("期間", f"{df[COL_TIMESTAMP].min().strftime('%m/%d')} 〜 {df[COL_TIMESTAMP].max().strftime('%m/%d')}" if not df[COL_TIMESTAMP].dropna().empty else "-")

st.markdown("---")

ANALYSIS_SYSTEM_PROMPT = """あなたは大学の授業担当教員を支援するアナリストです。授業用AIチャットボットのログ（学生が書いた質問・感想と、チャットボットが返した応答）を読み、教員が授業や指導の改善に使えるまとめを日本語で作成します。

まとめは必ずログに書かれている内容だけを根拠にしてください。
- 学生の質問・感想を示すときは、ログの文面をそのまま引用する。長い場合は「…」で省略してよいが、言い換えや創作はしない。
- 応答の要約は、ログにあるチャットボットの実際の応答の要点をまとめたものにする。ログにない説明を自分で補ったり、より良い回答に書き換えたりしない。
- 「多い」「目立つ」と書くのは、ログの中で実際に複数見られる場合だけにする。1件しかない内容は「〜という声もあった」のように書く。
- 学生の氏名や学籍番号は書かない。"""


def _format_log(df_target: pd.DataFrame) -> str:
    """質問・感想と応答の組を、番号付きのレコードとして時系列順に並べる"""
    records = []
    for i, (query, response) in enumerate(zip(df_target[COL_QUERY], df_target[COL_RESPONSE]), start=1):
        records.append(
            f'<record id="{i}">\n'
            f"<質問・感想>{query}</質問・感想>\n"
            f"<応答>{response or '（応答なし）'}</応答>\n"
            f"</record>"
        )
    return "\n".join(records)


def _build_class_prompt(context: str, log: str) -> str:
    return f"""以下は{context}と、それに対するチャットボットの応答です。

<log>
{log}
</log>

ログ全体に目を通し、次の構成でまとめてください。最初に、確認した件数と代表例の選び方を1〜2文で述べてください。

## 1. 代表的な質問・感想と応答（10件）
似た内容の質問・感想をまとめたうえで、代表的なものを10件選んでください（全体が10件に満たない場合はある分だけ）。
- 繰り返し出てくる内容を優先しつつ、授業内容の理解でつまずいている点、演習やツール操作での困りごと、授業内容への感想・気づき、授業運営やチャットボット自体への質問・要望が、ログにある範囲でバランスよく入るようにする。
- 同じ趣旨の質問・感想が複数あれば、1件にまとめて「」を並べてよい。
- 次の列の表にする。応答の要約は、実際の応答の要点（手順・判断基準・用語の説明など具体的な中身）を2〜3文の「だ・である」調でまとめる。励ましや前置き、末尾の問いかけは要約に含めない。

| No. | 代表的な質問・感想 | 応答の要約 |
|---|---|---|

## 2. 全体的な傾向
学生の質問・感想に繰り返し現れるテーマを3〜5個、番号付きで挙げてください。各テーマは太字の見出しと、学生が実際にどう書いているかを踏まえた1〜2文の説明にします。理解が難しいと感じられている点と、肯定的な感想の両方に触れてください。

## 3. チャットボットの応答について
応答の長さ、形式、末尾での問いかけ、授業運営に関する質問（出席・提出方法など）への答え方など、ログの応答から読み取れる特徴と改善点を2〜3点挙げてください。

## 4. 授業改善への示唆
分析結果をもとに、先生へのアドバイスを1〜2点挙げてください。"""


def _build_student_prompt(context: str, log: str) -> str:
    return f"""以下は{context}と、それに対するチャットボットの応答です。

<log>
{log}
</log>

次の4点をまとめてください。

## 1. この学生の主な関心テーマ
どんなトピックに関心を持っているかを箇条書きで。

## 2. 理解が不足していそうな部分
繰り返し質問している内容や混乱が見られる概念を、該当する質問・感想を引用しながら指摘してください。見られなければ「特に見られない」と書いてください。

## 3. 学習の傾向
質問・感想の深さや種類から見える学習の様子を2〜3文でまとめてください。

## 4. この学生へのサポート提案
チャットボットの応答だけでは解決していなさそうな点を踏まえ、先生が取れるアドバイスや支援を1〜2点挙げてください。"""


def _run_ai_analysis(df_target, class_name, student_name, date_label):
    df_target = df_target.dropna(subset=[COL_QUERY]).sort_values(COL_TIMESTAMP)
    if df_target.empty:
        st.warning("分析対象のデータがありません")
        return
    n = len(df_target)

    # 分析対象の説明文を組み立て
    if student_name != "全員":
        context = f"「{class_name}」の{student_name}さんの質問・感想（{n}件）"
    elif date_label and date_label != "全期間":
        context = f"「{class_name}」（期間：{date_label}）の全学生の質問・感想（{n}件）"
    else:
        context = f"「{class_name}」全期間の全学生の質問・感想（{n}件）"

    with st.spinner("Claudeが分析中...少し待ってください"):
        try:
            ai_client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            log = _format_log(df_target)

            if student_name != "全員":
                prompt = _build_student_prompt(context, log)
            else:
                prompt = _build_class_prompt(context, log)

            response = ai_client.messages.create(
                model="claude-sonnet-5",
                max_tokens=16000,  # 思考（thinking）分のトークンも含むため余裕を持たせる
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            # Sonnet 5 は思考ブロック（ThinkingBlock）を先頭に返すため、テキストブロックだけを取り出す
            result_text = "\n".join(b.text for b in response.content if b.type == "text")
            if response.stop_reason == "max_tokens":
                st.warning("出力が上限に達したため、分析結果が途中で切れている可能性があります")
            st.success(f"✅ 分析完了：{context}")
            st.markdown(result_text)
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

# ─── タブ構成 ───
tab1, tab2, tab3, tab4 = st.tabs(["📈 質問傾向", "👤 学生別分析", "🤖 AI分析", "📋 データ一覧"])

# ─────── Tab1: 質問傾向 ───────
with tab1:
    col_a, col_b = st.columns(2)

    # 頻出キーワード
    with col_a:
        st.subheader("🔑 頻出キーワード TOP20")
        kw_df = extract_keywords(df[COL_QUERY], top_n=20)
        if not kw_df.empty:
            fig = px.bar(
                kw_df, x="出現回数", y="キーワード",
                orientation="h",
                color="出現回数",
                color_continuous_scale="Blues"
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=500)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("キーワードが見つかりませんでした")

    # 質問タイプ分布
    with col_b:
        st.subheader("🗂️ 質問タイプの分布")
        type_counts = df["質問タイプ"].value_counts().reset_index()
        type_counts.columns = ["質問タイプ", "件数"]
        fig2 = px.pie(type_counts, names="質問タイプ", values="件数", hole=0.4)
        fig2.update_layout(height=500)
        st.plotly_chart(fig2, width="stretch")

    # 時間帯別質問数
    st.subheader("🕐 時間帯別 質問数")
    df["時間帯"] = df[COL_TIMESTAMP].dt.hour
    hourly = df.groupby("時間帯").size().reset_index(name="質問数")
    fig3 = px.bar(hourly, x="時間帯", y="質問数", color="質問数", color_continuous_scale="Teal")
    fig3.update_layout(xaxis=dict(tickmode="linear", dtick=1))
    st.plotly_chart(fig3, width="stretch")

    # 曜日別質問数（授業日との関係を見る）
    st.subheader("📆 曜日別 質問数")
    weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
    weekday = df[COL_TIMESTAMP].dt.dayofweek.dropna().astype(int).map(lambda i: weekday_names[i])
    weekly = weekday.value_counts().reindex(weekday_names, fill_value=0).reset_index()
    weekly.columns = ["曜日", "質問数"]
    fig_w = px.bar(weekly, x="曜日", y="質問数", color="質問数", color_continuous_scale="Oranges")
    st.plotly_chart(fig_w, width="stretch")

    # 日別質問数推移
    st.subheader("📅 日別 質問数推移")
    df["日付"] = df[COL_TIMESTAMP].dt.date
    daily = df.groupby("日付").size().reset_index(name="質問数")
    fig4 = px.line(daily, x="日付", y="質問数", markers=True)
    st.plotly_chart(fig4, width="stretch")

# ─────── Tab2: 学生別分析 ───────
with tab2:
    st.subheader("👤 学生ごとの質問数ランキング")
    student_stats = df.groupby([COL_STUDENT_ID, COL_STUDENT_NAME]).agg(
        質問数=(COL_QUERY, "count"),
    ).reset_index().sort_values("質問数", ascending=False)

    # 質問タイプの内訳を追加
    type_by_student = df.groupby([COL_STUDENT_ID, "質問タイプ"]).size().unstack(fill_value=0).reset_index()
    student_stats = student_stats.merge(type_by_student, on=COL_STUDENT_ID, how="left")

    fig5 = px.bar(
        student_stats, x=COL_STUDENT_NAME, y="質問数",
        color="質問数", color_continuous_scale="Purples",
        labels={COL_STUDENT_NAME: "学生名"}
    )
    st.plotly_chart(fig5, width="stretch")

    with st.expander("📊 学生別の質問タイプ内訳（表）"):
        st.dataframe(student_stats, width="stretch", hide_index=True)

    # 繰り返し質問の検出
    st.subheader("🔁 同じキーワードへの繰り返し質問（理解定着チェック）")
    st.caption("同じ学生が似たキーワードを複数回質問している場合に表示されます")

    tokenizer = get_tokenizer()
    repeat_records = []
    for sid, group in df.groupby(COL_STUDENT_ID):
        name = group[COL_STUDENT_NAME].iloc[0]
        word_counter = Counter()
        for text in group[COL_QUERY].dropna():
            for token in tokenizer.tokenize(str(text)):
                part = token.part_of_speech.split(",")[0]
                word = NORMALIZE_MAP.get(token.surface.lower(), token.surface)
                if part == "名詞" and len(word) > 1 and word.lower() not in STOP_WORDS:
                    word_counter[word] += 1
        repeated = [(w, c) for w, c in word_counter.items() if c >= 3]
        for word, count in sorted(repeated, key=lambda x: -x[1]):
            repeat_records.append({"学生名": name, "繰り返しキーワード": word, "出現回数": count})

    if repeat_records:
        repeat_df = pd.DataFrame(repeat_records).sort_values("出現回数", ascending=False)
        st.dataframe(repeat_df, width="stretch", hide_index=True)
    else:
        st.info("繰り返し質問（3回以上）は見つかりませんでした")

# ─────── Tab3: AI分析 ───────
with tab3:
    st.subheader("🤖 AIによる内容分析")
    st.caption("Claudeが質問・感想とチャットボットの応答を読み、傾向をまとめます（APIコストがかかるため必要なときだけ実行してください）")

    # 現在の分析対象を明示
    if selected_student != "全員":
        st.info(f"📌 分析対象：**{selected_student}さん** の個別分析（{len(df)}件）")
    else:
        st.info(f"📌 分析対象：**{selected_class}**（期間：{period_label}） 全学生（{len(df)}件）")

    st.markdown("---")
    st.write("サイドバーのフィルター（授業・期間・学生）で絞り込んだデータを分析します。")
    st.write(f"現在の対象件数：**{len(df)}件**")

    if st.button("🔍 AI分析を実行", type="primary"):
        _run_ai_analysis(df, f"{selected_year}年度 {selected_term} {selected_class}", selected_student, period_label)

# ─────── Tab4: データ一覧 ───────
with tab4:
    st.subheader("📋 質問・回答ログ")
    log_df = df[SHEET_COLUMNS].sort_values(COL_TIMESTAMP, ascending=False)

    keyword = st.text_input("🔎 質問・応答をキーワードで検索", "")
    if keyword:
        mask = (
            log_df[COL_QUERY].fillna("").str.contains(keyword, case=False, regex=False)
            | log_df[COL_RESPONSE].fillna("").str.contains(keyword, case=False, regex=False)
        )
        log_df = log_df[mask]
        st.caption(f"{len(log_df)}件ヒット")

    st.dataframe(log_df, width="stretch", hide_index=True)

    # CSVダウンロード
    csv = log_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 CSVダウンロード",
        data=csv,
        file_name=f"{selected_year}{selected_term}_{selected_class}_log_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )
