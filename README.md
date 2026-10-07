# チャットボット分析ダッシュボード

授業用AIチャットボットの質問・応答ログ（Google Sheet）を分析する Streamlit アプリです。
年度・学期をまたいで同じURLで使えるよう、授業とスプレッドシートの対応はコードに書かず、
**科目台帳**（固定の Google Sheet）から読み込みます。

- 公開URL：https://chatbot-analysis-dashboard-xxx.streamlit.app/
- メインファイル：`streamlit_app.py`

## 科目台帳

1枚目のシートの1行目をヘッダーとし、次の列を用意します（列の順番は自由）。

| 年度 | 学期 | 科目名 | スプレッドシートURL | 表示 |
|---|---|---|---|---|
| 2026 | 後期 | ソフトウェア工学 | https://docs.google.com/spreadsheets/d/.../edit | TRUE |

- `年度`・`学期`・`科目名`・`スプレッドシートURL` は必須です。どれかが空の行は無視されます。
- `スプレッドシートURL` にはURLを書きます。URLの代わりにスプレッドシート名を書いても開けます。
- `表示` は任意です。`FALSE`・`非表示`・`0` と書いた行はダッシュボードに出ません。
- ダッシュボードでは、最新の年度の最後の学期が最初に選ばれます。

[registry_template.csv](registry_template.csv) は、2026年度前期の2授業と後期の3授業を登録したひな形です。
Google Sheets にインポートし、スプレッドシートURLの列を各シートのURLに差し替えて使えます。

### 新しい学期・科目を追加するとき

1. 授業のスプレッドシートを、サービスアカウントの `client_email` に共有する
2. 科目台帳に1行追加する

コードの修正や再デプロイは不要です（台帳は5分ごとに読み直されます。すぐ反映したいときはサイドバーの「データを再読み込み」を押してください）。

## セットアップ

1. 科目台帳を作り、サービスアカウントの `client_email` に共有する
2. [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) を参考に secrets を設定する
   - ローカル：`.streamlit/secrets.toml` に記入（コミットしない）
   - Streamlit Community Cloud：アプリ設定の「Secrets」欄に記入
3. ローカルで動かす場合

   ```bash
   pip install -r requirements.txt
   streamlit run streamlit_app.py
   ```

## 授業スプレッドシートの形式

各チャットボットが `append_row([時間, 学籍番号, 氏名, 質問, 応答])` の順で書き込むことを前提に、
ヘッダー名に関係なく1枚目のシートの先頭5列を列の位置で読み込みます。
