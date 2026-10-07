"""科目台帳（Google Sheet）の読み込み

台帳の1行目はヘッダー行で、少なくとも次の4列を含めます（列の順番は自由）：
    年度 / 学期 / 科目名 / スプレッドシートURL
任意で「表示」列を置くと、FALSE・非表示・0 などと書いた行はダッシュボードに出しません。
"""
import pandas as pd

COL_YEAR = "年度"
COL_TERM = "学期"
COL_COURSE = "科目名"
COL_SHEET = "スプレッドシートURL"
COL_VISIBLE = "表示"

REQUIRED_COLUMNS = [COL_YEAR, COL_TERM, COL_COURSE, COL_SHEET]

# 「表示」列にこれらの値が入っている行は除外する（小文字で比較）
HIDDEN_VALUES = {"false", "0", "no", "非表示", "×"}

# 学期の並び順（ここにない学期名は後ろに並べる）
TERM_ORDER = {"前期": 0, "後期": 1}


def parse_registry(rows: list[list[str]]) -> pd.DataFrame:
    """get_all_values() で取得した台帳の行を、必須4列の DataFrame に変換する"""
    if not rows:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    header = [h.strip() for h in rows[0]]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"台帳に次の列が見つかりません：{'・'.join(missing)}")

    n = len(header)
    body = [[c.strip() for c in (r + [""] * n)[:n]] for r in rows[1:]]
    df = pd.DataFrame(body, columns=header)

    if COL_VISIBLE in df.columns:
        df = df[~df[COL_VISIBLE].str.lower().isin(HIDDEN_VALUES)]

    # 必須列のどれかが空の行（書きかけの行など）は無視する
    df = df[(df[REQUIRED_COLUMNS] != "").all(axis=1)]
    return df[REQUIRED_COLUMNS].reset_index(drop=True)


def sort_terms(terms) -> list[str]:
    """学期名を 前期 → 後期 の順に並べる"""
    return sorted(terms, key=lambda t: (TERM_ORDER.get(t, len(TERM_ORDER)), t))
