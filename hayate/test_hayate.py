import requests
import time
import json
import os
import re
import unicodedata
import random
import wikipediaapi
import traceback
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# --- 標準入出力のエンコーディング設定 ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
except (AttributeError, TypeError):
    pass

# --- Janome（形態素解析）のインポート ---
try:
    from janome.tokenizer import Tokenizer
    JANOME_TOKENIZER = Tokenizer()
    print("Janome (形態素解析) を読み込みました。")
except ImportError:
    print("---------------------------------------------------------------")
    print("エラー: Janomeがインストールされていません。")
    print("動的な質問生成を利用するには、`pip install -U janome` を実行してください。")
    print("---------------------------------------------------------------")
    JANOME_TOKENIZER = None
except Exception as e:
    print(f"Janomeの読み込み中に予期せぬエラー: {e}")
    JANOME_TOKENIZER = None

# --- グローバル定数 ---
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
HEADERS = {"User-Agent": USER_AGENT}

# 取得対象カテゴリ (主要なもの)
CATEGORIES = [
    "日本の俳優", "日本の女優", "お笑い芸人", "日本の声優", "日本のアイドル", "日本のモデル", "日本の歌手",
    "日本の作曲家", "日本の映画監督", "日本のアナウンサー", "日本のYouTuber",
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の科学者", "日本の医師",
    "日本の政治家", "日本の経営者", "日本の起業家", "日本の弁護士",
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本のオリンピック選手",
    "日本の画家", "日本の建築家", "日本のデザイナー", "日本の音楽家",
]

# 静的特徴抽出用のキーワード
FEATURE_KEYWORDS = {
    "taiga": ["大河ドラマ", "大河"], "tokusatsu": ["仮面ライダー", "スーパー戦隊", "ウルトラマン", "特撮"],
    "romance_drama": ["恋愛", "ラブストーリー", "恋人"], "movie": ["映画", "劇場版"],
    "action": ["アクション", "殺陣"], "seiyuu": ["声優", "アニメで声"],
    "singer": ["歌手", "シンガー", "ボーカル"], "stage": ["舞台", "ミュージカル", "劇団"],
    "model": ["モデル", "ファッションモデル"], "comedian": ["お笑い", "芸人", "コント"],
    "anime": ["アニメ"], "hollywood": ["ハリウッド", "海外映画"],
    "idol": ["アイドル", "グループ"], "award": ["受賞", "賞を受賞", "主演男優賞", "最優秀"],
    "nhk": ["NHK", "連続テレビ小説", "朝ドラ"], "youtuber": ["YouTube", "チャンネル"],
    "director": ["監督"], "athlete": ["選手", "オリンピック", "サッカー", "野球", "柔道"],
    "politician": ["政治家", "衆議院", "参議院", "首相"], "mc": ["司会", "MC", "司会者"],
    "radio": ["ラジオ", "パーソナリティ"], "cm": ["CM", "コマーシャル"],
    "married": ["結婚", "妻", "夫"], "author": ["執筆", "出版", "著書", "エッセイ"],
}

# 動的特徴抽出 (Janome) 用の除外単語
STOP_WORDS = {
    'こと', 'もの', 'ため', '人物', '概要', '日本', '活動', '出身', '現在', '自身', 'ほか', '以降',
    '選手', '俳優', '女優', '芸人', '声優', 'モデル', 'アイドル', 'メンバー', 'グループ', '監督', '主演',
    '日本人', '番組', 'テレビ', 'ドラマ', '映画', '作品', '名前', 'さん', '男性', '女性', '一つ', '氏名',
    '関係', '存在', '世界', '全国', '歴史', '時代', '今日', '連続', '以上', '以下', '約', '程度',
    '数', '人', '名', '回', '月', '日', '年', 'する', 'いる', 'ある', 'なる', 'ない', 'よい', 'できる',
    'いう', '行う', 'おこなう', '持つ', '行く', '当時', '一方', '他', '影響', '人気', 'ファン', '評価',
    'デビュー', '出演', '結成', '所属', '参加', '発表', '発売', '公開', '優勝', '受賞', '選出', '就任',
    '引退', '死去', '結婚', '誕生', '卒業', '在住', '在学', '地方', '問題', '理由', '意味', '最初',
    '最後', '方法', '結果', '種類', '愛称', '本人', '彼', '彼女', '私', '的', 'ため', '万', '円',
    '平成', '昭和', '大正', '明治', '東京', '大阪', '京都', 'アメリカ', 'イギリス', 'フリー', '公式'
}

# カテゴリ除外キーワード
IGNORE_CAT_KEYWORDS = {
    "存命人物", "死去した人物", "日本の人物", "曖昧さ回避", "リダイレクト", "人物", "生年", "没年",
    "年没", "年生", "世紀没", "世紀生", "各年の", "ウィキデータ", "ID", "記事", "テンプレート", "出典",
    "外部リンク", "カテゴリ", "リンク", "英語版ウィキ", "日本語版ウィキ", "ウィキペディア", "コモンズ",
    "スタブ", "項目", "一覧", "ポータル", "参考文献", "脚注", "注釈", "引用", "プロジェクト", "編集"
}

# Wikidata関連のQID定数
QID_GENDER_MALE = "Q6581097"
QID_GENDER_FEMALE = "Q6581072"
TOKYO_QIDS = {"Q1490", "Q1228", "Q11103005", "Q200000", "Q200072"}
KANSAI_QIDS = {"Q172582", "Q16997", "Q486245", "Q132640", "Q132643", "Q487545"}
FAMOUS_UNIV_QIDS = {
    "Q7842": "edu_todai", "Q336224": "edu_kyodai", "Q379744": "edu_waseda",
    "Q333738": "edu_keio", "Q1138439": "edu_meiji",
}

# --- ユーティリティ関数 ---

def get_dynamic_cache_path(categories_list, prefix="people_list"):
    """選択されたカテゴリリストから一意のハッシュを生成し、キャッシュファイル名を返す。"""
    sorted_cats = sorted(list(set(categories_list)))
    cat_string = json.dumps(sorted_cats)
    hash_hex = hashlib.md5(cat_string.encode('utf-8')).hexdigest()
    return f"{prefix}_{hash_hex}.json"

def is_person_page(title):
    """人物ページかどうかの簡易判定"""
    exclude_keywords = ["一覧", "号", "歴史", "編", "協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]
    return not any(k in title for k in exclude_keywords)

def clean_text(text):
    """テキストから不要な文字を除去し、正規化する"""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1F\x7F\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def load_people_list(people_list_path):
    """人物リストJSONを読み込む"""
    if not os.path.exists(people_list_path):
        return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get("people")
        elif isinstance(data, list):
            return data
        return None
    except Exception:
        return None

def choose_categories():
    """ユーザーにカテゴリを選択させる"""
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切り (例: 1,3,5) / 全ての場合は Enter")
    choice = input("> ").strip()
    if not choice:
        print("全カテゴリを対象にします。")
        return CATEGORIES
    selected = []
    for part in choice.split(","):
        try:
            idx = int(part) - 1
            if 0 <= idx < len(CATEGORIES):
                selected.append(CATEGORIES[idx])
        except:
            pass
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。")
        return CATEGORIES
    print(f"選択されたカテゴリ: {', '.join(selected)}")
    return selected

# --- Wikipedia/Wikidata API 関連関数 ---

def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=1.5):
    """指定されたカテゴリのメンバーを再帰的に取得する"""
    if collected is None:
        collected = set()
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": f"Category:{category}", "cmlimit": str(cmlimit), "format": "json"
    }
    cont = None
    while True:
        if cont:
            params.update(cont)
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            if res.status_code == 403:
                print("403 Forbidden: Wikipediaがアクセスを拒否しました。")
                break
            data = res.json()
        except Exception as e:
            print(f"HTTPエラー ({category}): {e}")
            break
        
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title:
                continue
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth - 1, collected=collected, sleep=sleep)
            elif is_person_page(title):
                collected.add(title)
        
        if "continue" in data:
            cont = data["continue"]
            time.sleep(sleep)
        else:
            break
    return collected

def get_wikibase_item_from_wikipedia(title):
    """WikipediaタイトルからWikidata QIDを取得する"""
    params = {"action": "query", "titles": title, "prop": "pageprops", "format": "json"}
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=10)
        pages = res.json().get("query", {}).get("pages", {})
        if pages:
            page = next(iter(pages.values()))
            return page.get("pageprops", {}).get("wikibase_item")
    except Exception:
        pass
    return None

def fetch_wikidata_entity(wikibase_id):
    """Wikidata QIDから主要な属性を取得する"""
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=10)
        entity = res.json().get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {"claims": claims} # 汎用性のためにclaims全体を保持

        # P106 (職業)
        if "P106" in claims:
            result["occupation_qids"] = [
                c["mainsnak"]["datavalue"]["value"]["id"]
                for c in claims["P106"] if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            ]
        # P21 (性別)
        if "P21" in claims:
            try: result["gender_qid"] = claims["P21"][0]["mainsnak"]["datavalue"]["value"]["id"]
            except Exception: pass
        # P569 (生年月日)
        if "P569" in claims:
            try: result["birth_time"] = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
            except Exception: pass
        # P570 (死亡年月日)
        if "P570" in claims:
            try: result["death_time"] = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
            except Exception: pass
        # P19 (出生地)
        if "P19" in claims:
            try: result["birth_place_qid"] = claims["P19"][0]["mainsnak"]["datavalue"]["value"]["id"]
            except Exception: pass
        # P69 (学歴)
        if "P69" in claims:
            result["education_qids"] = [
                c["mainsnak"]["datavalue"]["value"]["id"]
                for c in claims["P69"] if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            ]
        # P166 (受賞)
        if "P166" in claims:
            result["award_qids"] = [
                c["mainsnak"]["datavalue"]["value"]["id"]
                for c in claims["P166"] if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            ]
        return result
    except Exception:
        return None

# --- 特徴抽出関数 ---

def extract_features_from_summary(summary):
    """【静的】サマリーからキーワードベースで特徴を抽出"""
    s = summary or ""
    features = {k: int(any(kw in s for kw in keywords)) for k, keywords in FEATURE_KEYWORDS.items()}
    
    m = re.search(r'(\d{4})年', s)
    if m:
        try: features["birth_year"] = int(m.group(1))
        except: pass
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1
    return features

def extract_dynamic_features_from_summary(summary):
    """【動的】Janomeを使い、サマリーから名詞・形容詞・動詞を抽出"""
    if not JANOME_TOKENIZER or not summary:
        return {}
    
    features = {}
    try:
        tokens = JANOME_TOKENIZER.tokenize(summary)
    except Exception as e:
        # print(f"[DEBUG-DYNAMIC] Janome.tokenize(summary) でエラー: {e}")
        return {}

    TARGET_POS_TYPES = {
        ('名詞', '一般'): 'noun_', ('名詞', '固有名詞'): 'noun_',
        ('形容詞', '自立'): 'adj_', ('動詞', '自立'): 'verb_'
    }

    for token in tokens:
        pos_parts = token.part_of_speech.split(',')
        pos_tuple = (pos_parts[0], pos_parts[1])
        
        if pos_tuple in TARGET_POS_TYPES:
            word = token.base_form if pos_parts[0] in ('形容詞', '動詞') else token.surface
            
            if len(word) > 1 and word not in STOP_WORDS:
                features[f"{TARGET_POS_TYPES[pos_tuple]}{word}"] = 1
                
    return features

# --- メイン処理 (Step1: リスト収集) ---

def collect_people(categories, cmlimit, depth, sleep, save_path, corresponding_dataset_path):
    """Step1: カテゴリから人物リストを収集し、キャッシュを管理する"""
    
    target_categories = sorted(list(set(categories)))
    
    if os.path.exists(save_path):
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f)
            saved_categories = data.get("meta", {}).get("categories")
            people_list = data.get("people")
            
            if saved_categories == target_categories and people_list is not None:
                print(f"\n--- 💾 キャッシュが見つかりました ---")
                print(f"  リスト: {save_path}")
                print(f"  データセット: {corresponding_dataset_path}")
                print("このキャッシュを使用しますか？ (1: 使用 / 2: 再収集)")
                choice = input(" (1/2) > ").strip()
                
                if choice == "2":
                    print("キャッシュを削除し、再収集します。")
                    if os.path.exists(save_path): os.remove(save_path)
                    if os.path.exists(corresponding_dataset_path): os.remove(corresponding_dataset_path)
                else:
                    if choice != "1": print("無効な選択。キャッシュを使用します。")
                    print(f"キャッシュ {save_path} を使用します。")
                    return people_list
            else:
                print("カテゴリが変更されたため、人物リストを再収集します。")
                if os.path.exists(corresponding_dataset_path): os.remove(corresponding_dataset_path)
        
        except Exception as e:
            print(f"既存ファイルが壊れています: {e}。再収集します。")
            if os.path.exists(save_path): os.remove(save_path)
            if os.path.exists(corresponding_dataset_path): os.remove(corresponding_dataset_path)

    print("=== カテゴリから人物リストを収集します ===")
    all_people = set()
    for cat in target_categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        
        # 簡易フィルタ
        filtered = {
            name for name in people 
            if (len(name) > 1 and not re.fullmatch(r"[0-9０-９A-Za-z]+", name))
        }
        print(f"   → {len(people)} 件取得 → {len(filtered)} 件（フィルタ後）")
        all_people.update(filtered)
        time.sleep(sleep)

    people_list = sorted(list(all_people))
    save_data = {
        "meta": {"categories": target_categories, "last_updated": datetime.now().isoformat()},
        "people": people_list
    }

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）")
    return people_list

# --- メイン処理 (Step2: データセット構築) ---

def process_person(name):
    """(並列処理用) 一人の人物データを構築する"""
    try:
        wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
        page = wiki.page(name)
        if not page.exists():
            search_results = wiki.search(name)
            if search_results:
                page = wiki.page(search_results[0])
            else:
                return {"name": name, "error": "ページなし"}

        rec = {"name": name, "summary": page.summary, "features": None, "wikidata": None}
        summary = clean_text(page.summary)

        # 1. 静的特徴 (キーワード)
        features = extract_features_from_summary(summary)
        # 2. 動的特徴 (Janome)
        features.update(extract_dynamic_features_from_summary(summary) or {})

        # 3. カテゴリ特徴
        try:
            for cat_title in page.categories.keys():
                cat_name = cat_title.replace("Category:", "").strip()
                if not any(keyword in cat_name for keyword in IGNORE_CAT_KEYWORDS):
                    features[f"cat_{cat_name}"] = 1
        except Exception as e:
            pass # カテゴリ取得失敗は許容
            # print(f"  [DEBUG-PROCESS] {name}: カテゴリ取得失敗. error='{e}'")

        # 4. 名前構造
        if re.search(r'[ァ-ヶ]', name): features["has_katakana"] = 1
        if re.fullmatch(r'[ぁ-ん]+', name): features["is_hiragana_only"] = 1
        
        rec["features"] = features # Wikidata取得失敗に備え、ここで一度保存

        # 5. Wikidata特徴
        wikibase_id = get_wikibase_item_from_wikipedia(name)
        if wikibase_id:
            wd = fetch_wikidata_entity(wikibase_id)
            rec["wikidata"] = wd
            if wd:
                # 性別
                g = wd.get("gender_qid")
                if g == QID_GENDER_MALE: features["gender"] = "male"
                elif g == QID_GENDER_FEMALE: features["gender"] = "female"

                # 年齢・世代
                birth_time = wd.get("birth_time")
                if birth_time:
                    try:
                        birth_year = int(birth_time.strip("+-").split("-")[0])
                        age = datetime.now().year - birth_year
                        if 20 <= age < 30: features["age_20s"] = 1
                        if 30 <= age < 40: features["age_30s"] = 1
                        if 40 <= age < 50: features["age_40s"] = 1
                        if 50 <= age < 60: features["age_50s"] = 1
                        if 1980 <= birth_year <= 1989: features["born_1980s"] = 1
                        if 1990 <= birth_year <= 1999: features["born_1990s"] = 1
                        if 2000 <= birth_year <= 2009: features["born_2000s"] = 1
                    except Exception as e:
                        pass # print(f"  [DEBUG] {name}: birth_time パース失敗. data='{birth_time}', error='{e}'")

                # 没年
                if wd.get("death_time"):
                    try:
                        death_year = int(wd["death_time"].strip("+-").split("-")[0])
                        if 1900 <= death_year <= 1999: features["died_20c"] = 1
                    except: pass
                
                # 血液型 (P1853)
                try:
                    v_id = wd.get("claims", {}).get("P1853", [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                    if v_id == "Q170138": features["blood_A"] = 1
                    if v_id == "Q170162": features["blood_B"] = 1
                    if v_id == "Q170196": features["blood_O"] = 1
                    if v_id == "Q170094": features["blood_AB"] = 1
                except: pass

                # 職業 (俳優/歌手/政治家)
                occ_qs = wd.get("occupation_qids", [])
                if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]): features["actor_wikidata"] = 1
                if any(q in occ_qs for q in ["Q177220", "Q639669", "Q10800557"]): features["singer_wikidata"] = 1
                if "Q82955" in occ_qs: features["politician_wikidata"] = 1

                # 出身地
                place_qid = wd.get("birth_place_qid")
                if place_qid in TOKYO_QIDS: features["from_tokyo"] = 1
                elif place_qid in KANSAI_QIDS: features["from_kansai"] = 1

                # 学歴
                edu_qids = wd.get("education_qids", [])
                for qid, feature_key in FAMOUS_UNIV_QIDS.items():
                    if qid in edu_qids:
                        features[feature_key] = 1

        rec["features"] = features # 最終的な特徴を保存
        return rec
        
    except Exception as e:
        print(f"  [ERROR] {name}: 処理中にエラー: {e}")
        # traceback.print_exc() 
        return {"name": name, "error": str(e), "features": None, "wikidata": None}

def build_dataset_parallel(people_list_path, dataset_path, limit=None, max_workers=50, sleep=0.1):
    """Step2: 人物リストに基づき、並列処理でデータセットを構築する"""
    
    people = load_people_list(people_list_path)
    if people is None:
        print("人物リストが存在しません。")
        return None
    if JANOME_TOKENIZER is None:
        print("Janomeが読み込まれていないため、データ構築をスキップします。")
        return None

    existing = {}
    if os.path.exists(dataset_path):
        try:
            with open(dataset_path, "r", encoding="utf-8") as f:
                existing = {p["name"]: p for p in json.load(f)}
            print(f"{len(existing)} 件の既存データを読み込みました。未処理のみ並列処理します。")
        except Exception as e:
            print(f"既存データ読み込み失敗: {e}")
            existing = {}

    targets = people[:limit] if limit is not None else people
    targets_to_process = [n for n in targets if n not in existing or not existing[n].get("features")]
    total = len(targets_to_process)
    
    print(f"データセット総件数: {len(targets)} 件中、処理対象: {total} 件")
    if total == 0:
        print("処理対象の人物がいません (すべてキャッシュ済み)。")
        return [p for p in existing.values() if p.get("features")]

    results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_person, name): name for name in targets_to_process}
        
        for i, future in enumerate(as_completed(futures), 1):
            name = futures[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"  [FATAL] {name}: future.result() で致命的エラー: {e}")
                result = {"name": name, "error": f"Fatal error: {e}"}
            
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            eta = avg_time * (total - i)
            
            print(f"[{i}/{total}] (Avg: {avg_time:.2f}s, ETA: {eta:.0f}s) 処理完了: {name}")

            if result and not result.get("error"):
                results.append(result)
            elif result:
                print(f"  [SKIP] {name}: エラー ({result.get('error')}) のためスキップします。")
    
    print(f"並列処理で {len(results)} 件を新規取得しました。")
    for res in results:
        existing[res["name"]] = res # 新しいデータで更新
        
    final_dataset = [existing[name] for name in targets if name in existing and existing[name].get("features")]
    missing_count = len(targets) - len(final_dataset)
            
    print(f"最終データセット: {len(final_dataset)} 件 (うち {missing_count} 件は処理失敗またはスキップ)")

    try:
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(final_dataset, f, ensure_ascii=False, indent=2)
        print(f"データセットを保存しました: {dataset_path}")
    except Exception as e:
        print(f"データセットの保存に失敗しました: {e}")
        
    return final_dataset

# --- 実行ブロック ---
if __name__ == "__main__":
    print("=== Wikipedia/Wikidata データ収集スクリプト ===")
    
    if JANOME_TOKENIZER is None:
        print("Janomeがロードされていないため、処理を中断します。")
        sys.exit(1)
        
    # (1) カテゴリ選択
    selected_categories = choose_categories()
    
    # (2) 動的なキャッシュファイル名の生成
    dynamic_list_path = get_dynamic_cache_path(selected_categories, "people_list")
    dynamic_dataset_path = get_dynamic_cache_path(selected_categories, "people_dataset")
    print(f"使用するファイル名 (カテゴリ依存):")
    print(f"  リスト: {dynamic_list_path}")
    print(f"  データセット: {dynamic_dataset_path}")

    # (3) Step 1: 人物リストの収集 (キャッシュ対応)
    people_list = collect_people(
        categories=selected_categories, 
        cmlimit=500,  # 取得件数
        depth=1,      # サブカテゴリの深さ
        sleep=0.5,    # APIスリープ
        save_path=dynamic_list_path,
        corresponding_dataset_path=dynamic_dataset_path
    )
    
    if not people_list:
        print("人物リストが空です。処理を終了します。")
        sys.exit(1)
        
    print(f"\n--- 合計 {len(people_list)} 人のリストを確保しました ---")

    # (4) Step 2: データセットの構築 (並列処理)
    print("\n--- データセットの構築を開始します (並列処理) ---")
    build_dataset_parallel(
        people_list_path=dynamic_list_path, 
        dataset_path=dynamic_dataset_path, 
        limit=None,      # 制限なし (テスト時は 100 などに設定)
        max_workers=30,  # 並列スレッド数
        sleep=0.05       # 投入スリープ
    )
    
    print("\n=== 全ての処理が完了しました ===")