import requests # HTTPリクエスト用
import time # スリープ用
import json # JSON操作用
import os # ファイル操作用
import re # 正規表現用
import unicodedata # 文字列正規化用
import random # ランダム選択用
import wikipediaapi # Wikipedia API用
import traceback # デバッグ用にインポート
import hashlib # ★ ハッシュ化のため追加
from datetime import datetime # 日付処理のため
from concurrent.futures import ThreadPoolExecutor, as_completed # 並列処理用
import sys # 標準入出力のエンコーディング設定用
import traceback # デバッグ用にインポート

# 標準入出力のエンコーディングをUTF-8に設定
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
except (AttributeError, TypeError):
    pass

# Janome（形態素解析ライブラリ）のインポート
try:
    from janome.tokenizer import Tokenizer
    JANOME_TOKENIZER = Tokenizer()
    print("Janome (形態素解析) を読み込みました。")
except ImportError:
    print("---------------------------------------------------------------")
    print("エラー: Janomeがインストールされていません。")
    print("動的な質問生成（名詞分析）を利用するには、Janomeが必要です。")
    print("ターミナルで `pip install -U janome` を実行してください。")
    print("---------------------------------------------------------------")
    JANOME_TOKENIZER = None
except Exception as e:
    print(f"Janomeの読み込み中に予期せぬエラー: {e}")
    JANOME_TOKENIZER = None


# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
# WikipediaおよびWikidataのAPIエンドポイント
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ
CATEGORIES = [
    # 俳優・芸能
    "日本の俳優", "日本の女優", "お笑い芸人", "日本の声優", "日本のアイドル", "日本のモデル", "日本の歌手",
    "日本の作曲家", "日本の映画監督", "日本の舞台俳優", "日本のアナウンサー", "日本のYouTuber",
    # 文学・学問
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の医師", "日本の教育者",
    # 政治・社会
    "日本の政治家", "日本の官僚", "日本の実業家", "日本の起業家", "日本の弁護士",
    # スポーツ
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本の柔道家", "日本の格闘家", "日本のレスリング選手", "日本のオリンピック選手",
    "日本の水泳選手", "日本の陸上競技選手", "日本のテニス選手", "日本のバレーボール選手", "日本のバスケットボール選手", "日本のゴルフ選手",
    # 芸術・文化
    "日本の画家", "日本の建築家", "日本のデザイナー", "日本の作曲家"
]

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}

# -----------------------
# Wikipediaのメイン画像URLを取得
# -----------------------
def get_wikipedia_main_image(title, thumb_size=300):
    """
    Wikipedia APIを使い、ページのメイン画像（サムネイル）のURLを取得する。
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",      
        "pithumbsize": str(thumb_size), 
        "format": "json",
    }
    
    data = get_json_with_retry(WIKI_API, params=params)
    
    if not data: return None
    
    pages = data.get("query", {}).get("pages", {})
    if not pages: return None
        
    page_id = next(iter(pages))
    page_data = pages[page_id]
    
    if "thumbnail" in page_data:
        return page_data["thumbnail"]["source"]
    elif "original" in page_data: 
        return page_data["original"]["source"]
    else:
        return None


# -----------------------
# カテゴリに基づいたキャッシュファイル名
# -----------------------
def get_dynamic_cache_path(categories_list, prefix="people_list"):
    """
    選択されたカテゴリリストから一意のハッシュを生成し、
    キャッシュファイル名（.json）を返す。
    
    ★ 修正: 
    - 全選択 (または0選択) の場合のみ "ALL" を使用。
    - それ以外 (1〜46カテゴリ) の場合は、すべて名前を連結する。
    """
    # 常にソートして、「俳優,女優」と「女優,俳優」が同じハッシュ/名前になるようにする
    sorted_cats = sorted(list(set(categories_list)))
    
    num_cats = len(sorted_cats)
    total_cats = len(CATEGORIES) # グローバルのカテゴリ総数を参照
    
    filename_part = ""

    # --- ファイル名のルールを決定 ---

    # 1. カテゴリ未選択(Enter) または 全カテゴリを選択した場合
    if num_cats == 0 or num_cats == total_cats:
        filename_part = "ALL"
        
    # 2. それ以外 (1カテゴリでも、40カテゴリでも) の場合
    else:
        # カテゴリ名をアンダースコアで連結
        # (ファイル名として使えない文字を置換)
        safe_names = [re.sub(r'[\\/:*?"<>|]', '-', cat) for cat in sorted_cats]
        filename_part = "_".join(safe_names)

    # 最終的なファイル名を返す
    return f"{prefix}_{filename_part}.json"

# -----------------------
# 除外ルール: 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"] # 除外キーワード
    return not any(k in title for k in exclude_keywords) # 人物ページとみなす

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=1.5):
    # 再帰的にカテゴリメンバーを収集
    if collected is None:
        collected = set() # 初期化
    cmtitle = f"Category:{category}" # カテゴリタイトル
    # APIパラメータ
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": cmtitle, "cmlimit": str(cmlimit), "format": "json"
    }
    # ページネーション対応
    cont = None
    while True:
        # 続きパラメータを追加
        if cont: params.update(cont)
        # APIリクエスト
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        # HTTPエラーチェック
        except Exception as e:
            print(f"HTTPエラー: {e}"); return collected
        # アクセス拒否対応
        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。"); return collected
        # JSONデコード
        try:
            data = res.json()
        # デバッグ用: 取得したデータの一部を表示
        except Exception as e:
            print(f"JSONデコード失敗: {e}"); return collected # デコード失敗
        # メンバー処理
        for m in data.get("query", {}).get("categorymembers", []):
            # タイトル取得
            title = m.get("title")
            # 除外ルール適用
            if not title: continue
            # サブカテゴリの場合、深さが残っていれば再帰取得
            if title.startswith("Category:"):
                # 再帰呼び出し
                if depth > 0:
                    subcat = title[len("Category:"):] # サブカテゴリ名
                    time.sleep(sleep) # API負荷軽減
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep) # 再帰
                continue # サブカテゴリはスキップ
            # 除外キーワードチェック
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]) or not is_person_page(title):
                continue
            # 人物タイトルを追加
            collected.add(title)
        # 続き処理
        if "continue" in data:
            cont = data["continue"]; time.sleep(sleep) # API負荷軽減
        else:
            break
    return collected # collected titles

# -----------------------
# カテゴリ選択
# -----------------------
def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5) / 全ての場合は Enter")
    choice = input("> ").strip() # ユーザー入力
    # 選択処理
    if not choice:
        print("全カテゴリを対象にします。"); return CATEGORIES # 全選択
    selected = [] # 選択カテゴリ
    # 入力をパース
    for part in choice.split(","):
        # 番号をインデックスに変換
        try:
            idx = int(part)-1 # 1始まりを0始まりに変換
            if 0 <= idx < len(CATEGORIES): selected.append(CATEGORIES[idx]) # 有効なカテゴリを追加
        except: pass
    # 無効な入力は無視
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。"); return CATEGORIES
    print(f"選択されたカテゴリ: {', '.join(selected)}"); return selected

# -----------------------
# Step1: 全カテゴリから人物を収集して保存 
# -----------------------
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=1.5, save_path=PEOPLE_LIST_FILE, corresponding_dataset_path=DATASET_FILE):

    # 除外語リスト（非人物をはじく）
    EXCLUDE_KEYWORDS = [
        "テレビ", "番組", "映画", "ドラマ", "アニメ", "漫画", "作品",
        "イベント", "シリーズ", "コンビ", "グループ", "キャラクター",
        "音楽", "アルバム", "曲", "小説", "ゲーム", "企画", "特集",
        "大会", "舞台", "公演", "放送"
    ]

    # 人物らしい語（本文などから抽出に使える）
    INCLUDE_HINTS = [
        "俳優", "女優", "声優", "歌手", "ミュージシャン", "政治家", "作家",
        "小説家", "実業家", "科学者", "学者", "芸人", "タレント", "モデル",
        "アスリート", "スポーツ選手", "監督"
    ]

    # 既存ファイルのチェック
    target_categories = sorted(list(set(categories)))
    
    # 既存ファイルがあるかチェック
    if os.path.exists(save_path):
        # 既存ファイルを読み込み
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f) # JSON読み込み
            saved_categories = data.get("meta", {}).get("categories") # 保存時のカテゴリ
            people_list = data.get("people") # 保存時の人物リスト
            
            # カテゴリ比較 (カテゴリが一致しているか？)
            if saved_categories == target_categories and people_list is not None: 
                
                print(f"\n--- 💾 キャッシュが見つかりました ---")
                print(f"リスト: {save_path}")
                print(f"データセット: {corresponding_dataset_path}")
                print("このキャッシュを使用しますか？")
                print("  1: キャッシュを使用 (収集/構築をスキップ)")
                print("  2: 再収集 (キャッシュを削除して最初から)")
                
                choice = input(" (1/2) > ").strip() # ユーザー入力
                
                if choice == "1": # キャッシュ使用
                    print(f"キャッシュ {save_path} を使用します。collect はスキップします。")
                    return people_list # 既存の人物リストを返す (スキップ)
                
                elif choice == "2": # 再収集
                    print("キャッシュを削除し、人物リストを再収集します。") # 再収集
                    if os.path.exists(save_path): # 存在チェック
                        os.remove(save_path) # リストキャッシュを削除
                    if os.path.exists(corresponding_dataset_path): # 存在チェック
                        print(f"古いデータセット {corresponding_dataset_path} もリセットします。")
                        os.remove(corresponding_dataset_path) # データセットキャッシュも削除
                    # return せずに処理を続行 (再収集へ)
                
                else:
                    print("無効な選択です。デフォルトの「1: キャッシュを使用」を選びます。")
                    print(f"キャッシュ {save_path} を使用します。collect はスキップします。")
                    return people_list # 既存の人物リストを返す (スキップ)

            else: # カテゴリが不一致の場合
                print("カテゴリが変更されたため、人物リストを再収集します。")
                if os.path.exists(corresponding_dataset_path):
                    print(f"古いデータセット {corresponding_dataset_path} をリセットします。")
                    os.remove(corresponding_dataset_path)
        
        except Exception as e: # デコードエラーなど
            print(f"既存ファイルの形式が古いか壊れています: {e}。再収集します。")
            if os.path.exists(save_path):
                os.remove(save_path) # 壊れたリストキャッシュを削除
            if os.path.exists(corresponding_dataset_path): 
                os.remove(corresponding_dataset_path) # 関連データセットも削除

    # 収集開始
    print("=== カテゴリから人物リストを収集します ===")
    all_people = set() # 全人物セット

    for cat in target_categories: # 各カテゴリ処理
        print(f"取得中: {cat}") # カテゴリ名表示
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep) # 取得
        print(f"   → {len(people)} 件取得（フィルタ前）") # 取得数表示
        filtered = []
        for name in people:
            # ① 除外語フィルタ
            if any(word in name for word in EXCLUDE_KEYWORDS):
                continue

            # ② 名前があまりにも短い・数字だけの場合などを除外
            if len(name) < 2 or re.fullmatch(r"[0-9０-９A-Za-z]+", name):
                continue

            # （オプション）人物らしいワードが含まれるかチェック
            # ※ここは厳密にしすぎると漏れも出るので任意
            # if not any(hint in name for hint in INCLUDE_HINTS):
            #     continue

            filtered.append(name)

        print(f"   → {len(filtered)} 件（フィルタ後）") # フィルタ後の取得数表示
        all_people.update(filtered) # セットに追加
        time.sleep(sleep) # セットに追加、API負荷軽減
    
        all_people.update(people); time.sleep(sleep) # セットに追加、API負荷軽減

    people_list = sorted(list(all_people)) # リスト化・ソート

    # 保存
    save_data = {
        "meta": {"categories": target_categories, "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "people": people_list
    }

    # JSON保存
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2) # 保存
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）"); return people_list # 人物リスト返す

    return people_list


# -----------------------
# Wikidata取得補助
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {"action": "query", "titles": title, "prop": "pageprops", "format": "json"} # APIパラメータ
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15) # APIリクエスト
        data = res.json(); pages = data.get("query", {}).get("pages", {}) # JSON解析
        if not pages: return None # ページなし
        page = next(iter(pages.values())); pp = page.get("pageprops", {}) # ページプロパティ
        return pp.get("wikibase_item") # Wikibase ID返す
    except Exception: return None # エラー時はNone返す

# -----------------------
# Wikidataから構造化属性を取得 
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    # Wikidataエンティティを取得し、構造化属性を抽出
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id) # エンティティURL
        res = requests.get(url, headers=HEADERS, timeout=15) # APIリクエスト
        data = res.json() # JSON解析
        entity = data.get("entities", {}).get(wikibase_id, {}) # エンティティ取得
        claims = entity.get("claims", {}) # クレーム取得
        result = {} # 抽出結果
        
        # P106 (職業)
        if "P106" in claims:
            occ = [] # 職業QIDリスト
            for c in claims["P106"]: # 各クレーム処理
                try:
                    v = c["mainsnak"]["datavalue"]["value"]  # 値取得
                    if isinstance(v, dict) and "id" in v: occ.append(v["id"]) # QID追加
                except Exception: pass # エラー無視
            if occ: result["occupation_qids"] = occ # 職業QID保存
            
        # P21 (性別)
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"] # 値取得
                if isinstance(v, dict) and "id" in v: result["gender_qid"] = v["id"] # 性別QID保存
            except Exception: pass # エラー無視
            
        # P569 (birth time)
        if "P569" in claims:
            try:
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"] # 値取得
                result["birth_time"] = t # 保存
            except Exception: pass # エラー無視
            
        # P570 (death time)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"] # 値取得
                result["death_time"] = t # 保存
            except Exception: pass # エラー無視
            
        # P19 (birth place)
        if "P19" in claims:
            try:
                v = claims["P19"][0]["mainsnak"]["datavalue"]["value"] # 値取得
                if isinstance(v, dict) and "id" in v: # QID保存
                    result["birth_place_qid"] = v["id"] # 保存
            except Exception: pass # エラー無視
            
        # P69 (education)
        if "P69" in claims:
            edu_qids = [] # 教育機関QIDリスト
            for c in claims["P69"]: # 各クレーム処理
                try:
                    v = c["mainsnak"]["datavalue"]["value"] # 値取得
                    if isinstance(v, dict) and "id" in v: edu_qids.append(v["id"]) # QID追加
                except Exception: pass # エラー無視
            if edu_qids: result["education_qids"] = edu_qids # 教育機関QID保存

        # P166 (award received)
        if "P166" in claims:
            award_qids = [] # 受賞QIDリスト
            for c in claims["P166"]: # 各クレーム処理
                    try:
                        v = c["mainsnak"]["datavalue"]["value"] # 値取得
                        if isinstance(v, dict) and "id" in v: award_qids.append(v["id"]) # QID追加
                    except Exception: pass # エラー無視
            if award_qids: result["award_qids"] = award_qids # 受賞QID保存
        
        return result
    except Exception:
        return None

# Janomeトークナイザーインスタンス
tokenizer = Tokenizer()

# -----------------------
# テキストクリーンアップ
# -----------------------
def clean_text(text):
    # Unicode正規化
    text = unicodedata.normalize("NFKC", text)
    # 制御文字を除去
    text = re.sub(r"[\x00-\x1F\x7F]", "", text)
    # 不可視文字を除去
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    # 改行や連続空白を整理
    text = re.sub(r"\s+", " ", text).strip()
    return text

# -----------------------
# summaryから【Janomeベース（動的）】で特徴を抽出
# -----------------------
def extract_dynamic_features_from_summary(summary):
    """
    Janomeを使い、文章から特徴（名詞・形容詞・動詞）を抽出する。
    """
    if not JANOME_TOKENIZER:
        # Janomeが読み込まれていない場合のログ出力
        print("[DEBUG-DYNAMIC] Janome_TokenizerがNoneです。") 
        return {}
    
    if not summary:
        return {}
    
    features = {} 
    
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary) 
    except Exception as e:
        print(f"[DEBUG-DYNAMIC] Janome.tokenize(summary) でエラー: {e}")
        return {} 

    TARGET_POS_TYPES = {
        ('名詞', '一般'): 'noun_',
        ('名詞', '固有名詞'): 'noun_',
        ('形容詞', '自立'): 'adj_', 
        ('動詞', '自立'): 'verb_' 
    }

    # 除外単語リスト
    STOP_WORDS = {
        'こと', 'もの', 'ため', '人物', '概要', '日本', '活動', '出身',
        '現在', '自身', 'ほか', '以降', '選手', '俳優', '女優', '芸人',
        '声優', 'モデル', 'アイドル', 'メンバー', 'グループ', '監督', '主演',
        '日本', '日本人', '番組', 'テレビ', 'ドラマ', '映画', '作品', '名前',
        'さん', '男性', '女性', '一つ', '一つ', '氏名', '関係', '存在', '世界',
        '全国', '歴史', '時代', '今日', '連続', '以上', '以下', '約', '程度',
        '数', '人', '名', '回', '月', '日', '年',
        'する', 'いる', 'ある', 'なる', 'ない', 'よい', 'できる', 'ない', 'いう',
        '行う', '行う', '行う', 'おこなう', '持つ', '行く',
        '男女', 'それぞれ', '一部', '全体', '場合', '多く', '多数', '中心',
        '当時', '一方', '他', '影響', '人気', 'ファン', '評価', 'デビュー',
        '出演', '活動', '結成', '所属', '参加', '発表', '発売', '公開',
        '優勝', '受賞', '選出', '就任', '引退', '死去', '結婚', '誕生',
        '出身', '卒業', '在住', '在学', '地方', '問題', '理由', '意味',
        '最初', '最後', '方法', '結果', '種類', '名前', '愛称', '本人',
        '彼', '彼女', '私', '的', 'ため', '人', '名', '回', '月', '日', '年', '万', '円',
        '平成', '昭和', '大正', '明治', '東京', '大阪', '京都', 'アメリカ', 'イギリス',
        'フリー', '公式', '公式サイト'
    }

    for token in tokens: # トークンごとに処理
        pos_parts = token.part_of_speech.split(',') # 品詞分割
        pos_tuple = (pos_parts[0], pos_parts[1]) # 品詞タプル化
        
        if pos_tuple in TARGET_POS_TYPES: # 対象品詞チェック
            if pos_parts[0] in ('形容詞', '動詞'): # 形容詞・動詞は基本形を使用
                word = token.base_form # 基本形
            else: # 名詞は表層形
                word = token.surface # 表層形
            
            # word が STOP_WORDS に含まれていないかチェック
            if len(word) > 1 and word not in STOP_WORDS: # 除外単語チェック
                prefix = TARGET_POS_TYPES[pos_tuple] # プレフィックス取得
                features[f"{prefix}{word}"] = 1 # 特徴として追加
    
    # 『作品名』の抽出
    if summary:
        # 『』の中身をすべて抽出
        work_titles = re.findall(r'『(.*?)』', summary)
        
        # 除外したい一般的な単語
        IGNORE_TITLES = {
            "日本", "世界", "現在", "公式", "一覧", "映画", "ドラマ", "漫画", "小説",
            "アルバム", "シングル", "楽曲", "放送", "番組", "受賞", "概要", "本人",
            "プロフィール", "経歴", "人物", "来歴", "出演", "作品", "歴史", "文化"
        }

        for title in work_titles:
            # 記号などが含まれる長い文は除外（タイトルらしくないため）
            if len(title) < 2 or len(title) > 20 or "," in title or "。" in title:
                continue
            
            # 除外リストに含まれていなければ特徴に追加
            if title not in IGNORE_TITLES:
                features[f"work_{title}"] = 1

    if not features and summary: # summaryがある場合のみログ出力
        print(f"[DEBUG-DYNAMIC] Summaryは存在しましたが、抽出された動的特徴は0個でした。(Summary: {summary[:50]}...)")
            
    return features


# -----------------------
# summaryから【キーワードベース（静的）】で特徴を抽出 
# （こちらは元の関数名 extract_features_from_summary のまま)
# -----------------------
FEATURE_KEYWORDS = {
    "taiga": ["大河ドラマ", "大河"], "tokusatsu": ["仮面ライダー", "スーパー戦隊", "ウルトラマン", "特撮"],
    "romance_drama": ["恋愛", "ラブストーリー", "恋人"], "movie": ["映画", "劇場版"],
    "action": ["アクション", "殺陣", "アクション俳優"], "seiyuu": ["声優", "アニメで声"],
    "singer": ["歌手", "シンガー", "ボーカル"], "stage": ["舞台", "ミュージカル", "劇団"],
    "model": ["モデル", "ファッションモデル"], "comedian": ["お笑い", "芸人", "コント"],
    "anime": ["アニメ"], "hollywood": ["ハリウッド", "海外映画"],
    "idol": ["アイドル", "グループ"], "award": ["受賞", "賞を受賞", "主演男優賞", "最優秀"],
    "nhk": ["NHK", "連続テレビ小説", "朝ドラ"], "youtuber": ["YouTube", "チャンネル"],
    "director": ["監督"], "athlete": ["選手", "オリンピック", "サッカー", "野球", "柔道", "レスリング"],
    "politician": ["政治家", "衆議院", "参議院", "首相"], "mc": ["司会", "MC", "司会者"],
    "radio": ["ラジオ", "パーソナリティ"], "cm": ["CM", "コマーシャル"],
    "married": ["結婚", "妻", "夫"], "author": ["執筆", "出版", "著書", "エッセイ"],
}

# -----------------------
# summaryから【キーワードベース（静的）】で特徴を抽出
# -----------------------
def extract_features_from_summary(summary):
    s = summary or "" # summaryがNoneの場合は空文字に
    features = {} # 抽出特徴辞書
    for k, keywords in FEATURE_KEYWORDS.items(): # キーワードチェック
        features[k] = int(any(kw in s for kw in keywords)) # キーワードがあれば1
    
    m = re.search(r'(\d{4})年', s) # 生年抽出
    if m:
        try: features["birth_year"] = int(m.group(1)) # 生年を整数で保存
        except: pass # 整数変換失敗は無視
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1 # 生存フラグ

    # グループ活動の判定
    GROUP_KEYWORDS = ["グループ", "ユニット", "コンビ", "トリオ", "バンド", "メンバー", "結成", "解散", "加入", "脱退"]
    features["is_group_member"] = int(any(kw in s for kw in GROUP_KEYWORDS))

    # 有名事務所・劇団の判定
    FAMOUS_OFFICES = {
        "office_yoshimoto": ["吉本興業", "よしもと"],
        "office_johnnys": ["ジャニーズ", "SMILE-UP", "スマイルアップ", "STARTO", "光GENJI", "SMAP", "嵐", "King & Prince", "Snow Man", "SixTONES"],
        "office_horipro": ["ホリプロ"],
        "office_oscar": ["オスカープロモーション", "オスカー"],
        "office_amuse": ["アミューズ"],
        "office_stardust": ["スターダストプロモーション", "スターダスト"],
        "office_kenon": ["研音"],
        "office_burning": ["バーニング"],
        "office_ota": ["太田プロ", "太田プロダクション"],
        "office_ldh": ["LDH", "EXILE", "三代目"],
        "office_shiki": ["劇団四季"],
        "office_takarazuka": ["宝塚歌劇団", "宝塚", "娘役", "男役"],
        "office_akb": ["AKB", "乃木坂", "櫻坂", "欅坂", "日向坂", "SKE", "NMB", "HKT", "秋元康"],
    }

    for key, keywords in FAMOUS_OFFICES.items(): # 事務所ごとに判定
        features[key] = int(any(kw in s for kw in keywords)) # キーワードがあれば1

    return features # 抽出特徴辞書返す

# -----------------------
# ユーティリティ: 人物リスト読み込み
# -----------------------
def load_people_list(people_list_path=PEOPLE_LIST_FILE):
    # 人物リストを読み込む
    if not os.path.exists(people_list_path): return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f: data = json.load(f) # JSON読み込み
        if isinstance(data, dict): return data.get("people") # 辞書形式なら "people" キーを返す
        elif isinstance(data, list): return data # リスト形式ならそのまま返す
        return None # 不明な形式
    except Exception: return None # エラー時はNone返す


# -----------------------
# Step2: データセット構築（並列）
# -----------------------
def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                           limit=None, max_workers=30, sleep=0.1): #max_workers（並列数）を小さくすればエラーを防げる
    
    # 人物リスト読み込み
    people = load_people_list(people_list_path)
    if people is None:
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None
    if JANOME_TOKENIZER is None:
        print("Janomeが読み込まれていないため、データ構築をスキップします。")
        return None
    existing = {} # 既存データ読み込み
    if os.path.exists(dataset_path): # 既存データがあれば読み込み
        try:
            with open(dataset_path, "r", encoding="utf-8") as f: # JSON読み込み
                existing = {p["name"]: p for p in json.load(f)} # 辞書化
                print(f"{len(existing)} 件の既存データを読み込みました。未処理のみ並列処理します。") # 既存データ数表示
        except Exception as e:
            print(f"既存データ読み込み失敗: {e}") # エラー表示
            existing = {} # 既存データリセット
    targets = people # 処理対象リスト
    if limit is not None: # 制限があれば切り詰め
        targets = targets[:limit] # 切り詰め
    targets_to_process = [n for n in targets if n not in existing or not existing[n].get("features")] # 未処理のみ
    print(f"データセット総件数: {len(targets)} 件中、処理対象: {len(targets_to_process)} 件") # 対象数表示


    # スレッドで個別処理
    def process_person(name):
        try:
            wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja") # WikipediaAPIインスタンス
            page = wiki.page(name) # ページ取得
            if not page.exists(): # ページが存在しない場合、検索して最良候補を取得
                search_results = wiki.search(name) # 検索
                if search_results:
                    best_match = search_results[0] # 最良候補
                    page = wiki.page(best_match) # 最良候補ページ取得
                else:
                    return {"name": name, "error": "ページなし"} # ページなしエラー返す

            # page.summary の取得状況をログに出す
            if not page.summary: # summaryが空の場合のログ
                print(f"  [DEBUG-PROCESS] {name}: page.summary が空です。")
            # else:
                # 成功ログは大量に出すぎるためコメントアウト
                # print(f"  [DEBUG-PROCESS] {name}: page.summary 取得成功 (長さ: {len(page.summary)})")

            # --- 基本情報 ---
            rec = {"name": name, "summary": page.summary, "features": None, "wikidata": None}
            
            # 1. キーワードベース（静的）の特徴抽出
            features = extract_features_from_summary(page.summary)

            summary = clean_text(page.summary) # テキストクリーンアップ

            # 2. Janome（動的）の特徴を抽出し、featuresにマージする
            dynamic_features = extract_dynamic_features_from_summary(page.summary)
            
            # 動的特徴が空だった場合のログ
            if not dynamic_features and page.summary:
                # summaryはあったのに、Janomeが特徴を返さなかった場合
                print(f"  [DEBUG-PROCESS] {name}: Summaryはありましたが、動的特徴は0個でした。")

            # 動的特徴をマージ
            if dynamic_features:
                features.update(dynamic_features) # featuresにマージ
            
            # --- カテゴリ特徴 ---
            try:
                page_categories = page.categories # カテゴリ取得
                # 無視するカテゴリ (広すぎる、ノイズになる)
                IGNORE_CATS_KEYWORDS = {
                    "存命人物", "死去した人物", "日本の人物", "曖昧さ回避", 
                    "リダイレクト", "人物", "生年", "没年", "年没", "年生",
                    "世紀没", "世紀生", "各年の音楽", "各年のスポーツ",
                    "ウィキデータ", "ID", "記事", "テンプレート", "出典",
                    "外部リンク", "カテゴリ", "リンク", "英語版ウィキ",
                    "日本語版ウィキ", "ウィキペディア", "ウィキメディア・コモンズ",
                    "スタブ", "項目", "一覧", "一覧記事", "記事一覧", "ポータル",
                    "参考文献", "脚注", "注釈", "引用", "プロジェクト", "編集"
                }
                
                for cat_title in page_categories.keys(): # 各カテゴリ処理
                    # 'Category:日本の俳優' -> '日本の俳優'
                    cat_name = cat_title.replace("Category:", "").strip() # カテゴリ名抽出
                    
                    # (キーワードのどれか一つでもカテゴリ名に含まれていたら無視)
                    if any(keyword in cat_name for keyword in IGNORE_CATS_KEYWORDS):
                         continue
                    
                    # 無視リストにあるか、"〇〇年生" "〇〇年没" 形式は無視
                    if cat_name in IGNORE_CATS_KEYWORDS or cat_name.endswith("年生") or cat_name.endswith("年没"):
                         continue
                         
                    # 特徴として追加 (例: cat_日本の俳優)
                    features[f"cat_{cat_name}"] = 1 # カテゴリ特徴として追加
                    
            except Exception as e: # カテゴリ取得失敗時のログ
                print(f"  [DEBUG-PROCESS] {name}: カテゴリ取得失敗. error='{e}'")


            # --- 名前構造 ---
            if re.search(r'[ァ-ヶ]', name): # カタカナ文字が含まれるか
                features["has_katakana"] = 1 # カタカナありフラグ
            if re.fullmatch(r'[ぁ-ん]+', name): # 名前がひらがなのみか
                features["is_hiragana_only"] = 1 # ひらがなのみフラグ
            rec["features"] = features # 特徴セット保存

            # --- Wikidata取得 ---
            wikibase_id = get_wikibase_item_from_wikipedia(name) # Wikibase ID取得
            if wikibase_id: # Wikibase IDがあればWikidata取得
                wd = fetch_wikidata_entity(wikibase_id) # Wikidata取得
                rec["wikidata"] = wd # Wikidata保存
                if wd: # Wikidataが取得できたら追加特徴抽出

                    # (性別・年齢・職業・出身地などの処理)
                    g = wd.get("gender_qid") # 性別QID

                    if g == "Q6581097": features["gender"] = "male" # 男性
                    elif g == "Q6581072": features["gender"] = "female" # 女性

                    birth_time = wd.get("birth_time") # 生年月日
                    current_year = datetime.now().year # 現在の西暦年
                    if birth_time: # 生年月日があれば年齢関連特徴を追加
                        try:
                            birth_year = int(birth_time.strip("+-").split("-")[0]) # 西暦年抽出
                            age = current_year - birth_year # 年齢計算
                            if 20 <= age < 30: features["age_20s"] = 1 # 20代
                            if 30 <= age < 40: features["age_30s"] = 1 # 30代
                            if 40 <= age < 50: features["age_40s"] = 1 # 40代
                            if 50 <= age < 60: features["age_50s"] = 1 # 50代
                            if 1980 <= birth_year <= 1989: features["born_1980s"] = 1 # 1980年代生まれ
                            if 1990 <= birth_year <= 1999: features["born_1990s"] = 1 # 1990年代生まれ
                            if 2000 <= birth_year <= 2009: features["born_2000s"] = 1 # 2000年代生まれ
                        except Exception as e:
                            print(f"  [DEBUG] {name}: birth_time パース失敗. data='{birth_time}', error='{e}'") # ログ出力
                            pass # 整数変換失敗は無視

                    if wd.get("death_time"): # 死亡年月日があれば20世紀死亡フラグを追加
                        try:
                            death_year = int(wd["death_time"].strip("+-").split("-")[0]) # 西暦年抽出
                            if 1900 <= death_year <= 1999: features["died_20c"] = 1 # 20世紀死亡
                        except: pass

                    # P1853 (血液型)
                    if "P1853" in wd: # ※ wd は claims ではなく entity["claims"] を参照する wd です
                        try:
                            # ( fetch_wikidata_entity で wd["claims"] を取得しているので wd を使う)
                            v_id = wd.get("claims", {}).get("P1853", [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                            if v_id == "Q170138": features["blood_A"] = 1 # A型
                            if v_id == "Q170162": features["blood_B"] = 1 # B型
                            if v_id == "Q170196": features["blood_O"] = 1 # O型
                            if v_id == "Q170094": features["blood_AB"] = 1 # AB型
                        except: pass

                    # P27 (国籍) (日本(Q17)以外があるか)
                    if "P27" in wd:
                        try:
                            claims_P27 = wd.get("claims", {}).get("P27", [])
                            if any(c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") != "Q17" for c in claims_P27):
                                features["not_japanese_only"] = 1 # 日本国籍以外も持つ
                        except: pass
                        
                    # P22, P25, P26, P40 (家族に有名人)
                    family_keys = ["P22", "P25", "P26", "P40"]
                    if any(k in wd.get("claims", {}) for k in family_keys):
                        features["has_family_info"] = 1 

                    # P101 (活動分野)
                    if "P101" in wd:
                        field_qids = []
                        claims_P101 = wd.get("claims", {}).get("P101", [])
                        for c in claims_P101:
                            try:
                                v_id = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                                field_qids.append(v_id)
                            except: pass
                        if "Q11631" in field_qids: features["field_literature"] = 1 # 文学
                        if "Q483" in field_qids: features["field_music"] = 1 # 音楽
                        if "Q1104" in field_qids: features["field_science"] = 1 # 科学
                        
                    occ_qs = wd.get("occupation_qids", []) # 職業QIDリスト
                    if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]): features["actor_wikidata"] = 1 # 俳優
                    if any(q in occ_qs for q in ["Q177220", "Q639669", "Q10800557"]): features["singer_wikidata"] = 1 # 歌手

                    if "Q82955" in occ_qs: features["politician_wikidata"] = 1 # 政治家

                    place_qid = wd.get("birth_place_qid") # 出身地QID
                    TOKYO_QIDS = {"Q1490", "Q1228", "Q11103005", "Q200000", "Q200072"} # 東京関連QID
                    KANSAI_QIDS = {"Q172582", "Q16997", "Q486245", "Q132640", "Q132643"} # 関西関連QID
                    if place_qid in TOKYO_QIDS: features["from_tokyo"] = 1 # 東京出身
                    elif place_qid in KANSAI_QIDS: features["from_kansai"] = 1 # 関西出身

                    edu_qids = wd.get("education_qids", []) # 教育機関QIDリスト
                    if "Q7981" in edu_qids: features["grad_todai"] = 1 # 東大卒
                    elif "Q174019" in edu_qids: features["grad_waseda"] = 1 # 早大卒
                    elif "Q302302" in edu_qids: features["grad_keio"] = 1 # 慶応卒

                    # P166 (受賞) の拡充
                    award_qids = wd.get("award_qids", []) 
                    if "Q1138032" in award_qids: features["award_shiju"] = 1 # 紫綬褒章
                    if "Q1085422" in award_qids: features["award_academy_jp"] = 1 # 日本アカデミー賞
                    if "Q192200" in award_qids: features["award_blue_ribbon"] = 1 # ブルーリボン賞

            return rec # 正常終了返す

        except Exception as e: # 致命的なエラー処理
            print(f"[警告] {name} の解析中にエラーが発生しました: {e}")
            # tracebackを出したい場合（任意）
            # traceback.print_exc()
            # エラーの時でも処理を止めずに、空データを返す
            return {"name": name, "error": str(e), "features": []} # エラー情報を返す

    # 並列処理開始
    new_records = [] # 新規取得レコードリスト
    processed_count = 0 # 処理済みカウンタ
    total_to_process = len(targets_to_process) # 総処理対象数
    if total_to_process == 0:
        print("処理対象の人物がいません。データセットは最新です。") # スキップ
        return list(existing.values()) # 既存データ返す
    with ThreadPoolExecutor(max_workers=max_workers) as executor: # スレッドプール
        future_to_name = {executor.submit(process_person, name): name for name in targets_to_process} # 未来オブジェクトマップ
        for future in as_completed(future_to_name): # 完了待ち
            name = future_to_name[future] # 名前取得
            processed_count += 1 # カウンタ更新
            try:
                rec = future.result() # 結果取得
                new_records.append(rec) # 新規レコード追加
                if "error" in rec: # エラー表示
                    print(f"[{processed_count}/{total_to_process}] × {name}: {rec['error']}") # エラー表示
                else:
                    print(f"[{processed_count}/{total_to_process}] ✓ {name}") # 成功表示
            except Exception as e: # 例外処理
                print(f"[{processed_count}/{total_to_process}] ⚠ {name}: {e}") # 例外表示
            time.sleep(sleep) # API負荷軽減
    merged_data = existing.copy() # 既存データコピー
    for rec in new_records: # 新規レコードマージ
        merged_data[rec["name"]] = rec # マージ
    final_dataset = list(merged_data.values()) # 最終データセットリスト化
    with open(dataset_path, "w", encoding="utf-8") as f: # JSON保存
        json.dump(final_dataset, f, ensure_ascii=False, indent=2) # 保存
    print(f"データセットを保存しました: {dataset_path}（合計 {len(final_dataset)} 件）") # 保存完了表示
    return final_dataset # 最終データセット返す


# -----------------------
# Step3: アキネーター本体 データセット読み込み
# -----------------------
def load_dataset(dataset_path=DATASET_FILE, min_feature_threshold=10):
    """
    データセットを読み込む。
    [改変] features の数が min_feature_threshold 未満の人物を除外する。
    """
    if not os.path.exists(dataset_path): # データセットファイル存在チェック
        print("データセットが見つかりません。まず build_dataset_parallel を実行してください。")
        return None
    try:
        with open(dataset_path, "r", encoding="utf-8") as f: # JSON読み込み
            data = json.load(f) # データセット読み込み
            
            valid_data = [d for d in data if d.get("features")] # featuresがあるデータのみ
            
            # features の数が閾値以上のデータのみ抽出
            filtered_data = [
                d for d in valid_data
                if len(d.get("features", {})) >= min_feature_threshold # 閾値チェック
            ]
            
            print(f"データセット読み込み: {len(data)}件中、有効データ {len(valid_data)}件") # 読み込みログ
            
            # デバッグログ
            print(f"--- load_dataset デバッグ ---")
            print(f"有効データ（featuresあり）: {len(valid_data)} 人") # 有効データ数表示
            print(f"閾値 ({min_feature_threshold}個) を超えたデータ: {len(filtered_data)} 人") # 閾値超えデータ数表示
            print(f"除外されたデータ: {len(valid_data) - len(filtered_data)} 人") # 除外データ数表示
            print(f"--------------------------")
            
            if len(filtered_data) == 0: # フィルタ後にデータがない場合の警告
                print("エラー: 閾値が厳しすぎるか、有効なデータがありません。")
                return None
                
            return filtered_data # フィルタ後のデータセット返す
            
    except Exception as e:
        print(f"データセットの読み込みに失敗しました: {e}")
        return None

# -----------------------
# 質問マップの自動生成 (Janome動的質問＋閾値緩和)
# -----------------------
def generate_question_map(dataset, selected_categories=None):
    qm = {"occupation": [], "activity": [], "feature": [], "common": []} # 質問マップ初期化
    added_keys = set() # 追加済み特徴キーセット

    # --- 重みの定義 ---
    WEIGHT_URGENT = 1000 # 生死
    WEIGHT_HIGH   = 500  # 年代、大まかな職業
    WEIGHT_MID    = 100  # 事務所、出身地、血液型
    WEIGHT_LOW    = 50   # 具体的な作品名
    WEIGHT_MIN    = 10   # 細かいキーワード

    # --- 1. 共通質問 (Wikidata由来 + 日付 + 名前) ---
    common_questions_def = [
        # [最優先]
        ("alive_text", "現在もご存命ですか？", "common", WEIGHT_URGENT),

        # [優先]
        ("age_20s", "現在、20代ですか？", "common", WEIGHT_HIGH), 
        ("age_30s", "現在、30代ですか？", "common", WEIGHT_HIGH),
        ("age_40s", "現在、40代ですか？", "common", WEIGHT_HIGH), 
        ("age_50s", "現在、50代ですか？", "common", WEIGHT_HIGH),
        ("born_1980s", "1980年代生まれですか？", "common", WEIGHT_HIGH), 
        ("born_1990s", "1990年代生まれですか？", "common", WEIGHT_HIGH),
        ("born_2000s", "2000年代生まれですか？", "common", WEIGHT_HIGH),
        
        ("actor_wikidata", "俳優ですか？", "occupation", WEIGHT_HIGH),
        ("singer_wikidata", "歌手ですか？", "occupation", WEIGHT_HIGH),
        ("politician_wikidata", "政治家ですか？", "occupation", WEIGHT_HIGH),
        ("field_literature", "主な活動分野は「文学」ですか？", "occupation", WEIGHT_HIGH),
        ("field_music", "主な活動分野は「音楽」ですか？", "occupation", WEIGHT_HIGH),
        ("field_science", "主な活動分野は「科学」ですか？", "occupation", WEIGHT_HIGH),

        # [普通]
        ("died_20c", "20世紀（1900年代）に亡くなりましたか？", "common", WEIGHT_MID),
        ("has_katakana", "名前にカタカナが含まれていますか？", "common", WEIGHT_MID),
        ("is_hiragana_only", "名前はひらがなだけですか？", "common", WEIGHT_MID),
        ("from_tokyo", "出身は東京ですか？", "feature", WEIGHT_MID),
        ("from_kansai", "出身は関西（大阪・京都・兵庫）ですか？", "feature", WEIGHT_MID),
        ("blood_A", "血液型はA型ですか？", "feature", WEIGHT_MID),
        ("blood_B", "血液型はB型ですか？", "feature", WEIGHT_MID),
        ("blood_O", "血液型はO型ですか？", "feature", WEIGHT_MID),
        ("blood_AB", "血液型はAB型ですか？", "feature", WEIGHT_MID),
        ("not_japanese_only", "日本以外の国籍（ルーツ）を持っていますか？", "feature", WEIGHT_MID),
        ("has_family_info", "家族（親・配偶者・子供）にも有名人がいますか？", "feature", WEIGHT_MID),
        
        # [低め]
        ("grad_todai", "東京大学を卒業していますか？", "feature", WEIGHT_LOW),
        ("grad_waseda", "早稲田大学を卒業していますか？", "feature", WEIGHT_LOW),
        ("grad_keio", "慶應義塾大学を卒業していますか？", "feature", WEIGHT_LOW),
        ("award_shiju", "紫綬褒章を受章していますか？", "feature", WEIGHT_LOW),
        ("award_academy_jp", "日本アカデミー賞を受賞したことがありますか？", "feature", WEIGHT_LOW),
        ("award_blue_ribbon", "ブルーリボン賞を受賞したことがありますか？", "feature", WEIGHT_LOW),
        
        # [追加分]
        ("is_group_member", "グループやユニットの一員として活動していますか（いましたか）？", "activity", WEIGHT_MID),
        ("office_yoshimoto", "吉本興業に所属していますか？", "feature", WEIGHT_MID),
        ("office_johnnys", "SMILE-UP.（旧ジャニーズ）やSTARTOに関連するアイドルですか？", "feature", WEIGHT_MID),
        ("office_horipro", "ホリプロに所属していますか？", "feature", WEIGHT_MID),
        ("office_oscar", "オスカープロモーションに所属していますか？", "feature", WEIGHT_MID),
        ("office_amuse", "アミューズに所属していますか？", "feature", WEIGHT_MID),
        ("office_stardust", "スターダストプロモーションに所属していますか？", "feature", WEIGHT_MID),
        ("office_ota", "太田プロダクションに所属していますか？", "feature", WEIGHT_MID),
        ("office_ldh", "LDH（EXILE TRIBEなど）に関連していますか？", "feature", WEIGHT_MID),
        ("office_shiki", "劇団四季に関連していますか？", "feature", WEIGHT_MID),
        ("office_takarazuka", "宝塚歌劇団に関連していますか？", "feature", WEIGHT_MID),
        ("office_akb", "AKB48グループや坂道シリーズに関連していますか？", "feature", WEIGHT_MID),
    ]

    # 共通質問を追加
    for key, text, category in common_questions_def:
        key_exists = any(key in rec.get("features", {}) for rec in dataset) # キー存在チェック
        if key_exists and key not in added_keys: # 未追加なら追加
            # 質問マップに追加
            qm[category].append({
                "key": key,                                    # キー
                "text": text,                                  # 質問テキスト
                "check": lambda rec,                           # チェック関数
                k=key: rec.get("features",{}).get(k) == 1      # 特徴が1かどうか
            })
            added_keys.add(key) # 追加済みセットに登録

    # --- 2. FEATURE_KEYWORDS に基づく質問 (Summary由来) ---
    feature_questions_def = {
        "comedian": ("お笑い芸人ですか？", "occupation", WEIGHT_HIGH),
        "seiyuu": ("声優として活動していますか？", "occupation", WEIGHT_HIGH),
        "athlete": ("スポーツ選手ですか？", "occupation", WEIGHT_HIGH),
        "model": ("モデルとして活動していますか？", "occupation", WEIGHT_HIGH),
        "idol": ("アイドル活動をしていましたか（していますか）？", "occupation", WEIGHT_HIGH),
        "youtuber": ("YouTuberとして活動していますか？", "occupation", WEIGHT_HIGH),
        "director": ("監督（映画やアニメなど）ですか？", "occupation", WEIGHT_HIGH),
        "taiga": ("大河ドラマに出演しましたか？", "activity", WEIGHT_MID),
        "tokusatsu": ("特撮作品（仮面ライダーなど）に出演しましたか？", "activity", WEIGHT_MID),
        "romance_drama": ("恋愛ドラマに出演しましたか？", "activity", WEIGHT_LOW),
        "movie": ("映画に出演していますか？", "activity", WEIGHT_MID),
        "action": ("アクション作品に出演していますか？", "activity", WEIGHT_LOW),
        "stage": ("舞台（演劇・ミュージカル）に出演していますか？", "activity", WEIGHT_MID),
        "anime": ("アニメ作品に関わっていますか？", "activity", WEIGHT_MID),
        "hollywood": ("海外（ハリウッド等）の作品に出演していますか？", "activity", WEIGHT_MID),
        "nhk": ("NHK（朝ドラなど）に出演したことがありますか？", "activity", WEIGHT_MID),
        "award": ("（演技賞や作品賞など）を受賞したことがありますか？", "feature", WEIGHT_MID),
        "mc": ("司会者（MC）として有名ですか？", "activity", WEIGHT_MID),
        "radio": ("ラジオ番組を持っていますか（いましたか）？", "activity", WEIGHT_LOW),
        "cm": ("CMに多く出演していますか？", "activity", WEIGHT_LOW),
        "married": ("結婚していることを公表していますか？", "feature", WEIGHT_MID),
        "author": ("本（エッセイなど）を出版したことがありますか？", "feature", WEIGHT_LOW),
    }

    # 仕事カテゴリに基づくフィルタリングマップ
    CATEGORY_TO_FEATURE_MAP = {
        "日本の俳優": ["taiga", "tokusatsu", "movie", "action", "stage", "nhk", "award", "cm", "married"],
        "日本の女優": ["taiga", "romance_drama", "movie", "stage", "nhk", "award", "model", "cm", "married"],
        "お笑い芸人": ["comedian", "youtuber", "movie", "stage", "mc", "radio", "married"],
    }
    
    # フィルタリングされた特徴キーを決定
    allowed_feature_keys = set()
    # フィルタリング
    if not selected_categories or len(selected_categories) == len(CATEGORIES): # 全カテゴリ選択時
        allowed_feature_keys = set(feature_questions_def.keys()) # 全特徴キー許可
    else: 
        for cat in selected_categories: # 選択カテゴリごとに許可キーを追加
            allowed_feature_keys.update(CATEGORY_TO_FEATURE_MAP.get(cat, [])) # キー追加

    # 質問マップに追加
    for key in allowed_feature_keys: 
        if key in feature_questions_def and key not in added_keys: # 定義済みかつ未追加なら
            text, category = feature_questions_def[key] # テキストとカテゴリ取得
            if any(key in rec.get("features", {}) for rec in dataset): # キー存在チェック
                # 質問マップに追加
                qm[category].append({
                    "key": key, "text": text,
                    "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
                })
                # 追加済みセットに登録
                added_keys.add(key)
        
    # データセットから動的キーを読み込み、質問を生成する

    print("データセットをスキャンして、動的な質問（名詞・形容詞・動詞・カテゴリ）を生成します...")
    all_dynamic_keys = set() # すべての動的特徴キーセット
    DYNAMIC_PREFIXES = ("noun_", "adj_", "verb_", "cat_", "work_") # 動的特徴のプレフィックス
    
    # データセットスキャン
    for rec in dataset:
        if not rec.get("features"): continue # featuresがない場合スキップ
        for key in rec["features"].keys(): # 特徴キーごとに
            if key.startswith(DYNAMIC_PREFIXES): # 動的特徴プレフィックスチェック
                all_dynamic_keys.add(key) # 動的特徴キーセットに追加
    
    print(f"   → {len(all_dynamic_keys)} 種類のユニークな動的特徴を発見しました。") # 発見数ログ

    # フィルタリング
    total_people = len(dataset) # 総人物数
    min_count = max(3, int(total_people * 0.002))  # 最低0.2%または3人
    max_count = int(total_people * 0.90) # 最高90%
    
    useful_dynamic_keys = set() # 有用な動的特徴キーセット
    for key in all_dynamic_keys: # 動的特徴キーごとに
        count = sum(1 for rec in dataset if rec.get("features", {}).get(key) == 1) # 出現カウント
        if min_count <= count <= max_count: # 閾値チェック
            useful_dynamic_keys.add(key) # 有用セットに追加

    print(f"   → フィルタリング後、有用な質問を {len(useful_dynamic_keys)} 件、質問マスターリストに追加します。")

    PREFECTURES = {
        "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島",
        "茨城", "栃木", "群馬", "埼玉", "千葉", "東京", "神奈川",
        "新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜",
        "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫",
        "奈良", "和歌山", "鳥取", "島根", "岡山", "広島", "山口",
        "徳島", "香川", "愛媛", "高知", "福岡", "佐賀", "長崎",
        "熊本", "大分", "宮崎", "鹿児島", "沖縄"
    }

    for key in useful_dynamic_keys: # 有用な動的特徴キーごとに
        if key in added_keys: continue # 既に追加済みならスキップ
        
        question_text = "" # 質問テキスト初期化
        category_type = "activity" # デフォルトカテゴリ
        weight = WEIGHT_MIN # デフォルトは最低ランク
        
        try:
            # カテゴリ (cat_) の質問生成
            if key.startswith("cat_"): # カテゴリ質問
                cat_name = key[len("cat_"):] # カテゴリ名部分抽出
                
                if cat_name.endswith("出身の人物"): # 出身地カテゴリ
                    place = cat_name.replace("出身の人物", "") # 地名部分抽出
                    if place in PREFECTURES: continue # 都道府県名はスキップ（名詞質問で対応）
                    question_text = f"『{place}』の出身ですか？" # 出身地質問
                    category_type = "feature" # 特徴カテゴリに変更
                    weight = WEIGHT_MID # 重み中
                elif cat_name.endswith("所属者"): # 所属カテゴリ
                    group = cat_name.replace("所属者", "") # グループ名部分抽出
                    question_text = f"『{group}』に所属していますか（しましたか）？" # 所属質問
                    category_type = "feature" # 特徴カテゴリに変更
                    weight = WEIGHT_MID # 重み中
                elif cat_name.endswith("関連の人物"): # 関連人物カテゴリ
                    topic = cat_name.replace("関連の人物", "") # トピック部分抽出
                    question_text = f"『{topic}』に関連する人物ですか？" # 関連質問
                elif cat_name.endswith("の受賞者"): # 受賞者カテゴリ
                    award = cat_name.replace("の受賞者", "") # 賞名部分抽出
                    question_text = f"『{award}』を受賞していますか？" # 受賞質問
                    category_type = "feature" # 特徴カテゴリに変更
                    weight = WEIGHT_LOW # 重み低
                else: # その他のカテゴリ
                    question_text = f"「{cat_name}」というカテゴリに分類されますか？"

            # 名詞 (noun_) の質問生成
            if key.startswith("noun_"): # 名詞質問 
                word = key[len("noun_"):] # 名詞部分抽出
                
                # 単語の性質を推測して質問文を生成
                if word in ["北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島",
                            "茨城", "栃木", "群馬", "埼玉", "千葉", "東京", "神奈川",
                            "新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜",
                            "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫",
                            "奈良", "和歌山", "鳥取", "島根", "岡山", "広島", "山口",
                            "徳島", "香川", "愛媛", "高知", "福岡", "佐賀", "長崎",
                            "熊本", "大分", "宮崎", "鹿児島", "沖縄"]: # 日本の都道府県
                    question_text = f"『{word}』出身、または縁がありますか？"
                    category_type = "feature"
                    weight = WEIGHT_MID # 重み中
                elif word.endswith("大学"):
                    question_text = f"『{word}』を卒業していますか？"
                    category_type = "feature"
                    weight = WEIGHT_LOW # 重み低
                elif word.endswith("賞"):
                    question_text = f"『{word}』を受賞していますか？"
                    category_type = "feature"
                    weight = WEIGHT_LOW # 重み低
                elif word.endswith("（"): # "タモリ（森田一義）" のような表記を避ける
                    continue
                elif len(word) <= 4 and (re.fullmatch(r'[A-Z]+', word) or re.fullmatch(r'[A-Z][a-z]+', word)): # 英字略語
                    question_text = f"『{word}』というグループ／作品に関連しますか？"
                elif word.endswith("者") or word.endswith("家") or word.endswith("選手"):
                    question_text = f"『{word}』としての側面も持っていますか？"
                    category_type = "occupation" # 職業カテゴリに変更
                    weight = WEIGHT_MID # 重み中
                else:
                    # デフォルトの名詞質問
                    question_text = f"『{word}』というキーワードに関連しますか？"

            # 形容詞 (adj_) の質問生成
            elif key.startswith("adj_"):
                adj = key[len("adj_"):]
                question_text = f"『{adj}』というイメージ/特徴がありますか？"
                category_type = "feature"

            # 動詞 (verb_) の質問生成
            elif key.startswith("verb_"):
                verb = key[len("verb_"):]
                question_text = f"『{verb}（こと）』を（よく）しますか？"

            # 作品名 (work_) の質問生成
            elif key.startswith("work_"):
                title = key[len("work_"):]
                question_text = f"『{title}』という作品や番組に出演（または関連）していますか？"
                category_type = "activity" # 活動に関する質問
                weight = WEIGHT_LOW

            if question_text: # 質問テキストが生成された場合
                qm[category_type].append({ # カテゴリタイプも反映
                    "key": key, 
                    "text": question_text,
                    "weight": weight,
                    "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
                })
                added_keys.add(key)
        
        except Exception as e: # エラー処理
            print(f"[DEBUG] 動的質問生成エラー: {key} - {e}")
            pass # エラーは無視して続行
            
    # デバッグログ
    total_questions = len(added_keys) # 合計質問数
    print(f"--- generate_question_map デバッグ ---")
    print(f"動的特徴の総数: {len(all_dynamic_keys)} 個")
    print(f"フィルタリング閾値: 最低 {min_count} 人 / 最高 {max_count} 人")
    print(f"フィルタリング後の有用な動的質問数: {len(useful_dynamic_keys)} 個")
    print(f"（手動質問と合わせた合計質問数: {total_questions} 種類）")
    print(f"-----------------------------------")
        
    print(f"質問マスターリストを生成しました (合計 {total_questions} 種類)")
    return qm


# -----------------------
# 最適な質問を見つけるアルゴリズム (質問の厳選)
# -----------------------
def find_best_question(candidates_for_analysis, qm_dict, asked_keys):
    """
    【重要】解析用候補者リスト(candidates_for_analysis)を最も効率よく
    半分(50/50)に分割できる質問を厳選。
    スコアが0の質問も保持し、他にない場合の保険とする。
    職業や性別など、本質的な質問のスコアに「優先度ブースト」をかける。
    """
    best_question = None # 最適な質問
    best_score = -1 # スコアの初期値

    # 分割できない質問 (スコア0) を保持するリスト
    zero_score_questions = []

    # 現在の候補者数を把握
    total_candidates = len(candidates_for_analysis)

    # すべての質問カテゴリをループ
    for category_name, q_category_list in qm_dict.items(): # 質問カテゴリごとに
        
        # 質問カテゴリに応じて優先度を設定
        # --------------------------------------------------
        if category_name in ("common", "occupation"):
            # 「男性ですか」「俳優ですか」などの本質的な質問
            priority_weight = 10.0 # 優先度高
        else:
            # 「月光に関連しますか」「大河ドラマに出ましたか」などの詳細な質問
            priority_weight = 1.0  # 優先度標準
        # --------------------------------------------------

        for question in q_category_list: # 各質問ごとに
            key, test = question.get("key"), question.get("check") # キーとテスト関数取得

            weight = question.get("weight", 10) # 重み取得（未定義なら10）

            if key in asked_keys: # 既に尋ねた質問はスキップ
                continue

            # --- シミュレーション (解析用候補者リストで行う) ---
            yes_count = 0 # はいカウント
            no_count = 0 # いいえカウント
            for c in candidates_for_analysis: # 各候補者ごとに
                if c.get("features") is None: continue # featuresがない場合スキップ
                if test(c): # 質問に「はい」と答える場合
                    yes_count += 1 # はいカウント増加
                else: # 質問に「いいえ」と答える場合
                    no_count += 1 # いいえカウント増加
            
            # スコア計算に優先度ブーストを追加
            if yes_count == 0 or no_count == 0: # 分割できない場合
                score = 0 # 分割できない場合はスコア0
            else: # 分割できる場合
                # (情報利得スコア) * (優先度ブースト)
                score = (yes_count * no_count) * weight # スコア計算
            
            if score > best_score: # 最良スコア更新
                best_score = score # スコア更新
                best_question = question # 最適な質問更新
            
            elif score == 0: # スコア0の質問を保持
                zero_score_questions.append(question) # スコア0質問リストに追加
    
    # 1. 候補者を分割できる「良い質問」 (score > 0) が見つかった場合
    if best_question is not None:
        return best_question # 迷わずその質問を返す

    # 2. 「良い質問」が見つからなかった (best_question is None) 場合
    
    # 2a. 候補者がすでに少ない (5人以下) 場合
    #     スコア0の「悪い質問」をするより、諦めて候補者を提示する方が良い
    if total_candidates <= 5:
        print("[DEBUG] 候補者が5人以下のため、スコア0の質問は行わず、推測を終了します。")
        return None # 諦める

    # 2b. 候補者がまだ多い (6人以上) 場合
    #     最後の手段として、スコア0の質問でもランダムに尋ねる
    if zero_score_questions:
        print("[DEBUG] スコア > 0の質問がありませんでした。スコア0の質問からランダムに選びます。")
        # スコア0の中でも、なるべく重みが大きいものを選ぶ
        zero_score_questions.sort(key=lambda q: q.get("weight", 0), reverse=True)
        # 上位10個からランダム
        top_zeros = zero_score_questions[:10]
        return random.choice(top_zeros)
        
    # 3. 本当に尋ねる質問が何も残っていない場合
    return None # 諦める

# -----------------------
# アキネーター本体ループ (★「戻る」機能のバグを完全修正)
# -----------------------
def akinator_play(dataset, selected_categories=None, max_questions=1000, analysis_size=100):
    """
    候補者が1人になるまで質問を続ける。
    """
    
    current_game_dataset = dataset.copy() # ゲーム用データセットのコピー
    
    # 履歴の初期状態 (質問1 の直前の状態)
    history = [(current_game_dataset.copy(), set(), 0)] 
    # history リストは、常に「次に実行されるべき状態」のタプルを保持する
    # [ (candidates, asked_keys, asked_count), ... ]

    qm_dict = generate_question_map(current_game_dataset, selected_categories) # 質問マップ生成

    # 相互排他グループ定義
    MUTEX_GROUPS = {
        # 年代 (年齢)
        "age": {"age_20s", "age_30s", "age_40s", "age_50s"},
        "born": {"born_1980s", "born_1990s", "born_2000s"},
        # 血液型
        "blood": {"blood_A", "blood_B", "blood_O", "blood_AB"},
        # 性別
        "gender": {"gender_male", "gender_female"},
    }
    # グループキーを高速に逆引きするためのマップ
    KEY_TO_GROUP = {} # key -> group_name
    for group_name, keys in MUTEX_GROUPS.items(): # グループごとに
        for key in keys: # key ごとに
            KEY_TO_GROUP[key] = group_name # 逆引き登録
    
    print(f"=== 🕵️ 人物検索開始 (1人特定/候補者全員・全力分析モード) ===")
    print(f"※ 毎回、残りの候補者全員 ({len(current_game_dataset)}人) を分析して最適な質問を厳選します。")
    print("回答は「はい(y) / いいえ(n) / わからない(u) / 戻る(b)」のいずれかを入力してください。") 
    print("---")
    
    # ループ条件を history の中身で管理する (max_questions は保険)
    loop_count = 0 # ループカウンタ
    while len(history) > 0 and loop_count < max_questions: # 最大質問数制限
        
        loop_count += 1 # 無限ループ防止
        
        # --- 1. 現在の状態を履歴の末尾から取得 ---
        # (これが「今から尋ねる」または「今から判断する」状態)
        current_candidates, current_asked_keys, current_asked_count = history[-1] # 履歴の末尾取得

        # --- 2. 状態のチェック (0人の場合) ---
        if len(current_candidates) == 0: # 0人の場合
            print("\n[!] 候補者がいなくなりました。")
            print("回答が間違っていた可能性があります。")
            
            if len(history) <= 1: # 履歴が1つ以下の場合
                print("履歴がなく、戻れません。終了します。")
                break 

            ans = input("1つ前の質問に戻りますか？ (y/n または b) > ").strip().lower()
            
            if ans in ("y", "b"): # 戻る場合
                history.pop() # [0人] の状態を捨てる
                # ループの最初に戻ると、history[-1] は 0人になる前の状態になる
                continue 
            else: # 終了の場合
                print("終了します。")
                break 
        
        # --- 3. 状態のチェック (1人の場合) ---
        if len(current_candidates) == 1: # 1人の場合
            c = current_candidates[0] # 唯一の候補者
            print(f"\n===============================")
            print(f"🎉 答えが絞り込めました！ ({current_asked_count}回の質問)")
            
            # ★ 画像URL取得機能 (以前追加したものがあればここに復活させます)
            print(f"--- 候補者の画像を取得中: {c['name']} ---")
            image_url = get_wikipedia_main_image(c['name'])
            if image_url:
                print(f"📷 画像URL: {image_url}")
            else:
                print("📷 (画像は見つかりませんでした)")
        
            ans = input(f"**あなたが思い浮かべたのは... 『{c['name']}』** ですか？ (y/n/b) > ").strip().lower()

            if ans in ("y", "yes"):
                print("-------------------------------")
                print("🎉 やはりその方でしたね！お見事です！")
                print("===============================")
                return current_candidates # 勝利
            
            elif ans in ("b", "back"):
                print("--- 1つ前の質問に戻ります ---")
                if len(history) <= 1:
                    print("--- 最初の質問です（これ以上戻れません） ---")
                    continue
                
                history.pop() # [1人] の状態を捨てる
                continue # ループの最初に戻る

            else: # 「いいえ (n)」の場合
                print(f"🤔 違いましたか...。『{c['name']}』を今回の候補から完全に除外します。")
                
                wrong_guess_name = c["name"]
                
                # マスターデータセットから永久除外
                current_game_dataset = [p for p in current_game_dataset if p["name"] != wrong_guess_name]
                
                history.pop() # [1人] の状態を捨てる
                
                if not history: break # 履歴が空になったら終了
                
                # 1つ前の状態（複数候補）を取得し、そこからも除外
                candidates_prev, asked_keys_prev, asked_count_prev = history[-1]
                
                candidates_updated = [p for p in candidates_prev if p["name"] != wrong_guess_name]
                
                # 履歴の末尾（1つ前の状態）を、除外後の状態で「更新」する
                history[-1] = (candidates_updated, asked_keys_prev, asked_count_prev)

                print(f"--- 1つ前の状態 (候補 {len(candidates_updated)}人) に戻り、質問を続けます ---")
                continue 
        
        #--- 4. 質問の選択 (2人以上の場合) ---
        
               
        question = find_best_question(current_candidates, qm_dict, current_asked_keys)
            
        if question is None:
            print("\n質問が尽きるか、残りの候補で質問が分けられなくなりました。残りの候補から推測します...")
            break # 質問が尽きた

        key, q_text, test = question["key"], question["text"], question["check"]
        
        yes_count_analysis = sum(1 for c in current_candidates if test(c))
        no_count_analysis = len(current_candidates) - yes_count_analysis
        
        print(f"\n[質問 {current_asked_count+1}] (候補: {len(current_candidates)}人 | 全員分析の分割予測: {yes_count_analysis} / {no_count_analysis})")
        
        ans = input(q_text + " （y/n/u/b） > ").strip().lower() 
        
        # --- 5. 回答処理 ---
        
        if ans in ("b", "back"):
            if len(history) <= 1:
                print("--- 最初の質問です（これ以上戻れません） ---")
                continue
            
            history.pop() # 現在の状態を捨てる
            # ループの最初に戻ると、history[-1] は1つ前の状態になる
            continue 

        # --- (y/n/u) の場合、次の状態を計算して history に追加 ---
        
        next_candidates = current_candidates.copy()
        next_asked_keys = current_asked_keys.copy()
        next_asked_keys.add(key)
        next_asked_count = current_asked_count + 1

        if ans in ("はい", "y"):
            next_candidates = [c for c in next_candidates if test(c)]

            # 相互排他ロジックの実行)
            if key in KEY_TO_GROUP: # キーが相互排他グループに属している場合
                group_name = KEY_TO_GROUP[key] # グループ名取得
                group_keys = MUTEX_GROUPS[group_name] # グループ内のキーセット取得
                # 自分が「はい」だったので、グループの他のキーは質問済み(ask)扱いにする
                skipped_keys = [] # スキップされたキーリスト
                for other_key in group_keys: # グループ内の各キーごとに
                    if other_key != key and other_key not in next_asked_keys: # 自分以外かつ未質問の場合
                        next_asked_keys.add(other_key) # 質問済み扱いに追加
                        skipped_keys.append(other_key) # スキップリストに追加
                if skipped_keys:
                    print(f"  [INFO] {group_name} グループの他の質問 ({', '.join(skipped_keys)}) をスキップします。")
            # 相互排他ロジック終了
            
        elif ans in ("いいえ", "n"): # 「いいえ」の場合
            next_candidates = [c for c in next_candidates if not test(c)] # 否定フィルタリング
        elif ans in ("わからない", "u"): # 「わからない」の場合
            pass # 候補者は変わらない
        else:
            print("無効な回答です。 y/n/u/b のいずれかを入力してください。")
            continue # ★ 履歴を追加せず、単にループの最初に戻る (質問は再実行される)

        # y/n/u で処理された「次の状態」を履歴に追加
        history.append((next_candidates, next_asked_keys, next_asked_count))
        
        # 候補者数の表示
        if 0 < len(next_candidates) < 10:
             print(f"(現在の候補数: {len(next_candidates)}人 - {', '.join([c['name'] for c in next_candidates])})")
        elif len(next_candidates) > 0:
             print(f"(現在の候補数: {len(next_candidates)}人)")


    # -----------------------------
    # 最終的な提案ロジック (ループが尽きた / 0人になった場合)
    # -----------------------------
    # ★ ループが正常に終了した場合（= breakした）、最終状態を history から取得
    final_candidates, final_asked_count = history[-1][0], history[-1][2]
    
    print("\n===============================")
    
    if len(final_candidates) > 1:
        print(f"🤔 {final_asked_count}回の質問では1人に絞り込めませんでした。")
        print(f"特徴が完全に一致する候補が {len(final_candidates)}人 残りました。")
        print(f"=== 最終候補 ===")
        for i, c in enumerate(final_candidates, 1):
            print(f"{i}. **{c['name']}**")
            
    elif len(final_candidates) == 0:
        print("😢 最終的な候補者が0人になってしまいました。")
        
    print("===============================")
    return final_candidates

# -----------------------
# エントリポイント用関数
# -----------------------
def run_step(step="collect", people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, **kwargs):
    step = step.lower() # 小文字化
    # どのステップでも使う可能性のあるカテゴリリストを取得
    selected_categories = kwargs.get("categories", CATEGORIES) # ※ "categories" が kwargs にないと CATEGORIES になる
    if step == "collect": # データ収集ステップ
        # 収集実行
        return collect_people(categories=selected_categories,               # 選択カテゴリ
                              cmlimit=kwargs.get("cmlimit", 50),            # カテゴリメンバー取得上限
                              depth=kwargs.get("depth", 1),                 # カテゴリ深度
                              sleep=kwargs.get("sleep", 1.5),               # API呼び出し間隔
                              save_path=people_list_path,                   # 渡されたパス
                              corresponding_dataset_path=dataset_path)      # 渡されたパス
    elif step == "build": # データセット構築ステップ
        # 構築実行
        return build_dataset_parallel(people_list_path=people_list_path, # 渡されたパス
            dataset_path=dataset_path, # 渡されたパス
            limit=kwargs.get("limit", None),
            sleep=kwargs.get("sleep", 1.5))
    elif step == "play": # ゲームプレイステップ
        min_features = kwargs.get("min_feature_threshold", 5) # デフォルト閾値5
        ds = load_dataset(dataset_path=dataset_path, min_feature_threshold=min_features) # データセット読み込み
        
        if not ds: return None # データセット読み込み失敗時は終了
        selected_categories = kwargs.get("categories") # 選択カテゴリ取得
        # 実行
        return akinator_play(ds,                                               # データセット
                             selected_categories=selected_categories,          # 選択カテゴリ
                             max_questions=kwargs.get("max_questions", 1000),  # 最大質問数
                             analysis_size=kwargs.get("analysis_size", 100))   # 分析候補者数
    else: # 不明なステップ
        raise ValueError("不明なステップです。collect, build, play のいずれかを指定してください。")

# -----------------------
# 実行部分
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ ---
    SLEEP = 0.1           # API呼び出し間隔（秒）
    CMLIMIT = 50           # Wikipedia API のカテゴリメンバー取得上限
    DEPTH = 1              # カテゴリ深度
    BUILD_LIMIT = None     # データセット構築の上限（Noneで無制限）
    MAX_QUESTIONS = 1000   # 検索中の最大質問数
    ANALYSIS_SIZE = 100    # 毎回の質問最適化で分析する候補者数

    # データの閾値を緩和
    # 特徴量がこの数未満の人物は検索開始前に除外されます。
    MIN_FEATURE_THRESHOLD = 35 # 閾値

    # --- 実行フロー ---
    try:
        print("--- 🤖 著名人特定プログラム（動的質問生成＋全力分析モード） ---")
        
        if JANOME_TOKENIZER is None: # Janomeが読み込まれていない場合
            print("Janomeが読み込まれていないため、実行を停止します。") # エラーメッセージ表示
            sys.exit(1) # プログラム終了
        
        # カテゴリ選択
        selected_categories = choose_categories()

        # 選択カテゴリに基づいて動的なキャッシュパスをここで生成
        dynamic_list_path = get_dynamic_cache_path(selected_categories, prefix="people_list")
        dynamic_dataset_path = get_dynamic_cache_path(selected_categories, prefix="people_dataset")

        print(f"ターゲットリスト: {dynamic_list_path}")
        print(f"ターゲットデータセット: {dynamic_dataset_path}")
        
        # ステップ実行
        run_step("collect",                          # データ収集ステップ
                 categories=selected_categories,     # 選択カテゴリ
                 cmlimit=CMLIMIT,                    # カテゴリメンバー取得上限
                 depth=DEPTH,                        # カテゴリ深度
                 sleep=SLEEP,                        # API呼び出し間隔
                 people_list_path=dynamic_list_path, # 動的パスを指定
                 dataset_path=dynamic_dataset_path   # 動的パスを指定
                )
        
        print("\n=== データセット構築中 ===")
        print("注意: 初回実行時、人物リストが膨大な場合、この処理には時間がかかります。")
        run_step("build",                            # データセット構築ステップ
                 categories=selected_categories,     # playステップでも使うため渡しておく
                 limit=BUILD_LIMIT,                  # 上限
                 sleep=SLEEP,                        # API呼び出し間隔
                 people_list_path=dynamic_list_path, # 動的パスを指定
                 dataset_path=dynamic_dataset_path   # 動的パスを指定
                )
        
        print("\n=== 検索スタート ===")
        run_step("play",                                       # ゲームプレイステップ
                 categories=selected_categories,               # 選択カテゴリを渡す
                 max_questions=MAX_QUESTIONS,                  # 最大質問数
                 analysis_size=ANALYSIS_SIZE,                  # 分析候補者数
                 min_feature_threshold=MIN_FEATURE_THRESHOLD,  # 最小特徴閾値
                 people_list_path=dynamic_list_path,           # 動的パスを指定
                 dataset_path=dynamic_dataset_path             # 動的パスを指定
                )
                 
    except KeyboardInterrupt: # キーボード割り込み処理
        print("\n処理が中断されました。") # 中断メッセージ表示
    except Exception as e: # その他の例外処理
        print(f"\nエラーが発生しました: {e}") # エラーメッセージ表示
        traceback.print_exc() # デバッグ用にトレースバックも表示