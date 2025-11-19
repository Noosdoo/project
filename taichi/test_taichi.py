import requests
import time
import json
import os
import re
import random
import wikipediaapi
from datetime import datetime # 日付処理のため
from concurrent.futures import ThreadPoolExecutor, as_completed # 並列処理用
import sys # 標準入出力のエンコーディング設定用

# 標準入出力のエンコーディングをUTF-8に設定
try:
    # ↓ 不正な文字(U+00A0)を除去しました
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
except (AttributeError, TypeError):
    # reconfigure がない環境 (例: IDLE) 向け
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
    print(f"Janomeの読み込み中に予gi期せぬエラー: {e}")
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
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    if collected is None:
        collected = set()
    cmtitle = f"Category:{category}"
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": cmtitle, "cmlimit": str(cmlimit), "format": "json"
    }
    cont = None
    while True:
        if cont: params.update(cont)
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"HTTPエラー: {e}"); return collected
        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。"); return collected
        try:
            data = res.json()
        except Exception as e:
            print(f"JSONデコード失敗: {e}"); return collected
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
    choice = input("> ").strip()
    if not choice:
        print("全カテゴリを対象にします。"); return CATEGORIES
    selected = []
    for part in choice.split(","):
        try:
            idx = int(part)-1
            if 0 <= idx < len(CATEGORIES): selected.append(CATEGORIES[idx])
        except: pass
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。"); return CATEGORIES
    print(f"選択されたカテゴリ: {', '.join(selected)}"); return selected

# -----------------------
# Step1: 全カテゴリから人物を収集して保存 
# -----------------------
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    target_categories = sorted(list(set(categories)))
    if os.path.exists(save_path):
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f)
            saved_categories = data.get("meta", {}).get("categories")
            people_list = data.get("people")
            if saved_categories == target_categories and people_list is not None:
                print(f"{save_path} が存在し、カテゴリが一致するため、collect はスキップします。")
                return people_list
            else:
                print("カテゴリが変更されたため、人物リストを再収集します。")
                if os.path.exists(DATASET_FILE):
                    print(f"古いデータセット {DATASET_FILE} をリセットします。")
                    os.remove(DATASET_FILE)
        except Exception as e:
            print(f"既存ファイルの形式が古いか壊れています: {e}。再収集します。")
            if os.path.exists(DATASET_FILE): os.remove(DATASET_FILE)

    print("=== カテゴリから人物リストを収集します ===")
    all_people = set()
    for cat in target_categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        print(f"  → {len(people)} 人取得")
        all_people.update(people); time.sleep(sleep)
    people_list = sorted(list(all_people))
    save_data = {
        "meta": {"categories": target_categories, "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "people": people_list
    }
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
        
        # P106 (職業)
        if "P106" in claims:
            occ = [] 
            for c in claims["P106"]:
                try:
                    v = c["mainsnak"]["datavalue"]["value"] 
                    if isinstance(v, dict) and "id" in v: occ.append(v["id"]) 
                except Exception: pass 
            if occ: result["occupation_qids"] = occ
            
        # P21 (性別)
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v: result["gender_qid"] = v["id"]
            except Exception: pass
            
        # P569 (birth time)
        if "P569" in claims:
            try:
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["birth_time"] = t
            except Exception: pass
            
        # P570 (death time)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["death_time"] = t
            except Exception: pass
            
        # P19 (birth place)
        if "P19" in claims:
            try:
                v = claims["P19"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v:
                    result["birth_place_qid"] = v["id"] 
            except Exception: pass
            
        # P69 (education)
        if "P69" in claims:
            edu_qids = []
            for c in claims["P69"]:
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    if isinstance(v, dict) and "id" in v: edu_qids.append(v["id"])
                except Exception: pass
            if edu_qids: result["education_qids"] = edu_qids 

        # P166 (award received)
        if "P166" in claims:
            award_qids = []
            for c in claims["P166"]:
                    try:
                        v = c["mainsnak"]["datavalue"]["value"]
                        if isinstance(v, dict) and "id" in v: award_qids.append(v["id"])
                    except Exception: pass
            if award_qids: result["award_qids"] = award_qids 
        
        return result
    except Exception:
        return None

# -----------------------
# [追加] Summaryから名詞を抽出する (Janome使用)
# -----------------------
def extract_nouns_from_summary(summary):
    if not JANOME_TOKENIZER or not summary:
        return {}
    
    features = {}
    
    # 形態素解析を実行
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary)
    except Exception:
        return {} # パースに失敗した

    # 抽出する品詞
    TARGET_POS = ('名詞', '一般')
    TARGET_POS_PROPER = ('名詞', '固有名詞') # 固有名詞

    # ストップワード (一般的すぎて質問にならない単語)
    STOP_WORDS = {
        'こと', 'もの', 'ため', '人物', '概要', '日本', '活動', '出身',
        '現在', '自身', 'ほか', '以降', '選手', '俳優', '女優', '芸人',
        '声優', 'モデル', 'アイドル', 'メンバー', 'グループ', '監督', '主演',
        '日本', '日本人', '番組', 'テレビ', 'ドラマ', '映画', '作品', '名前',
        'さん', '男性', '女性', '一つ', '一つ', '氏名', '関係', '存在', '世界',
        '全国', '歴史', '時代', '今日', '連続', '以上', '以下', '約', '程度',
        '数', '人', '名', '回', '月', '日', '年'
    }

    for token in tokens:
        pos_parts = token.part_of_speech.split(',')
        
        # 「名詞,一般」または「名詞,固有名詞」を抽出
        if (pos_parts[0], pos_parts[1]) == TARGET_POS or \
           (pos_parts[0], pos_parts[1]) == TARGET_POS_PROPER:
            
            noun = token.surface # 単語 (例: 'サッカー')
            
            # 2文字以上で、ストップワードでないもの
            if len(noun) > 1 and noun not in STOP_WORDS:
                # features に "noun_サッカー" = 1 のように保存
                features[f"noun_{noun}"] = 1
                
    return features

# -----------------------
# summaryからキーワードベースで特徴を抽出 
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

def extract_features_from_summary(summary):
    """
    Janomeを使い、文章から特徴（名詞・形容詞・動詞）を抽出する。
    (元の extract_nouns_from_summary からの拡張版)
    """
    if not JANOME_TOKENIZER or not summary:
        return {}
    
    features = {}
    
    # 形態素解析を実行
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary)
    except Exception:
        return {} # パースに失敗した

    # 抽出する品詞と、特徴キーのプレフィックス
    TARGET_POS_TYPES = {
        ('名詞', '一般'): 'noun_',
        ('名詞', '固有名詞'): 'noun_',
        ('形容詞', '自立'): 'adj_', # 例: 「若い」「美しい」
        ('動詞', '自立'): 'verb_'  # 例: 「歌う」「走る」
    }

    # ストップワード (一般的すぎて質問にならない単語)
    # 元のSTOP_WORDSに、動詞の基本形などを追加
    STOP_WORDS = {
        'こと', 'もの', 'ため', '人物', '概要', '日本', '活動', '出身',
        '現在', '自身', 'ほか', '以降', '選手', '俳優', '女優', '芸人',
        '声優', 'モデル', 'アイドル', 'メンバー', 'グループ', '監督', '主演',
        '日本', '日本人', '番組', 'テレビ', 'ドラマ', '映画', '作品', '名前',
        'さん', '男性', '女性', '一つ', '一つ', '氏名', '関係', '存在', '世界',
        '全国', '歴史', '時代', '今日', '連続', '以上', '以下', '約', '程度',
        '数', '人', '名', '回', '月', '日', '年',
        # 動詞・形容詞のストップワードを追加
        'する', 'いる', 'ある', 'なる', 'ない', 'よい', 'できる', 'ない', 'いう',
        '行う', '行う', '行う', 'おこなう', '持つ', '行く'
    }


    for token in tokens:
        pos_parts = token.part_of_speech.split(',')
        
        # (品詞, 品詞細分類1) のタプルを作成
        pos_tuple = (pos_parts[0], pos_parts[1])
        
        # ターゲットとする品詞かどうかチェック
        if pos_tuple in TARGET_POS_TYPES:
            
            # 動詞や形容詞は「基本形」 (例: '美しい') を使う
            # 名詞は「表層形」 (例: 'サッカー') を使う
            if pos_parts[0] in ('形容詞', '動詞'):
                word = token.base_form
            else:
                word = token.surface
            
            # 2文字以上で、ストップワードでないもの
            if len(word) > 1 and word not in STOP_WORDS:
                
                # 'noun_', 'adj_', 'verb_' のいずれかのプレフィックスを取得
                prefix = TARGET_POS_TYPES[pos_tuple] 
                
                # features に "noun_サッカー" や "adj_若い" のように保存
                features[f"{prefix}{word}"] = 1
                
    return features

# -----------------------
# Step2: people list -> build dataset 
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
# Step2: build dataset 並行処理版
# -----------------------
def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                             limit=None, max_workers=150, sleep=0.1):
    """
    並列処理でデータセットを構築する。
    limit=None の場合、全件を対象とする。
    """
    people = load_people_list(people_list_path)
    if people is None:
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None
    
    if JANOME_TOKENIZER is None:
        print("Janomeが読み込まれていないため、データ構築をスキップします。")
        return None

    # 既存データの読み込み
    existing = {}
    if os.path.exists(dataset_path):
        try:
            with open(dataset_path, "r", encoding="utf-8") as f:
                existing = {p["name"]: p for p in json.load(f)}
                print(f"{len(existing)} 件の既存データを読み込みました。未処理のみ並列処理します。")
        except Exception as e:
            print(f"既存データ読み込み失敗: {e}")
            existing = {}

    # 処理対象を絞る
    # limit が None の場合は全件 (people) が対象
    targets = people
    if limit is not None:
        targets = targets[:limit]

    # 既存データにない、または features がない人物のみを処理対象とする
    targets_to_process = [n for n in targets if n not in existing or not existing[n].get("features")]
    
    print(f"データセット総件数: {len(targets)} 件中、処理対象: {len(targets_to_process)} 件")


    # スレッドで個別処理
    def process_person(name):
        try:
            wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
            page = wiki.page(name)
            if not page.exists():
                search_results = wiki.search(name)
                if search_results:
                    best_match = search_results[0]
                    page = wiki.page(best_match)
                else:
                    return {"name": name, "error": "ページなし"}

            rec = {"name": name, "summary": page.summary, "features": None, "wikidata": None}
            
            # 1. キーワードベースの特徴抽出
            features = extract_features_from_summary(page.summary)

            # 2. [★変更点★] Janomeを使って名詞を抽出し、featuresにマージする
            noun_features = extract_nouns_from_summary(page.summary)
            if noun_features:
                features.update(noun_features)
            
            # --- 名前構造 ---
            if re.search(r'[ァ-ヶ]', name):
                features["has_katakana"] = 1
            if re.fullmatch(r'[ぁ-ん]+', name):
                features["is_hiragana_only"] = 1
            rec["features"] = features

            # --- Wikidata取得 ---
            wikibase_id = get_wikibase_item_from_wikipedia(name)
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd
                if wd:
                    # 性別
                    g = wd.get("gender_qid")
                    if g == "Q6581097":
                        features["gender"] = "male"
                    elif g == "Q6581072":
                        features["gender"] = "female"
                        
                    # 年齢層
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

                    # 職業
                    occ_qs = wd.get("occupation_qids", [])
                    if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]):
                        features["actor_wikidata"] = 1
                    if any(q in occ_qs for q in ["Q177220", "Q639669", "Q10800557"]):
                        features["singer_wikidata"] = 1
                    if "Q82955" in occ_qs: 
                        features["politician_wikidata"] = 1

                    # 出身地
                    place_qid = wd.get("birth_place_qid")
                    TOKYO_QIDS = {"Q1490", "Q1228", "Q11103005", "Q200000", "Q200072"}
                    KANSAI_QIDS = {"Q172582", "Q16997", "Q486245", "Q132640", "Q132643"}

                    if place_qid in TOKYO_QIDS:
                        features["from_tokyo"] = 1
                    elif place_qid in KANSAI_QIDS:
                        features["from_kansai"] = 1

                    # 学歴
                    edu_qids = wd.get("education_qids", [])
                    if "Q7981" in edu_qids: features["grad_todai"] = 1
                    elif "Q174019" in edu_qids: features["grad_waseda"] = 1
                    elif "Q302302" in edu_qids: features["grad_keio"] = 1

                    # 受賞歴
                    award_qids = wd.get("award_qids", [])
                    if "Q1138032" in award_qids:
                        features["award_shiju"] = 1

            return rec

        except Exception as e:
            return {"name": name, "error": str(e)}


    # 並列実行
    new_records = []
    processed_count = 0
    total_to_process = len(targets_to_process)
    
    if total_to_process == 0:
        print("処理対象の人物がいません。データセットは最新です。")
        return list(existing.values())

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {executor.submit(process_person, name): name for name in targets_to_process}
        
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            processed_count += 1
            try:
                rec = future.result()
                new_records.append(rec)
                if "error" in rec:
                    print(f"[{processed_count}/{total_to_process}] × {name}: {rec['error']}")
                else:
                    print(f"[{processed_count}/{total_to_process}] ✓ {name}")
            except Exception as e:
                print(f"[{processed_count}/{total_to_process}] ⚠ {name}: {e}")
            time.sleep(sleep)  # 過剰アクセス防止の軽いディレイ

    # 結合と保存
    merged_data = existing.copy()
    for rec in new_records:
        merged_data[rec["name"]] = rec
        
    final_dataset = list(merged_data.values())

    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(final_dataset, f, ensure_ascii=False, indent=2)

    print(f"データセットを保存しました: {dataset_path}（合計 {len(final_dataset)} 件）")
    return final_dataset


# -----------------------
# Step3: アキネーター本体
# -----------------------
def load_dataset(dataset_path=DATASET_FILE, min_feature_threshold=5):
    """
    データセットを読み込む。
    [改変] features の数が min_feature_threshold 未満の人物を除外する。
    """
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset_parallel を実行してください。")
        return None
    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # 1. まず features が取得できた有効なデータのみを抽出
            valid_data = [d for d in data if d.get("features")]
            
            # 2. [追加] 特徴量の数が閾値以上の人のみフィルタリング
            filtered_data = [
                d for d in valid_data 
                if len(d.get("features", {})) >= min_feature_threshold
            ]
            
            print(f"データセット読み込み: {len(data)}件中、有効データ {len(valid_data)}件")
            print(f"  → 特徴量が {min_feature_threshold} 個未満の人を除外し、{len(filtered_data)}件をゲーム対象にします。")
            
            if len(filtered_data) == 0:
                print("エラー: 閾値が厳しすぎるか、有効なデータがありません。")
                return None
                
            return filtered_data
            
    except Exception as e:
        print(f"データセットの読み込みに失敗しました: {e}")
        return None

# -----------------------
# 質問マップの自動生成 (質問マスターリストの作成)
# [★変更点★] Janomeによる動的質問生成を追加
# -----------------------
def generate_question_map(dataset, selected_categories=None):
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set() 

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

    for key, text, category in common_questions_def:
        # データセット全体にその特徴を持つ人が一人でもいれば、質問マスターリストに追加
        key_exists = any(key in rec.get("features", {}) for rec in dataset)
        if key_exists and key not in added_keys:
            qm[category].append({
                "key": key, "text": text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)

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

    # カテゴリと質問キーの対応表 (省略)
    CATEGORY_TO_FEATURE_MAP = {
        "日本の俳優": ["taiga", "tokusatsu", "movie", "action", "stage", "nhk", "award", "cm", "married"],
        "日本の女優": ["taiga", "romance_drama", "movie", "stage", "nhk", "award", "model", "cm", "married"],
        "お笑い芸人": ["comedian", "youtuber", "movie", "stage", "mc", "radio", "married"],
        # ... 他のカテゴリも同様に定義 ...
    }
    
    # カテゴリ選択に基づくフィルタリング
    allowed_feature_keys = set()
    if not selected_categories or len(selected_categories) == len(CATEGORIES):
        allowed_feature_keys = set(feature_questions_def.keys())
    else: 
        for cat in selected_categories:
            allowed_feature_keys.update(CATEGORY_TO_FEATURE_MAP.get(cat, []))

    # 質問マップに追加
    for key in allowed_feature_keys: 
        if key in feature_questions_def and key not in added_keys: 
            text, category = feature_questions_def[key] 
            # データセット全体にその特徴を持つ人が一人でもいれば、質問マスターリストに追加
            if any(key in rec.get("features", {}) for rec in dataset):
                qm[category].append({
                    "key": key, "text": text,
                    "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
                })
                added_keys.add(key)
        
    # [★ここからが改善箇所★] --------------------------------
    # 3. データセットから "noun_", "adj_", "verb_" キーを動的に読み込み質問を生成する
    
    print("データセットをスキャンして、動的な質問（名詞・形容詞・動詞）を生成します...")
    all_dynamic_keys = set()
    
    # 対象とするプレフィックス
    DYNAMIC_PREFIXES = ("noun_", "adj_", "verb_")
    
    for rec in dataset:
        if not rec.get("features"): continue
        for key in rec["features"].keys():
            # プレフィックスのいずれかで始まるキーを収集
            if key.startswith(DYNAMIC_PREFIXES):
                all_dynamic_keys.add(key)
    
    print(f"   → {len(all_dynamic_keys)} 種類のユニークな動的特徴を発見しました。")

    # フィルタリング:
    # 質問として「有用」な特徴だけを厳選する
    
    total_people = len(dataset)
    
    # [★改善点★] 閾値を緩和する
    # 終盤の絞り込みのため、2人でも持っていれば質問候補とする
    min_count = max(2, int(total_people * 0.001)) 
    # 95%が持つような一般的すぎる特徴は除外
    max_count = int(total_people * 0.95)      
    
    useful_dynamic_keys = set()
    for key in all_dynamic_keys:
        # このキーを持っている人数をカウント
        count = sum(1 for rec in dataset if rec.get("features", {}).get(key) == 1)
        
        # [★改善点★] 変更された閾値で判定
        if min_count <= count <= max_count:
            useful_dynamic_keys.add(key)

    print(f"   → フィルタリング後、有用な質問を {len(useful_dynamic_keys)} 件、質問マスターリストに追加します。")

    for key in useful_dynamic_keys:
        if key in added_keys: continue # 既に手動で定義されていればスキップ
        
        question_text = ""
        
        # [★改善点★] キーの種別に応じて質問文を生成
        
        if key.startswith("noun_"):
            noun = key[len("noun_"):] # "noun_サッカー" -> "サッカー"
            question_text = f"『{noun}』に（深く）関連していますか？"
        
        elif key.startswith("adj_"):
            adj = key[len("adj_"):] # "adj_美しい" -> "美しい"
            question_text = f"『{adj}』というイメージ/特徴がありますか？"
            
        elif key.startswith("verb_"):
            verb = key[len("verb_"):] # "verb_歌う" -> "歌う"
            question_text = f"『{verb}』という活動をしましたか（しますか）？"

        
        if question_text:
            # 質問を追加
            # (どのカテゴリに入れるかはプロジェクトの設計によりますが、一旦 "activity" に入れます)
            qm["activity"].append({
                "key": key, 
                "text": question_text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)
        
    # [★ここまでが改善箇所★] --------------------------------
        
    print(f"質問マスターリストを生成しました (合計 {len(added_keys)} 種類)")
    return qm

# -----------------------
# 最適な質問を見つけるアルゴリズム (質問の厳選)
# [★変更点★: スコア0の質問を保険として保持する]
# -----------------------
def find_best_question(candidates_for_analysis, qm_dict, asked_keys):
    """
    【重要】解析用候補者リスト(candidates_for_analysis)を最も効率よく
    半分(50/50)に分割できる質問を厳選します。
    [修正] スコアが0の質問も保持し、他にない場合の保険とします。
    """
    best_question = None
    best_score = -1 # スコアの初期値

    # [追加] 分割できない質問 (スコア0) を保持するリスト
    zero_score_questions = []

    # qm_dict (質問マスターリスト) をループ
    for q_category in qm_dict.values():
        for question in q_category:
            key, test = question.get("key"), question.get("check")

            if key in asked_keys:
                continue

            # --- シミュレーション (解析用候補者リストで行う) ---
            yes_count = 0
            no_count = 0
            for c in candidates_for_analysis:
                if c.get("features") is None: continue
                if test(c):
                    yes_count += 1
                else:
                    no_count += 1
            
            # 分割の良さをスコア化 (50/50に近いほど高得点)
            score = yes_count * no_count
            
            if score > best_score:
                best_score = score
                best_question = question
            
            # [変更] 
            # スコアが0 (全員Yesか全員No) でも、
            # まだ聞いていない質問ならリストに保持
            elif score == 0:
                zero_score_questions.append(question)
                
    # [変更]
    # もし最適な質問 (score > 0) が見つからなかった場合、
    # スコア0の質問が残っていれば、それをランダムに返す
    if best_question is None and zero_score_questions:
        # print("[デバッグ] 最適な質問がなかったため、スコア0の質問から選びます。")
        return random.choice(zero_score_questions)
        
    return best_question


# -----------------------
# アキネーター本体ループ (カスタムロジック)
# [★変更点★: 3人以下で提案 / サンプリング(analysis_size)を廃止]
# -----------------------
def akinator_play(dataset, selected_categories=None, max_questions=1000, analysis_size=100):
    """
    [改変版]
    候補者が3人以下になったら質問を中止し、候補を提案する。
    [★変更★] analysis_sizeによるサンプリングを廃止し、常に候補者全員を分析する。
    """
    # 候補者リストの初期化 (全データセット)
    candidates = dataset.copy()
    
    # 質問マスターリストの生成
    qm_dict = generate_question_map(dataset, selected_categories)
    
    print(f"=== 🕵️ アキネーター開始 (3人提案/候補者全員・全力分析モード) ===")
    print(f"※ 毎回、残りの候補者全員 ({len(candidates)}人) を分析して最適な質問を厳選します。")
    print("回答は「はい(y) / いいえ(n) / わからない(u)」のいずれかを入力してください。")
    print("---")
    
    asked_keys = set()
    asked_count = 0

    # ループの継続条件は「候補者が3人より多い」
    while len(candidates) > 3 and asked_count < max_questions:
        
        # -----------------------------------------------------------------
        # [★変更点★] サンプリングをやめ、常に残りの候補者全員を解析する
        # -----------------------------------------------------------------
        candidates_for_analysis = candidates
        # -----------------------------------------------------------------
            
        # 2. 解析対象に基づいて最適な質問を特定
        # (計算に時間がかかる場合があります...)
        if len(candidates_for_analysis) > 500:
            print(f"\n[... {len(candidates_for_analysis)}人から最適な質問を計算中 ...]")
        
        question = find_best_question(candidates_for_analysis, qm_dict, asked_keys)
        
        if question is None:
            print("\n質問が尽きるか、残りの候補で質問が分けられなくなりました。残りの候補から推測します...")
            break

        key, q_text, test = question["key"], question["text"], question["check"]
        
        # 解析対象における分割効率を表示 (質問選定の根拠として)
        yes_count_analysis = sum(1 for c in candidates_for_analysis if test(c))
        no_count_analysis = len(candidates_for_analysis) - yes_count_analysis
        
        print(f"\n[質問 {asked_count+1}] (候補: {len(candidates)}人 | 全員分析の分割予測: {yes_count_analysis} / {no_count_analysis})")
        ans = input(q_text + " （y/n/u） > ").strip().lower()
        
        asked_keys.add(key)
        
        # 3. 回答に基づいて候補者全体を絞り込む
        if ans in ("はい", "y"):
            candidates = [c for c in candidates if test(c)]
        elif ans in ("いいえ", "n"):
            candidates = [c for c in candidates if not test(c)]
        elif ans in ("わからない", "u"):
            pass # 絞り込まない
        else:
            print("無効な回答です。スキップします。")
            continue

        asked_count += 1
        
        # 絞り込み後の候補者数を確認
        if len(candidates) == 0:
            print("\n候補者がいなくなってしまいました。質問の回答に矛盾があった可能性があります。")
            break
        elif len(candidates) < 10:
             print(f"(現在の候補数: {len(candidates)}人 - {', '.join([c['name'] for c in candidates])})")
        else:
             print(f"(現在の候補数: {len(candidates)}人)")


    # -----------------------------
    # 最終的な提案ロジック
    # -----------------------------
    print("\n===============================")
    
    if len(candidates) > 0 and len(candidates) <= 3:
        # 目的の「3人以下」になった場合
        print(f"🎉 候補者が {len(candidates)} 人に絞り込まれました！")
        print(f"あなたが思い浮かべた人物は、この中にいますか？")
        print("-------------------------------")
        for i, c in enumerate(candidates, 1):
            print(f"**{i}. 『{c['name']}』**")
            
    elif len(candidates) > 3:
        # 質問が尽きたが、4人以上残った場合
        print(f"🤔 {asked_count}回の質問では3人まで絞り込めませんでした。")
        print(f"=== 最終候補トップ{min(len(candidates), 5)} ===")
        for i, c in enumerate(candidates[:5], 1):
            print(f"{i}. **{c['name']}**")
        print(f"（合計 {len(candidates)}人が残りました）")
        
    elif len(candidates) == 0:
        # 候補者が0人になった場合
        print("😢 最終的な候補者が0人になってしまいました。")
        
    print("===============================")
    return candidates


# -----------------------
# エントリポイント用関数
# -----------------------
def run_step(step="collect", **kwargs):
    step = step.lower()
    if step == "collect":
        return collect_people(categories=kwargs.get("categories", CATEGORIES),
                              cmlimit=kwargs.get("cmlimit", 50),
                              depth=kwargs.get("depth", 1),
                              sleep=kwargs.get("sleep", 0.8))
    elif step == "build":
        return build_dataset_parallel(limit=kwargs.get("limit", None),
                                      sleep=kwargs.get("sleep", 0.8))
    elif step == "play":
        # [変更] 閾値を受け取る
        min_features = kwargs.get("min_feature_threshold", 5) 
        ds = load_dataset(min_feature_threshold=min_features) # 閾値を渡す
        
        if not ds: return None
        selected_categories = kwargs.get("selected_categories")
        return akinator_play(ds, 
                             selected_categories=selected_categories, 
                             max_questions=kwargs.get("max_questions", 1000),
                             analysis_size=kwargs.get("analysis_size", 100)) # analysis_sizeはplayでは使われなくなったが、run_stepのI/Fのため残す
    else:
        raise ValueError("step must be one of: collect, build, play")

# -----------------------
# 実行部分
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ ---
    SLEEP = 0.01     # APIアクセス間隔 (秒)
    CMLIMIT = 50
    DEPTH = 1
    BUILD_LIMIT = None  
    MAX_QUESTIONS = 1000
    ANALYSIS_SIZE = 100 # (この設定は「全力分析モード」では使われません)

    # [追加] データの閾値
    # -----------------------------------------------------------------
    # ここに設定した数（例: 2個）未満の特徴しか持たない人物は、
    # ゲーム開始前に除外されます。
    MIN_FEATURE_THRESHOLD = 2
    # -----------------------------------------------------------------


    # --- 実行フロー ---
    try:
        print("--- 🤖 Akinator風人物特定プログラム（動的質問生成＋全力分析モード） ---")
        
        if JANOME_TOKENIZER is None:
            print("Janomeが読み込まれていないため、実行を停止します。")
            sys.exit(1)
        
        selected_categories = choose_categories()
        
        run_step("collect", 
                 categories=selected_categories, 
                 cmlimit=CMLIMIT, 
                 depth=DEPTH, 
                 sleep=SLEEP)
        
        print("\n=== データセットの構築/更新（全件解析＋Janome名詞抽出） ===")
        print("注意: 初回実行時、人物リストが膨大な場合、この処理には時間がかかります。")
        run_step("build", 
                 limit=BUILD_LIMIT, 
                 sleep=SLEEP)
        
        print("\n=== ゲームスタート ===")
        # [変更] 閾値を渡す
        run_step("play", 
                 selected_categories=selected_categories, 
                 max_questions=MAX_QUESTIONS,
                 analysis_size=ANALYSIS_SIZE,
                 min_feature_threshold=MIN_FEATURE_THRESHOLD) # 👈 追加
                 
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")