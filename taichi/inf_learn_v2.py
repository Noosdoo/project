import requests # HTTPリクエスト用
import time # スリープ用
import json # JSON操作用
import os # ファイル操作用
import re # 正規表現用
import unicodedata # 文字列正規化用
import random # ランダム選択用
import wikipediaapi # Wikipedia API用
import traceback # デバッグ用にインポート
from datetime import datetime # 日付処理のため
from concurrent.futures import ThreadPoolExecutor, as_completed # 並列処理用
import sys # 標準入出力のエンコーディング設定用

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
    print("エラー : Janomeがインストールされていません。")
    print("動的な質問生成（名詞分析）を利用するには、Janomeが必要です。")
    print("ターミナルで 'pip install -U janome' を実行してください。")
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

# 保存先ファイル名（デフォルト）
PEOPLE_LIST_FILE = "people_list.json" 
DATASET_FILE = "people_dataset.json"   
MISTAKE_LOG_FILE = "mistake_log.json"

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}

# 取得対象カテゴリ
CATEGORIES = [
    # 俳優・芸能
    "日本の俳優", "日本の女優", "お笑い芸人", "日本の声優", "日本のアイドル", "日本のモデル", "日本の歌手",
    "日本の作曲家", "日本の映画監督", "日本の舞台俳優", "日本のアナウンサー", "日本のYouTuber",
    # 文学・学問
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の医師", "日本の教育者",
    # 政治・社会
    "日本の政治家", "日本の官僚", "日本の起業家", "日本の弁護士",
    # スポーツ
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本の柔道家", "日本の格闘家", "日本のレスリング選手", "日本のオリンピック選手",
    "日本の水泳選手", "日本の陸上競技選手", "日本のテニス選手", "日本のバレーボール選手", "日本のバスケットボール選手", "日本のゴルファー",
    # 芸術・文化
    "日本の画家", "日本の建築家", "日本のデザイナー"
]

# -----------------------
# リトライ機能付きJSON取得 (APIエラー対策)
# -----------------------
def get_json_with_retry(url, params=None, headers=HEADERS, retries=3, backoff_factor=1.0):
    for i in range(retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in (429, 503):
                wait_time = backoff_factor * (2 ** i)
                time.sleep(wait_time)
            else:
                return None
        except json.JSONDecodeError:
            time.sleep(backoff_factor * (2 ** i))
        except requests.exceptions.RequestException:
            time.sleep(backoff_factor * (2 ** i))
    return None

# -----------------------
# Wikipediaのメイン画像URLを取得
# -----------------------
def get_wikipedia_main_image(title, thumb_size=300):
    params = {
        "action": "query", "titles": title, "prop": "pageimages",
        "pithumbsize": str(thumb_size), "format": "json",
    }
    data = get_json_with_retry(WIKI_API, params=params)
    if not data: return None
    pages = data.get("query", {}).get("pages", {})
    if not pages: return None
    page_id = next(iter(pages))
    page_data = pages[page_id]
    if "thumbnail" in page_data: return page_data["thumbnail"]["source"]
    elif "original" in page_data: return page_data["original"]["source"]
    return None

# -----------------------
# カテゴリに基づいたキャッシュファイル名
# -----------------------
def get_dynamic_cache_path(categories_list, prefix="people_list"):
    sorted_cats = sorted(list(set(categories_list)))
    num_cats = len(sorted_cats)
    total_cats = len(CATEGORIES)
    filename_part = ""
    if num_cats == 0 or num_cats == total_cats:
        filename_part = "ALL"
    else:
        safe_names = [re.sub(r'[\\/:*?"<>|]', '-', cat) for cat in sorted_cats]
        filename_part = "_".join(safe_names)
    return f"{prefix}_{filename_part}.json"

# -----------------------
# 除外ルール : 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

# -----------------------
# ユーティリティ : Wikipediaカテゴリからタイトル取得
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=1.5):
    if collected is None: collected = set()
    cmtitle = f"Category:{category}"
    params = {"action": "query", "list": "categorymembers", "cmtitle": cmtitle, "cmlimit": str(cmlimit), "format": "json"}
    cont = None
    while True:
        if cont: params.update(cont)
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception: return collected
        if res.status_code == 403: return collected
        try:
            data = res.json()
        except Exception: return collected
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title: continue
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep)
                continue
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]) or not is_person_page(title):
                continue
            collected.add(title)
        if "continue" in data:
            cont = data["continue"]; time.sleep(sleep)
        else:
            break
    return collected

# -----------------------
# カテゴリ選択
# -----------------------
def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5) / 全ての場合は Enter")
    
    # 全角数字対応などで正規化
    raw_input = input("> ").strip()
    normalized_input = unicodedata.normalize("NFKC", raw_input)
    
    if not normalized_input:
        print("全カテゴリを対象にします。"); return CATEGORIES
    selected = []
    for part in normalized_input.split(","):
        try:
            idx = int(part)-1
            if 0 <= idx < len(CATEGORIES): selected.append(CATEGORIES[idx])
        except: pass
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。"); return CATEGORIES
    print(f"選択されたカテゴリ: {', '.join(selected)}"); return selected

# -----------------------
# 全カテゴリから人物を収集して保存 
# -----------------------
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=1.5, save_path=PEOPLE_LIST_FILE, corresponding_dataset_path=DATASET_FILE):
    EXCLUDE_KEYWORDS = ["テレビ", "番組", "映画", "ドラマ", "アニメ", "漫画", "作品", "イベント", "シリーズ", "コンビ", "グループ", "キャラクター", "音楽", "アルバム", "曲", "小説", "ゲーム", "企画", "特集", "大会", "舞台", "公演", "放送"]
    
    target_categories = sorted(list(set(categories)))
    
    if os.path.exists(save_path):
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f)
            saved_categories = data.get("meta", {}).get("categories")
            people_list = data.get("people")
            
            if saved_categories == target_categories and people_list is not None: 
                print(f"\n--- キャッシュが見つかりました: {save_path} ---")
                print("  1 : キャッシュを使用 (収集/構築をスキップ)")
                print("  2 : 再収集 (キャッシュを削除して最初から)")
                choice = input(" (1/2) > ").strip()
                if choice == "1":
                    return people_list
                elif choice == "2":
                    print("キャッシュを削除し、再収集します。")
                    if os.path.exists(save_path): os.remove(save_path)
                    if os.path.exists(corresponding_dataset_path): os.remove(corresponding_dataset_path)
                else:
                    return people_list
            else:
                print("カテゴリ変更のため、再収集します。")
                if os.path.exists(corresponding_dataset_path): os.remove(corresponding_dataset_path)
        except Exception:
            if os.path.exists(save_path): os.remove(save_path)

    print("=== 人物リストを収集します ===")
    all_people = set()
    for cat in target_categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        filtered = []
        for name in people:
            if any(word in name for word in EXCLUDE_KEYWORDS): continue
            if len(name) < 2 or re.fullmatch(r"[0-9０-９A-Za-z]+", name): continue
            filtered.append(name)
        print(f"   → {len(filtered)} 件")
        all_people.update(filtered)
        time.sleep(sleep)
    
    people_list = sorted(list(all_people))
    save_data = {"meta": {"categories": target_categories, "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, "people": people_list}
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）"); return people_list

# -----------------------
# Wikidata取得補助
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {"action": "query", "titles": title, "prop": "pageprops", "format": "json"}
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        data = res.json(); pages = data.get("query", {}).get("pages", {})
        if not pages: return None
        page = next(iter(pages.values())); pp = page.get("pageprops", {})
        return pp.get("wikibase_item")
    except Exception: return None

# -----------------------
# Wikidataから構造化属性を取得 
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        data = res.json()
        entity = data.get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {}
        
        # Helper function for getting claim ID
        def get_claim_ids(prop):
            ids = []
            if prop in claims:
                for c in claims[prop]:
                    try:
                        v = c["mainsnak"]["datavalue"]["value"]
                        if isinstance(v, dict) and "id" in v: ids.append(v["id"])
                    except: pass
            return ids

        result["occupation_qids"] = get_claim_ids("P106")
        result["education_qids"] = get_claim_ids("P69")
        result["award_qids"] = get_claim_ids("P166")
        
        # Gender
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v: result["gender_qid"] = v["id"]
            except: pass
        
        # Times
        for p_time, key in [("P569", "birth_time"), ("P570", "death_time")]:
            if p_time in claims:
                try:
                    t = claims[p_time][0]["mainsnak"]["datavalue"]["value"]["time"]
                    result[key] = t
                except: pass
        
        # Birth Place
        if "P19" in claims:
            try:
                v = claims["P19"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v: result["birth_place_qid"] = v["id"]
            except: pass
            
        return result
    except Exception:
        return None

# -----------------------
# テキストクリーンアップ
# -----------------------
def clean_text(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1F\x7F]", "", text)
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# -----------------------
# summaryから【Janomeベース（動的）】で特徴を抽出
# -----------------------
def extract_dynamic_features_from_summary(summary):
    if not JANOME_TOKENIZER or not summary: return {}
    features = {} 
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary) 
    except Exception: return {} 

    TARGET_POS_TYPES = {
        ('名詞', '一般'): 'noun_', ('名詞', '固有名詞'): 'noun_',
        ('形容詞', '自立'): 'adj_', ('動詞', '自立'): 'verb_' 
    }
    STOP_WORDS = {
        'こと', 'もの', 'ため', '人物', '概要', '日本', '活動', '出身',
        '現在', '自身', 'ほか', '以降', '選手', '俳優', '女優', '芸人',
        '声優', 'モデル', 'アイドル', 'メンバー', 'グループ', '監督', '主演',
        'さん', '男性', '女性', '氏名', '関係', '存在', '世界',
        '全国', '歴史', '時代', '今日', '連続', '以上', '以下', '約', '程度',
        'する', 'いる', 'ある', 'なる', 'ない', 'よい', 'できる', 'いう',
        '行う', 'おこなう', '持つ', '行く', '出身', '卒業', '在住', '在学'
    }

    for token in tokens:
        pos_parts = token.part_of_speech.split(',')
        pos_tuple = (pos_parts[0], pos_parts[1])
        if pos_tuple in TARGET_POS_TYPES:
            word = token.base_form if pos_parts[0] in ('形容詞', '動詞') else token.surface
            if len(word) > 1 and word not in STOP_WORDS:
                features[f"{TARGET_POS_TYPES[pos_tuple]}{word}"] = 1
    
    # 『作品名』の抽出
    work_titles = re.findall(r'『(.*?)』', summary)
    IGNORE_TITLES = {"日本", "世界", "現在", "公式", "一覧", "映画", "ドラマ", "漫画", "小説", "プロフィール", "経歴", "人物"}
    for title in work_titles:
        if len(title) < 2 or len(title) > 20 or "," in title or "。" in title: continue
        if title not in IGNORE_TITLES: features[f"work_{title}"] = 1

    return features

# -----------------------
# summaryからキーワードベースで特徴を抽出
# -----------------------
FEATURE_KEYWORDS = {
    "taiga": ["大河ドラマ", "大河"], "tokusatsu": ["仮面ライダー", "スーパー戦隊", "ウルトラマン", "特撮"],
    "romance_drama": ["恋愛", "ラブストーリー"], "movie": ["映画", "劇場版"],
    "action": ["アクション", "殺陣"], "seiyuu": ["声優", "アニメで声"],
    "singer": ["歌手", "シンガー", "ボーカル"], "stage": ["舞台", "ミュージカル"],
    "model": ["モデル"], "comedian": ["お笑い", "芸人", "コント"],
    "anime": ["アニメ"], "hollywood": ["ハリウッド", "海外映画"],
    "idol": ["アイドル", "グループ"], "award": ["受賞", "賞を受賞", "主演男優賞", "最優秀"],
    "nhk": ["NHK", "連続テレビ小説", "朝ドラ"], "youtuber": ["YouTube", "チャンネル"],
    "director": ["監督"], "athlete": ["選手", "オリンピック", "サッカー", "野球"],
    "politician": ["政治家", "衆議院"], "mc": ["司会", "MC"],
    "radio": ["ラジオ"], "cm": ["CM"], "married": ["結婚", "妻", "夫"], "author": ["執筆", "出版", "著書"],
}

def extract_features_from_summary(summary):
    s = summary or ""
    features = {}
    for k, keywords in FEATURE_KEYWORDS.items():
        features[k] = int(any(kw in s for kw in keywords))
    
    m = re.search(r'(\d{4})年', s)
    if m:
        try: features["birth_year"] = int(m.group(1))
        except: pass
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1

    GROUP_KEYWORDS = ["グループ", "ユニット", "コンビ", "トリオ", "バンド", "メンバー", "結成", "解散", "加入", "脱退"]
    features["is_group_member"] = int(any(kw in s for kw in GROUP_KEYWORDS))

    FAMOUS_OFFICES = {
        "office_yoshimoto": ["吉本興業", "よしもと"],
        "office_johnnys": ["ジャニーズ", "SMILE-UP", "STARTO", "SMAP", "嵐", "Snow Man", "SixTONES"],
        "office_horipro": ["ホリプロ"], "office_oscar": ["オスカー"], "office_amuse": ["アミューズ"],
        "office_stardust": ["スターダスト"], "office_ldh": ["LDH", "EXILE"], "office_shiki": ["劇団四季"],
        "office_takarazuka": ["宝塚歌劇団", "宝塚"], "office_akb": ["AKB", "乃木坂", "櫻坂", "日向坂"],
    }
    for key, keywords in FAMOUS_OFFICES.items():
        features[key] = int(any(kw in s for kw in keywords))
    return features

# -----------------------
# ユーティリティ : 人物リスト読み込み
# -----------------------
def load_people_list(people_list_path=PEOPLE_LIST_FILE):
    if not os.path.exists(people_list_path): return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, dict): return data.get("people")
        elif isinstance(data, list): return data
        return None
    except Exception: return None

# -----------------------
# 【共通化】人物データ取得・解析ロジック
# -----------------------
def scrape_person_data(name, source_type="auto"):
    """
    指定された人物名のWikipedia/Wikidataを取得し、データレコードを作成して返す。
    """
    try:
        wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
        page = wiki.page(name)

        if not page.exists():
            search_results = wiki.search(name)
            if search_results: page = wiki.page(search_results[0])
            else: return {"name": name, "error": "ページなし"}

        if not page.summary: return {"name": name, "error": "Summaryが空"}

        # 基本情報
        rec = {"name": name, "summary": page.summary, "features": None, "wikidata": None, "source": source_type}
        
        # 1. 特徴抽出
        features = extract_features_from_summary(page.summary)
        if JANOME_TOKENIZER:
            dynamic_features = extract_dynamic_features_from_summary(page.summary)
            if dynamic_features: features.update(dynamic_features)
        
        # 3. カテゴリ特徴
        try:
            page_categories = page.categories
            IGNORE_CATS_KEYWORDS = {"存命人物", "死去した人物", "日本の人物", "曖昧さ回避", "リダイレクト", "人物", "生年", "没年", "年没", "年生", "世紀没", "世紀生", "ウィキデータ", "ID", "記事", "テンプレート", "出典", "外部リンク", "カテゴリ", "スタブ", "一覧", "プロジェクト", "編集"}
            for cat_title in page_categories.keys():
                cat_name = cat_title.replace("Category:", "").strip()
                if any(keyword in cat_name for keyword in IGNORE_CATS_KEYWORDS): continue
                if cat_name.endswith("年生") or cat_name.endswith("年没"): continue
                features[f"cat_{cat_name}"] = 1
        except Exception: pass

        # 名前構造
        if re.search(r'[ァ-ヶ]', name): features["has_katakana"] = 1
        if re.fullmatch(r'[ぁ-ん]+', name): features["is_hiragana_only"] = 1
        rec["features"] = features

        # 4. Wikidata詳細解析
        wikibase_id = get_wikibase_item_from_wikipedia(name)
        if wikibase_id:
            wd = fetch_wikidata_entity(wikibase_id)
            rec["wikidata"] = wd
            if wd:
                g = wd.get("gender_qid")
                if g == "Q6581097": features["gender"] = "male"
                elif g == "Q6581072": features["gender"] = "female"
                
                birth_time = wd.get("birth_time")
                current_year = datetime.now().year
                if birth_time:
                    try:
                        birth_year = int(birth_time.strip("+-").split("-")[0])
                        age = current_year - birth_year
                        if 20 <= age < 30: features["age_20s"] = 1
                        if 30 <= age < 40: features["age_30s"] = 1
                        if 40 <= age < 50: features["age_40s"] = 1
                        if 50 <= age < 60: features["age_50s"] = 1
                        if 1980 <= birth_year <= 1989: features["born_1980s"] = 1
                        if 1990 <= birth_year <= 1999: features["born_1990s"] = 1
                        if 2000 <= birth_year <= 2009: features["born_2000s"] = 1
                    except: pass
                
                if wd.get("death_time"):
                    try:
                        death_year = int(wd["death_time"].strip("+-").split("-")[0])
                        if 1900 <= death_year <= 1999: features["died_20c"] = 1
                    except: pass

                if "P1853" in wd: # claimsではなくentity["claims"]相当のwd
                     # 簡易実装: 既にfetch_wikidataで構造化されている場合はここを調整
                     pass 

                # 国籍 (P27), 家族 (P22等), 分野 (P101) などのロジックは
                # 必要に応じてscrape_person_data(完全版)から移植してください
                
                # 職業
                occ_qs = wd.get("occupation_qids", [])
                if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]): features["actor_wikidata"] = 1
                if any(q in occ_qs for q in ["Q177220", "Q639669", "Q10800557"]): features["singer_wikidata"] = 1
                if "Q82955" in occ_qs: features["politician_wikidata"] = 1

                place_qid = wd.get("birth_place_qid")
                if place_qid in {"Q1490", "Q1228", "Q11103005", "Q200000", "Q200072"}: features["from_tokyo"] = 1
                elif place_qid in {"Q172582", "Q16997", "Q486245", "Q132640", "Q132643"}: features["from_kansai"] = 1

                award_qids = wd.get("award_qids", []) 
                if "Q1085422" in award_qids: features["award_academy_jp"] = 1
        
        return rec
    except Exception as e:
        return {"name": name, "error": str(e)}

# -----------------------
# データセット構築（差分更新・ラベル指定対応版）
# -----------------------
def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                           limit=None, max_workers=30, sleep=0.1, 
                           source_label="auto"):
    print(f"=== データセットの差分更新を開始します (Label: {source_label}) ===")
    people_targets = load_people_list(people_list_path)
    if people_targets is None:
        print("人物リストが存在しません。")
        return None
    if JANOME_TOKENIZER is None:
        print("Janomeが読み込まれていないため、中止します。")
        return None
    
    existing_data_map = {} 
    if os.path.exists(dataset_path): 
        try:
            with open(dataset_path, "r", encoding="utf-8") as f: 
                existing_data_map = {p["name"]: p for p in json.load(f)} 
                print(f"📂 既存データ: {len(existing_data_map)} 件を読み込みました。") 
        except Exception: existing_data_map = {} 

    targets_to_process = []
    current_targets = people_targets[:limit] if limit else people_targets

    for name in current_targets:
        if name in existing_data_map: continue # 既存データ保護
        targets_to_process.append(name)

    if not targets_to_process:
        print("✨ 追加学習は不要です。") 
        return list(existing_data_map.values()) 

    print(f"🔍 新規追加: {len(targets_to_process)} 件 (Label: {source_label})") 

    new_records = [] 
    processed_count = 0 
    total = len(targets_to_process)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor: 
        future_to_name = {
            executor.submit(scrape_person_data, name, source_type=source_label): name 
            for name in targets_to_process
        }
        for future in as_completed(future_to_name): 
            name = future_to_name[future] 
            processed_count += 1 
            try:
                rec = future.result() 
                new_records.append(rec) 
                if "error" in rec: print(f"[{processed_count}/{total}] × {name}") 
                else: print(f"[{processed_count}/{total}] ✓ {name}") 
            except Exception: pass
            time.sleep(sleep) 

    for rec in new_records: existing_data_map[rec["name"]] = rec
    final_dataset = list(existing_data_map.values()) 
    
    with open(dataset_path, "w", encoding="utf-8") as f: 
        json.dump(final_dataset, f, ensure_ascii=False, indent=2) 
    print(f"✅ 保存完了: 合計 {len(final_dataset)} 件") 
    return final_dataset

# -----------------------
# 新規人物データの取得と追記
# -----------------------
def fetch_and_add_new_person_data(new_person_name, dataset_path=DATASET_FILE):
    existing_dataset = []
    if os.path.exists(dataset_path):
        try:
            with open(dataset_path, "r", encoding="utf-8") as f: existing_dataset = json.load(f)
        except Exception: existing_dataset = []
            
    existing_manual_names = {rec.get("name") for rec in existing_dataset if isinstance(rec, dict) and rec.get("source") == "manual"}
    if new_person_name in existing_manual_names:
        print(f"⚠️ 『{new_person_name}』は既に手動データとして存在しています。スキップします。")
        return 

    print(f"\n💡 新規データ構築: {new_person_name}")
    new_record = scrape_person_data(new_person_name, source_type="manual")

    if not new_record or "error" in new_record:
        print(f"データ取得失敗: {new_record.get('error') if new_record else '不明'}")
        return

    existing_dataset = [d for d in existing_dataset if d["name"] != new_person_name]
    existing_dataset.append(new_record)
    
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(existing_dataset, f, ensure_ascii=False, indent=2)
    print(f"✅ 追記完了: {new_person_name}")

# -----------------------
# 学習データの更新機能
# -----------------------
def refresh_learned_data(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path): return
    with open(dataset_path, "r", encoding="utf-8") as f: data = json.load(f)
    target_names = [d["name"] for d in data if d.get("source") == "manual"]
    if not target_names: print("学習データなし"); return

    print(f"--- 学習データ更新: {len(target_names)}件 ---")
    updated_records = []
    for i, name in enumerate(target_names, 1):
        print(f"[{i}/{len(target_names)}] {name}")
        rec = scrape_person_data(name, source_type="manual")
        if not "error" in rec: updated_records.append(rec)
        else:
            old_rec = next(d for d in data if d["name"] == name)
            updated_records.append(old_rec)
        time.sleep(1.0)

    other_data = [d for d in data if d.get("source") != "manual"]
    final_data = other_data + updated_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    print("完了")

# -----------------------
# アキネーター本体: データセット読み込み
# -----------------------
def load_dataset(dataset_path=DATASET_FILE, min_feature_threshold=10):
    if not os.path.exists(dataset_path): return None
    try:
        with open(dataset_path, "r", encoding="utf-8") as f: data = json.load(f)
        valid_data = [d for d in data if d.get("features") and len(d.get("features", {})) >= min_feature_threshold]
        if not valid_data: return None
        return valid_data
    except Exception: return None

# -----------------------
# 質問マップの自動生成
# -----------------------
def generate_question_map(dataset, selected_categories=None):
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set()
    WEIGHT_URGENT, WEIGHT_HIGH, WEIGHT_MID, WEIGHT_LOW = 1000, 500, 100, 50

    common_questions_def = [
        ("alive_text", "現在もご存命ですか？", "common", WEIGHT_URGENT),
        ("age_20s", "現在、20代ですか？", "common", WEIGHT_HIGH), 
        ("age_30s", "現在、30代ですか？", "common", WEIGHT_HIGH),
        ("age_40s", "現在、40代ですか？", "common", WEIGHT_HIGH), 
        ("age_50s", "現在、50代ですか？", "common", WEIGHT_HIGH),
        ("actor_wikidata", "俳優ですか？", "occupation", WEIGHT_HIGH),
        ("singer_wikidata", "歌手ですか？", "occupation", WEIGHT_HIGH),
        ("politician_wikidata", "政治家ですか？", "occupation", WEIGHT_HIGH),
        ("from_tokyo", "出身は東京ですか？", "feature", WEIGHT_MID),
        ("from_kansai", "出身は関西（大阪・京都・兵庫）ですか？", "feature", WEIGHT_MID),
        ("blood_A", "血液型はA型ですか？", "feature", WEIGHT_MID),
        ("blood_B", "血液型はB型ですか？", "feature", WEIGHT_MID),
        ("blood_O", "血液型はO型ですか？", "feature", WEIGHT_MID),
        ("is_group_member", "グループやユニットの一員として活動していますか？", "activity", WEIGHT_MID),
    ]

    for key, text, category, weight in common_questions_def:
        if any(key in rec.get("features", {}) for rec in dataset):
            qm[category].append({"key": key, "text": text, "weight": weight, "check": lambda rec, k=key: rec.get("features",{}).get(k) == 1})
            added_keys.add(key)

    feature_questions_def = {
        "comedian": ("お笑い芸人ですか？", "occupation", WEIGHT_HIGH),
        "seiyuu": ("声優として活動していますか？", "occupation", WEIGHT_HIGH),
        "athlete": ("スポーツ選手ですか？", "occupation", WEIGHT_HIGH),
        "model": ("モデルとして活動していますか？", "occupation", WEIGHT_HIGH),
        "idol": ("アイドル活動をしていましたか？", "occupation", WEIGHT_HIGH),
        "youtuber": ("YouTuberとして活動していますか？", "occupation", WEIGHT_HIGH),
        "taiga": ("大河ドラマに出演しましたか？", "activity", WEIGHT_MID),
        "tokusatsu": ("特撮作品（仮面ライダーなど）に出演しましたか？", "activity", WEIGHT_MID),
        "movie": ("映画に出演していますか？", "activity", WEIGHT_MID),
        "anime": ("アニメ作品に関わっていますか？", "activity", WEIGHT_MID),
        "nhk": ("NHK（朝ドラなど）に出演したことがありますか？", "activity", WEIGHT_MID),
        "award": ("受賞歴がありますか？", "feature", WEIGHT_MID),
        "married": ("結婚していますか？", "feature", WEIGHT_MID),
    }

    allowed_feature_keys = set(feature_questions_def.keys())
    for key in allowed_feature_keys: 
        if key in feature_questions_def and key not in added_keys:
            text, category, weight = feature_questions_def[key]
            if any(key in rec.get("features", {}) for rec in dataset):
                qm[category].append({"key": key, "text": text, "weight": weight, "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1})
                added_keys.add(key)
    
    # 動的質問
    all_dynamic_keys = set()
    DYNAMIC_PREFIXES = ("noun_", "adj_", "verb_", "cat_", "work_")
    for rec in dataset:
        for key in rec.get("features", {}).keys():
            if key.startswith(DYNAMIC_PREFIXES): all_dynamic_keys.add(key)
    
    total_people = len(dataset)
    min_count, max_count = max(3, int(total_people * 0.002)), int(total_people * 0.90)
    
    PREFECTURES = {"北海道", "東京", "神奈川", "埼玉", "千葉", "愛知", "大阪", "京都", "福岡"} # 簡易版

    for key in all_dynamic_keys:
        count = sum(1 for rec in dataset if rec.get("features", {}).get(key) == 1)
        if not (min_count <= count <= max_count): continue
        if key in added_keys: continue
        
        q_text, cat_type, w = "", "activity", WEIGHT_MIN
        if key.startswith("cat_"):
            name = key[4:]
            if "出身" in name: q_text, cat_type, w = f"『{name.replace('出身の人物','')}』の出身ですか？", "feature", WEIGHT_MID
            elif "所属" in name: q_text, cat_type, w = f"『{name.replace('所属者','')}』に所属していますか？", "feature", WEIGHT_MID
            else: q_text = f"カテゴリ「{name}」に含まれますか？"
        elif key.startswith("noun_"):
            word = key[5:]
            if word in PREFECTURES: q_text, cat_type, w = f"『{word}』にゆかりがありますか？", "feature", WEIGHT_MID
            else: q_text = f"キーワード『{word}』に関連しますか？"
        elif key.startswith("work_"):
            q_text, cat_type = f"作品『{key[5:]}』に関連していますか？", "activity"

        if q_text:
            qm[cat_type].append({"key": key, "text": q_text, "weight": w, "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1})
            added_keys.add(key)

    return qm

# -----------------------
# 最適な質問を見つけるアルゴリズム
# -----------------------
def find_best_question(candidates, qm_dict, asked_keys):
    best_question, best_score = None, -1
    total_candidates = len(candidates)
    
    for cat, questions in qm_dict.items():
        for q in questions:
            if q["key"] in asked_keys: continue
            yes = sum(1 for c in candidates if q["check"](c))
            no = total_candidates - yes
            if yes == 0 or no == 0: continue
            score = (yes * no) * q.get("weight", 1.0)
            if score > best_score:
                best_score = score
                best_question = q

    if best_question: return best_question
    if total_candidates <= 5: return None
    # 最後の手段（ランダム）
    available = [q for cat in qm_dict.values() for q in cat if q["key"] not in asked_keys]
    return random.choice(available) if available else None

def calculate_mismatches(person, user_answers):
    mismatches = 0
    features = person.get("features", {})
    for key, ans in user_answers.items():
        has_feature = features.get(key) == 1
        if (ans == "y" and not has_feature) or (ans == "n" and has_feature): mismatches += 1
    return mismatches

def save_mistake_log(user_answers, candidates):
    log = {"timestamp": datetime.now().isoformat(), "answers": user_answers, "candidates": [c["name"] for c in candidates]}
    logs = []
    if os.path.exists(MISTAKE_LOG_FILE):
        try:
            with open(MISTAKE_LOG_FILE, "r", encoding="utf-8") as f: logs = json.load(f)
        except: pass
    logs.append(log)
    with open(MISTAKE_LOG_FILE, "w", encoding="utf-8") as f: json.dump(logs, f, ensure_ascii=False, indent=2)

# -----------------------
# 著名人検索本体ループ
# -----------------------
def akinator_play(dataset, selected_categories=None, max_questions=1000, analysis_size=100, dataset_path_for_new_entry=DATASET_FILE):
    valid_dataset = [p for p in dataset if p.get("features")]
    current_candidates = valid_dataset.copy()
    user_answers = {}
    history = [(current_candidates.copy(), set(), 0)] # candidates, asked_keys, count
    qm_dict = generate_question_map(valid_dataset, selected_categories)

    print(f"=== 🕵️ 人物検索開始 (候補: {len(current_candidates)}人) ===")
    
    while history:
        current_candidates, asked_keys, count = history[-1]
        
        # 終了条件
        if len(current_candidates) == 0:
            print("\n候補がいなくなりました。リカバリーモードへ移行します...")
            break # リカバリーへ
        
        if len(current_candidates) == 1:
            c = current_candidates[0]
            print(f"\n🎉 答え: {c['name']} ({count}問)")
            url = get_wikipedia_main_image(c['name'])
            if url: print(f"📷 Image: {url}")
            
            ans = input(f"正解ですか？ (y/n) > ").strip().lower()
            if ans in ("y", "yes"):
                print("✨ やりました！"); return [c]
            else:
                print("違いましたか..."); break # リカバリーへ

        # 質問選択 (★高速化: ランダムサンプリング)
        analysis_targets = current_candidates
        if len(current_candidates) > analysis_size:
            analysis_targets = random.sample(current_candidates, analysis_size)
            
        question = find_best_question(analysis_targets, qm_dict, asked_keys)
        
        if not question:
            print("有効な質問がなくなりました。上位候補を表示します。")
            for i, c in enumerate(current_candidates[:5], 1): print(f"{i}. {c['name']}")
            break

        print(f"\n[Q{count+1}] 残り{len(current_candidates)}人")
        ans = input(f"{question['text']} (y/n/u/b) > ").strip().lower()

        if ans in ("b", "back"):
            if len(history) > 1: history.pop(); print("<<< 戻りました"); continue
            else: print("これ以上戻れません"); continue
        
        val = "y" if ans in ("y", "yes") else "n" if ans in ("n", "no") else "u"
        user_answers[question['key']] = val
        
        next_candidates = []
        if val == "u": next_candidates = current_candidates[:]
        else:
            check_val = (val == "y")
            next_candidates = [c for c in current_candidates if question["check"](c) == check_val]
        
        new_asked = asked_keys.copy(); new_asked.add(question["key"])
        history.append((next_candidates, new_asked, count + 1))

    # --- リカバリー処理 ---
    print("\n🔄 類似人物を検索中...")
    near_misses = []
    for p in valid_dataset:
        if calculate_mismatches(p, user_answers) <= 3: near_misses.append(p)
    
    if near_misses:
        print(f"もしかして: {near_misses[0]['name']} さんですか？")
    else:
        print("特定できませんでした。")
        save_mistake_log(user_answers, current_candidates)
        correct_name = input("正解の人物名を入力してください (学習します): ").strip()
        if correct_name:
            fetch_and_add_new_person_data(correct_name, dataset_path=dataset_path_for_new_entry)

    return []

# -----------------------
# エントリポイント
# -----------------------
def run_step(step="collect", people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, **kwargs):
    step = step.lower()
    selected_categories = kwargs.get("categories", CATEGORIES)

    if step == "collect":
        return collect_people(categories=selected_categories, cmlimit=kwargs.get("cmlimit", 50),
                              depth=kwargs.get("depth", 1), sleep=kwargs.get("sleep", 1.5),
                              save_path=people_list_path, corresponding_dataset_path=dataset_path)
    elif step == "build":
        return build_dataset_parallel(people_list_path=people_list_path, dataset_path=dataset_path,
                                      limit=kwargs.get("limit", None), sleep=kwargs.get("sleep", 1.5),
                                      source_label=kwargs.get("source_label", "auto"))
    elif step == "refresh":
        return refresh_learned_data(dataset_path=dataset_path)
    elif step == "play":
        ds = load_dataset(dataset_path=dataset_path, min_feature_threshold=kwargs.get("min_feature_threshold", 5))
        if not ds: return None
        return akinator_play(ds, selected_categories=selected_categories,
                             max_questions=kwargs.get("max_questions", 1000),
                             analysis_size=kwargs.get("analysis_size", 100),
                             dataset_path_for_new_entry=dataset_path)
    else:
        raise ValueError("Unknown step")

if __name__ == "__main__":
    SLEEP, CMLIMIT, DEPTH, BUILD_LIMIT = 0.1, 50, 1, None
    MIN_FEATURE_THRESHOLD = 35
    
    try:
        print("--- 🤖 著名人特定プログラム ---")
        if not JANOME_TOKENIZER: sys.exit(1)

        selected_categories = choose_categories()
        dynamic_list = get_dynamic_cache_path(selected_categories, prefix="people_list")
        dynamic_ds = get_dynamic_cache_path(selected_categories, prefix="people_dataset")

        print(f"List: {dynamic_list} / DB: {dynamic_ds}")

        run_step("collect", categories=selected_categories, cmlimit=CMLIMIT, depth=DEPTH, sleep=SLEEP, people_list_path=dynamic_list, dataset_path=dynamic_ds)
        
        print("\n=== データセット構築 ===")
        run_step("build", categories=selected_categories, limit=BUILD_LIMIT, sleep=SLEEP, people_list_path=dynamic_list, dataset_path=dynamic_ds, source_label="auto")

        print("\n=== ゲーム開始 ===")
        run_step("play", categories=selected_categories, min_feature_threshold=MIN_FEATURE_THRESHOLD, people_list_path=dynamic_list, dataset_path=dynamic_ds)

    except KeyboardInterrupt: print("\n中断しました")
    except Exception as e: traceback.print_exc()