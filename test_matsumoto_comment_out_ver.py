import requests # HTTPリクエスト用
import time # スリープ用
import json # JSON操作用
import os # ファイル操作用
import re # 正規表現用
import random
import wikipediaapi
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
    print("ターミナルで `pip install janome` を実行してください。")
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
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の詩人", "日本の科学者", "日本の数学者", "日本の物理学者",
    "日本の化学者", "日本の医師", "日本の哲学者", "日本の歴史学者", "日本の教育者", "日本の研究者", "日本の発明家",
    # 政治・社会
    "日本の政治家", "日本の外交官", "日本の官僚", "日本の経営者", "日本の起業家", "日本の弁護士", "日本の裁判官",
    # スポーツ
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本の柔道家", "日本のレスリング選手", "日本のオリンピック選手",
    "日本の水泳選手", "日本の陸上競技選手", "日本のテニス選手", "日本のバレーボール選手", "日本のバスケットボール選手",
    # 芸術・文化
    "日本の画家", "日本の彫刻家", "日本の写真家", "日本の建築家", "日本のデザイナー", "日本の陶芸家", "日本の演出家",
    "日本の音楽家", "日本の指揮者", "日本の舞踏家",
]

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}


# -----------------------
# 除外ルール: 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"] # 除外キーワード
    return not any(k in title for k in exclude_keywords) # 人物ページとみなす

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
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
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    # 既存ファイルのチェック
    target_categories = sorted(list(set(categories)))
    # 既存ファイルがあり、カテゴリが一致すればスキップ
    if os.path.exists(save_path):
        # 既存ファイルを読み込み
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f) # JSON読み込み
            saved_categories = data.get("meta", {}).get("categories") # 保存時のカテゴリ
            people_list = data.get("people") # 保存時の人物リスト
            # カテゴリ比較
            if saved_categories == target_categories and people_list is not None: # カテゴリ一致
                print(f"{save_path} が存在し、カテゴリが一致するため、collect はスキップします。") # スキップ
                return people_list # 既存の人物リストを返す
            else:
                print("カテゴリが変更されたため、人物リストを再収集します。") # 再収集
                if os.path.exists(DATASET_FILE):
                    print(f"古いデータセット {DATASET_FILE} をリセットします。") # 再収集時はデータセットもリセット
                    os.remove(DATASET_FILE) # データセット削除
        # デコードエラーなど
        except Exception as e:
            print(f"既存ファイルの形式が古いか壊れています: {e}。再収集します。") # 再収集
            if os.path.exists(DATASET_FILE): os.remove(DATASET_FILE) # データセット削除

    # 収集開始
    print("=== カテゴリから人物リストを収集します ===")
    all_people = set() # 全人物セット
    for cat in target_categories: # 各カテゴリ処理
        print(f"取得中: {cat}") # カテゴリ名表示
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep) # 取得
        print(f"   → {len(people)} 人取得") # 取得数表示
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
    
    # summaryが空かどうかを明示的にログに出す
    if not summary:
        # 概要文が空なら、ここで処理を終了する
        # print("[DEBUG-DYNAMIC] summaryが空(None)のため、動的特徴の抽出をスキップします。")
        # 大量に出すぎる可能性があるのでコメントアウト
        return {}
    
    features = {} # 抽出特徴辞書
    
    # 形態素解析を実行
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary) # トークン化
    except Exception as e:
        # Janomeのパース失敗をログに出す
        print(f"[DEBUG-DYNAMIC] Janome.tokenize(summary) でエラー: {e}")
        return {} # パースに失敗した

    # 抽出する品詞と、特徴キーのプレフィックス
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
        '行う', '行う', '行う', 'おこなう', '持つ', '行く'
    }

    # トークンごとに処理
    for token in tokens:
        pos_parts = token.part_of_speech.split(',') # 品詞分割
        pos_tuple = (pos_parts[0], pos_parts[1]) # 品詞タプル化
        
        if pos_tuple in TARGET_POS_TYPES: # 対象品詞チェック
            if pos_parts[0] in ('形容詞', '動詞'): # 形容詞・動詞は基本形を使用
                word = token.base_form # 基本形
            else:
                word = token.surface # 名詞は表層形
            
            if len(word) > 1 and word not in STOP_WORDS: # 除外単語チェック
                prefix = TARGET_POS_TYPES[pos_tuple] # プレフィックス取得
                features[f"{prefix}{word}"] = 1 # 特徴として追加
    
    # もしJanomeが動いたのに特徴が0ならログに出す
    if not features:
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
# Step2: データセット構築（並列版）
# (summaryの取得状況をログに出す)
# -----------------------
def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                           limit=None, max_workers=150, sleep=0.1):
    
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

            # 2. Janome（動的）の特徴を抽出し、featuresにマージする
            dynamic_features = extract_dynamic_features_from_summary(page.summary)
            
            # 動的特徴が空だった場合のログ
            if not dynamic_features and page.summary:
                # summaryはあったのに、Janomeが特徴を返さなかった場合
                print(f"  [DEBUG-PROCESS] {name}: Summaryはありましたが、動的特徴は0個でした。")

            # 動的特徴をマージ
            if dynamic_features:
                features.update(dynamic_features) # featuresにマージ
            
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
                    award_qids = wd.get("award_qids", []) # 受賞QIDリスト
                    if "Q1138032" in award_qids: features["award_shiju"] = 1 # 紫綬褒章受賞
            return rec # 正常終了返す

        except Exception as e: # 致命的なエラー処理
            print(f"!!!!!!!!!!!!! 致命的なエラー {name} !!!!!!!!!!!!!")
            traceback.print_exc()
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            return {"name": name, "error": str(e)} # エラー返す

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

    # --- 1. 共通質問 (Wikidata由来 + 日付 + 名前) ---
    common_questions_def = [
        ("gender_male", "男性ですか？", "common"), ("gender_female", "女性ですか？", "common"),
        ("alive_text", "現在もご存命ですか？", "common"),
        ("actor_wikidata", "本業は俳優ですか？", "occupation"),
        ("singer_wikidata", "本業は歌手ですか？", "occupation"),
        ("politician_wikidata", "本業は政治家ですか？", "occupation"),
        ("age_20s", "現在、20代ですか？", "common"), ("age_30s", "現在、30代ですか？", "common"),
        ("age_40s", "現在、40代ですか？", "common"), ("age_50s", "現在、50代ですか？", "common"),
        ("born_1980s", "1980年代生まれですか？", "common"), ("born_1990s", "1990年代生まれですか？", "common"),
        ("born_2000s", "2000年代生まれですか？", "common"),
        ("died_20c", "20世紀（1900年代）に亡くなりましたか？", "common"),
        ("has_katakana", "名前にカタカナが含まれていますか？", "common"),
        ("is_hiragana_only", "名前はひらがなだけですか？", "common"),
        ("from_tokyo", "出身は東京ですか？", "feature"),
        ("from_kansai", "出身は関西（大阪・京都・兵庫）ですか？", "feature"),
        ("grad_todai", "東京大学を卒業していますか？", "feature"),
        ("grad_waseda", "早稲田大学を卒業していますか？", "feature"),
        ("grad_keio", "慶應義塾大学を卒業していますか？", "feature"),
        ("award_shiju", "紫綬褒章を受章していますか？", "feature"),
    ]

    # 共通質問を追加
    for key, text, category in common_questions_def:
        key_exists = any(key in rec.get("features", {}) for rec in dataset) # キー存在チェック
        if key_exists and key not in added_keys: # 未追加なら追加
            # 質問マップに追加
            qm[category].append({
                "key": key, "text": text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key) # 追加済みセットに登録

    # --- 2. FEATURE_KEYWORDS に基づく質問 (Summary由来) ---
    feature_questions_def = {
        "comedian": ("お笑い芸人ですか？", "occupation"),
        "seiyuu": ("声優として活動していますか？", "occupation"),
        "athlete": ("スポーツ選手ですか？", "occupation"),
        "model": ("モデルとして活動していますか？", "occupation"),
        "idol": ("アイドル活動をしていましたか（していますか）？", "occupation"),
        "youtuber": ("YouTuberとして活動していますか？", "occupation"),
        "director": ("監督（映画やアニメなど）ですか？", "occupation"),
        "taiga": ("大河ドラマに出演しましたか？", "activity"),
        "tokusatsu": ("特撮作品（仮面ライダーなど）に出演しましたか？", "activity"),
        "romance_drama": ("恋愛ドラマに出演しましたか？", "activity"),
        "movie": ("映画に出演していますか？", "activity"),
        "action": ("アクション作品に出演していますか？", "activity"),
        "stage": ("舞台（演劇・ミュージカル）に出演していますか？", "activity"),
        "anime": ("アニメ作品に関わっていますか？", "activity"),
        "hollywood": ("海外（ハリウッド等）の作品に出演していますか？", "activity"),
        "nhk": ("NHK（朝ドラなど）に出演したことがありますか？", "activity"),
        "award": ("（演技賞や作品賞など）を受賞したことがありますか？", "feature"),
        "mc": ("司会者（MC）として有名ですか？", "activity"),
        "radio": ("ラジオ番組を持っていますか？", "activity"),
        "cm": ("CMに多く出演していますか？", "activity"),
        "married": ("結婚していることを公表していますか？", "feature"),
        "author": ("本（エッセイなど）を出版したことがありますか？", "feature"),
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
        
    # --- 3. データセットから "noun_", "adj_", "verb_" キーを動的に読み込み質問を生成する ---
    
    print("データセットをスキャンして、動的な質問（名詞・形容詞・動詞）を生成します...")
    all_dynamic_keys = set() # すべての動的特徴キーセット
    DYNAMIC_PREFIXES = ("noun_", "adj_", "verb_") # 動的特徴のプレフィックス
    
    # データセットスキャン
    for rec in dataset:
        if not rec.get("features"): continue # featuresがない場合スキップ
        for key in rec["features"].keys(): # 特徴キーごとに
            if key.startswith(DYNAMIC_PREFIXES): # 動的特徴プレフィックスチェック
                all_dynamic_keys.add(key) # 動的特徴キーセットに追加
    
    print(f"   → {len(all_dynamic_keys)} 種類のユニークな動的特徴を発見しました。") # 発見数ログ

    # フィルタリング
    total_people = len(dataset)
    
    # 閾値を緩和 (最低2人)
    min_count = max(2, int(total_people * 0.001)) # 最低1‰または2人
    max_count = int(total_people * 0.95)          # 最高95%
    
    useful_dynamic_keys = set() # 有用な動的特徴キーセット
    for key in all_dynamic_keys: # 動的特徴キーごとに
        count = sum(1 for rec in dataset if rec.get("features", {}).get(key) == 1) # 出現カウント
        if min_count <= count <= max_count: # 閾値チェック
            useful_dynamic_keys.add(key) # 有用セットに追加

    print(f"   → フィルタリング後、有用な質問を {len(useful_dynamic_keys)} 件、質問マスターリストに追加します。")

    for key in useful_dynamic_keys: # 有用な動的特徴キーごとに
        if key in added_keys: continue # 既に追加済みならスキップ
        
        question_text = "" # 質問テキスト初期化
        
        if key.startswith("noun_"): # 名詞特徴
            noun = key[len("noun_"):] # 名詞部分抽出
            question_text = f"『{noun}』に（深く）関連していますか？" # 名詞関連質問
        elif key.startswith("adj_"): # 形容詞特徴
            adj = key[len("adj_"):] # 形容詞部分抽出
            question_text = f"『{adj}』というイメージ/特徴がありますか？" # 形容詞関連質問
        elif key.startswith("verb_"): # 動詞特徴
            verb = key[len("verb_"):] # 動詞部分抽出
            question_text = f"『{verb}』という活動をしましたか（しますか）？" # 動詞関連質問

        if question_text: # 質問テキストが生成されたら
            # 質問マップに追加
            qm["activity"].append({
                "key": key, 
                "text": question_text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key) # 追加済みセットに登録
            
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
                score = (yes_count * no_count) * priority_weight # スコア計算
            
            if score > best_score: # 最良スコア更新
                best_score = score # スコア更新
                best_question = question # 最適な質問更新
            
            elif score == 0: # スコア0の質問を保持
                zero_score_questions.append(question) # スコア0質問リストに追加

    # もし最適な質問 (score > 0) が見つからなかった場合、スコア0の質問が残っていれば、それをランダムに返す
    if best_question is None and zero_score_questions: # 最適な質問がない場合
        # print("[デバッグ] 最適な質問がなかったため、スコア0の質問から選びます。")
        return random.choice(zero_score_questions) # スコア0の質問からランダムに選択
        
    return best_question # 最適な質問を返す

# -----------------------
# アキネーター本体ループ (カスタムロジック)
# -----------------------
def akinator_play(dataset, selected_categories=None, max_questions=1000, analysis_size=100):
    """
    候補者が1人になるまで質問を続ける。
    """
    candidates = dataset.copy() # 候補者リスト初期化
    qm_dict = generate_question_map(dataset, selected_categories) # 質問マップ生成
    
    print(f"=== 🕵️ 人物検索開始 (1人特定/候補者全員・全力分析モード) ===")
    print(f"※ 毎回、残りの候補者全員 ({len(candidates)}人) を分析して最適な質問を厳選します。")
    print("回答は「はい(y) / いいえ(n) / わからない(u)」のいずれかを入力してください。")
    print("---")
    
    asked_keys = set() # 尋ねた質問キーセット
    asked_count = 0 # 尋ねた質問回数カウンタ

    # ループの継続条件を「候補者が1人より多い」に変更
    while len(candidates) > 1 and asked_count < max_questions: # 候補者が1人より多く、質問回数が上限未満の場合
        
        candidates_for_analysis = candidates # 解析用候補者リスト初期化
            
        if len(candidates_for_analysis) > 500: # 候補者が多すぎる場合、ランダムサンプリング
            print(f"\n[... {len(candidates_for_analysis)}人から最適な質問を計算中 ...]")
        
        question = find_best_question(candidates_for_analysis, qm_dict, asked_keys) # 最適な質問を取得
        
        if question is None: # 質問が見つからなかった場合
            print("\n質問が尽きるか、残りの候補で質問が分けられなくなりました。残りの候補から推測します...")
            break

        key, q_text, test = question["key"], question["text"], question["check"] # 質問情報取得
        
        yes_count_analysis = sum(1 for c in candidates_for_analysis if test(c)) # はいカウント
        no_count_analysis = len(candidates_for_analysis) - yes_count_analysis # いいえカウント
        
        print(f"\n[質問 {asked_count+1}] (候補: {len(candidates)}人 | 全員分析の分割予測: {yes_count_analysis} / {no_count_analysis})")
        ans = input(q_text + " （y/n/u） > ").strip().lower() # ユーザー入力取得
        
        asked_keys.add(key) # 尋ねた質問キーを登録
        
        if ans in ("はい", "y"): # 「はい」の場合に絞り込み
            candidates = [c for c in candidates if test(c)]
        elif ans in ("いいえ", "n"): # 「いいえ」の場合に絞り込み
            candidates = [c for c in candidates if not test(c)]
        elif ans in ("わからない", "u"): # 「わからない」の場合はスキップ
            pass 
        else: # 無効な回答の場合
            print("無効な回答です。スキップします。")
            continue

        asked_count += 1 # 質問回数カウンタ増加
        
        if len(candidates) == 0: # 候補者が0人になった場合
            print("\n候補者がいなくなってしまいました。質問の回答に矛盾があった可能性があります。")
            break
        elif len(candidates) < 10: # 候補者が10人未満の場合、名前を表示
             print(f"(現在の候補数: {len(candidates)}人 - {', '.join([c['name'] for c in candidates])})")
        else: # 候補者が10人以上の場合、数だけ表示
             print(f"(現在の候補数: {len(candidates)}人)")


    # -----------------------------
    # 最終的な提案ロジック (1人になった場合に対応)
    # -----------------------------
    print("\n===============================")
    
    # 最終結果の表示
    if len(candidates) == 1:
        # 目的の「1人」になった場合
        c = candidates[0] # 唯一の候補者取得
        print(f"🎉 答えが特定できました！ ({asked_count}回の質問)")
        print("-------------------------------")
        print(f"**あなたが思い浮かべたのは... 『{c['name']}』**")
        
    elif len(candidates) > 1:
        # 質問が尽きたが、2人以上残った場合 (特徴が完全一致)
        print(f"🤔 {asked_count}回の質問では1人に絞り込めませんでした。")
        print(f"特徴が完全に一致する候補が {len(candidates)}人 残りました。")
        print(f"=== 最終候補 ===")
        for i, c in enumerate(candidates, 1):
            print(f"{i}. **{c['name']}**")
        
    elif len(candidates) == 0:
        # 候補者が0人になった場合
        print("😢 最終的な候補者が0人になってしまいました。")
        
    print("===============================")
    return candidates


# -----------------------
# エントリポイント用関数
# -----------------------
def run_step(step="collect", **kwargs):
    step = step.lower() # 小文字化
    if step == "collect": # データ収集ステップ
        # 収集実行
        return collect_people(categories=kwargs.get("categories", CATEGORIES),
                              cmlimit=kwargs.get("cmlimit", 50),
                              depth=kwargs.get("depth", 1),
                              sleep=kwargs.get("sleep", 0.8))
    elif step == "build": # データセット構築ステップ
        # 構築実行
        return build_dataset_parallel(limit=kwargs.get("limit", None),
                                      sleep=kwargs.get("sleep", 0.8))
    elif step == "play": # ゲームプレイステップ
        min_features = kwargs.get("min_feature_threshold", 5) # デフォルト閾値5
        ds = load_dataset(min_feature_threshold=min_features) # データセット読み込み
        
        if not ds: return None # データセット読み込み失敗時は終了
        selected_categories = kwargs.get("selected_categories") # 選択カテゴリ取得
        # ゲーム実行
        return akinator_play(ds, 
                             selected_categories=selected_categories, 
                             max_questions=kwargs.get("max_questions", 1000),
                             analysis_size=kwargs.get("analysis_size", 100))
    else: # 不明なステップ
        raise ValueError("不明なステップです。collect, build, play のいずれかを指定してください。")

# -----------------------
# 実行部分
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ ---
    SLEEP = 0.01           # API呼び出し間隔（秒）
    CMLIMIT = 50           # Wikipedia API のカテゴリメンバー取得上限
    DEPTH = 1              # カテゴリ深度
    BUILD_LIMIT = None     # データセット構築の上限（Noneで無制限）
    MAX_QUESTIONS = 1000   # ゲーム中の最大質問数
    ANALYSIS_SIZE = 100    # 毎回の質問最適化で分析する候補者数

    # データの閾値を緩和
    # 特徴量がこの数未満の人物はゲーム開始前に除外されます。
    MIN_FEATURE_THRESHOLD = 2 # 変更後の閾値

    # --- 実行フロー ---
    try:
        print("--- 🤖 人物特定プログラム（動的質問生成＋全力分析モード） ---")
        
        if JANOME_TOKENIZER is None: # Janomeが読み込まれていない場合
            print("Janomeが読み込まれていないため、実行を停止します。") # エラーメッセージ表示
            sys.exit(1) # プログラム終了
        
        # カテゴリ選択
        selected_categories = choose_categories()
        
        # ステップ実行
        run_step("collect",                       # データ収集ステップ
                 categories=selected_categories,  # 選択カテゴリ
                 cmlimit=CMLIMIT,                 # カテゴリメンバー取得上限
                 depth=DEPTH,                     # カテゴリ深度
                 sleep=SLEEP)                     # API呼び出し間隔
        
        print("\n=== データセット構築中 ===")
        print("注意: 初回実行時、人物リストが膨大な場合、この処理には時間がかかります。")
        run_step("build",                         # データセット構築ステップ
                 limit=BUILD_LIMIT,               # 上限
                 sleep=SLEEP)                     # API呼び出し間隔
        
        print("\n=== ゲームスタート ===")
        run_step("play",                                       # ゲームプレイステップ
                 selected_categories=selected_categories,      # 選択カテゴリ
                 max_questions=MAX_QUESTIONS,                  # 最大質問数
                 analysis_size=ANALYSIS_SIZE,                  # 分析候補者数
                 min_feature_threshold=MIN_FEATURE_THRESHOLD)  # 最小特徴閾値
                 
    except KeyboardInterrupt: # キーボード割り込み処理
        print("\n処理が中断されました。") # 中断メッセージ表示
    except Exception as e: # その他の例外処理
        print(f"\nエラーが発生しました: {e}") # エラーメッセージ表示