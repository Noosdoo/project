import wikipediaapi
import random
import time
from collections import Counter

# --- 1. Wikipedia APIの準備 ---
# User-Agentは必ず設定してください（あなたのプロジェクト名や連絡先が望ましい）
user_agent = "AkinatorProject/1.0 (your-email@example.com)"
wiki_ja = wikipediaapi.Wikipedia(
    user_agent=user_agent,
    language='ja'
)

# 無視するカテゴリ（人物の属性と関係ないもの）
IGNORE_CATEGORIES = [
    'Category:存命人物', 'Category:死去した人物', 'Category:Pages using constraint references',
    'Category:生年', 'Category:没年', 'Category:Pages using duplicate arguments in template calls'
]

def get_people_from_category(category_name, max_people=50):
    """
    指定されたカテゴリから、人物ページのリストを取得する。
    APIアクセスが多すぎないよう、人数を制限する。
    """
    print(f"「Category:{category_name}」から人物リストを取得中...")
    cat_page = wiki_ja.page(f"Category:{category_name}")
    
    if not cat_page.exists():
        print(f"エラー: カテゴリ「{category_name}」が見つかりません。")
        return []

    # categorymembers から全メンバーを取得 (この時点ではページオブジェクトではない)
    all_members = list(cat_page.categorymembers.keys())
    
    # 人物ページだけに絞り込み (サブカテゴリやファイルを除外)
    person_titles = [
        title for title in all_members 
        if not title.startswith('Category:') and not title.startswith('ファイル:')
    ]
    
    # 人数が多すぎる場合、ランダムに絞り込む
    if len(person_titles) > max_people:
        print(f"（候補者が多すぎるため、{max_people}人にランダムで絞り込みます）")
        person_titles = random.sample(person_titles, max_people)
    
    print(f"対象人数: {len(person_titles)}人")
    return person_titles

def build_candidate_database(person_titles):
    """
    人物名のリストを受け取り、全員分のカテゴリ情報を取得してデータベース化する。
    【注意】この処理は、人数分のAPIアクセスが発生するため、非常に時間がかかります。
    """
    print("\n--- 全候補者のカテゴリ情報を取得します ---")
    print("（対象人数が多いため、数分かかる場合があります...）")
    
    candidates_db = {} # { "名前": ["カテゴリ1", "カテゴリ2"] } の辞書
    
    for i, title in enumerate(person_titles):
        print(f"処理中... ({i+1}/{len(person_titles)}) {title}")
        page = wiki_ja.page(title)
        
        if not page.exists():
            continue
            
        # カテゴリを取得し、不要なものを除外
        categories = [
            cat for cat in page.categories.keys() 
            if cat not in IGNORE_CATEGORIES and not cat.startswith(('Category:1', 'Category:2'))
        ]
        
        candidates_db[title] = categories
        time.sleep(0.1) # APIに負荷をかけないよう、少し待機

    print("--- データベース構築完了 ---")
    return candidates_db

def find_best_question(candidates, asked_categories):
    """
    残っている候補者リストから、最も効率よく絞り込めそうな質問（カテゴリ）を見つける。
    （候補者を最も50/50に分けられるカテゴリを探す）
    """
    category_counts = Counter()
    
    # 残っている候補者が持っているカテゴリをすべてカウント
    for title in candidates:
        for category in candidates[title]:
            if category not in asked_categories:
                category_counts[category] += 1
                
    if not category_counts:
        return None # 聞ける質問がもうない

    best_category = None
    best_score = -1 # 0に近いほど悪い（全員Yes/No）
    
    num_candidates = len(candidates)
    
    for category, count in category_counts.items():
        # count = 「はい」と答える人の数
        # num_candidates - count = 「いいえ」と答える人の数
        
        # 50/50 に近いほどスコアが高くなる計算
        score = count * (num_candidates - count)
        
        if score > best_score:
            best_score = score
            best_category = category
            
    return best_category

def filter_candidates(candidates, category, answer_is_yes):
    """
    回答（はい/いいえ）に基づいて、候補者リストを絞り込む
    """
    new_candidates = {}
    for title, categories in candidates.items():
        has_category = (category in categories)
        
        if answer_is_yes and has_category:
            new_candidates[title] = categories # 「はい」で、持っていたら残す
        elif not answer_is_yes and not has_category:
            new_candidates[title] = categories # 「いいえ」で、持っていなかったら残す
            
    return new_candidates

# --- 3. メインの実行部分 ---
def main():
    print("--- 著名人当てゲーム (Wikipedia カテゴリ版) ---")
    category_name = input("どのカテゴリの著名人を対象にしますか？ (例: 日本の俳優) > ").strip()
    
    if not category_name:
        print("カテゴリが入力されませんでした。")
        return

    # 1. 候補者リストを取得
    person_titles = get_people_from_category(category_name, max_people=50) # 人数制限
    if not person_titles:
        return

    # 2. 候補者の全カテゴリ情報を取得（これがデータベースになる）
    # このプログラムで最も時間がかかる部分
    candidates_db = build_candidate_database(person_titles)
    
    if not candidates_db:
        print("データを取得できませんでした。")
        return

    # 3. ゲーム開始
    remaining_candidates = candidates_db
    asked_categories = set()
    question_count = 0
    max_questions = 20

    print("\n--- ゲーム開始！ ---")
    print("頭の中に、リストの誰か一人を思い浮かべてください。")
    print("「yes」「no」または「y」「n」で答えてください。")

    while len(remaining_candidates) > 1 and question_count < max_questions:
        question_count += 1
        
        # 3-1. 最適な質問を見つける
        best_category = find_best_question(remaining_candidates, asked_categories)
        
        if best_category is None:
            print("（これ以上絞り込める質問がありません）")
            break
            
        asked_categories.add(best_category)
        
        # カテゴリ名を質問文に変換
        question_text = best_category.replace('Category:', '') + " ですか？"
        
        # 3-2. 質問する
        answer_raw = input(f"\n質問{question_count}: {question_text} (残り候補: {len(remaining_candidates)}人) > ").strip().lower()
        
        if answer_raw in ["yes", "y", "はい"]:
            answer_is_yes = True
        elif answer_raw in ["no", "n", "いいえ"]:
            answer_is_yes = False
        else:
            print("（yes/noで答えてください。スキップします）")
            continue
            
        # 3-3. 候補者を絞り込む
        remaining_candidates = filter_candidates(remaining_candidates, best_category, answer_is_yes)

    # --- 4. 結果発表 ---
    print("\n--- 結果 ---")
    if len(remaining_candidates) == 1:
        result_name = list(remaining_candidates.keys())[0]
        print(f"あなたが思い浮かべたのは... 【{result_name}】 ですね！")
    elif len(remaining_candidates) == 0:
        print("あれ...？ 該当する人がデータにいませんでした。")
    else:
        print(f"すみません、{max_questions}回の質問では特定できませんでした。")
        print("以下の可能性があります。")
        for name in list(remaining_candidates.keys())[:5]: # 最大5人まで表示
            print(f"- {name}")

# このファイルが直接実行された時だけ、main()を動かす
if __name__ == "__main__":
    main()