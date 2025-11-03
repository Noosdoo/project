import wikipediaapi
import sys

# 標準出力のエンコーディングをUTF-8に設定 (ターミナルでの文字化け防止)
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
except (AttributeError, TypeError):
    pass

# ユーザーエージェントを設定
USER_AGENT = "MyWikiChecker/1.0 (contact@example.com)"

# Wikipedia APIに接続
wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")

# --- ここに確認したい人物名を入力 ---
PERSON_NAME = "佐藤健 (俳優)"
# ---

print(f"--- 🔍 『{PERSON_NAME}』のデータを取得します ---")

# ページを取得
page = wiki.page(PERSON_NAME)

if not page.exists():
    print("エラー: ページが見つかりません。")
else:
    print("\n--- 1. タイトル (page.title) ---")
    print(page.title)

    print("\n--- 2. 概要文 (page.summary) ---")
    # 概要文（アキネーターのJanomeが分析しているのは主にこれ）
    print(page.summary)

    print("\n--- 3. カテゴリ (page.categories) ---")
    # dict_keys(['Category:1989年生', 'Category:存命人物', ...]) のように表示
    print(list(page.categories.keys()))

    print("\n--- 4. ページ全文 (page.text) ---")
    # ページの「全文」がプレーンテキストで表示されます
    print("（全文は長いため、最初の500文字のみ表示します）")
    print(page.text[:500] + "...")

print("\n--- 処理完了 ---")