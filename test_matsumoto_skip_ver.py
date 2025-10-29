import requests
import time
import json
import os
import re
import random
import wikipediaapi
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ（必要に応じて増やす）
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

# ユーティリティ: Wikipediaカテゴリからタイトル取得（cmcontinue対応）
# depth: サブカテゴリをたどる深さ（0=直下のみ、1=1階層下まで）




# -----------------------
# 除外ルール: 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    """
    タイトルに特定のキーワードが含まれていたら除外
    """
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)




# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得（cmcontinue対応）
# -----------------------

# カテゴリから人物を収集する関数（カテゴリ名、１回のAPIリクエストで取得する件数、サブカテゴリをたどる深さ、再帰用、アクセス間隔）
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    """
    category: "日本の俳優" のようなカテゴリ名（"Category:" は不要）
    cmlimit: 1リクエスト当たりの取得数（Colab利用なら50程度推奨）
    depth: サブカテゴリをたどる階層深さ
    collected: 内部用（再帰時に渡す）
    """

    # 再帰呼び出しでなければ、新しいセットを作成
    if collected is None:
        collected = set()

    # Wikipedia API用に "Category:" プレフィックスをつける
    cmtitle = f"Category:{category}"

    # APIパラメータ設定
    params = {
        "action": "query",           # クエリ実行モード
        "list": "categorymembers",   # カテゴリ内のメンバーを取得
        "cmtitle": cmtitle,          # 対象カテゴリ
        "cmlimit": str(cmlimit),     # 取得件数上限
        "format": "json"             # 結果形式（jsonとは人間が読み書きしやすいシンプルなテキスト形式）
    }

    cont = None  # 取得が複数ページに分かれる場合の継続トークンを格納
    while True:

        # 続きがあればパラメータに追加
        if cont:
            params.update(cont)
        try:
            # Wikipedia APIにリクエストを送信
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            # 通信エラー時は報告して終了
            print("HTTPエラー:", e)
            return collected

        # アクセス拒否された場合
        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。時間を置いて再試行してください。")
            return collected

        # JSONのパースを試みる
        try:
            data = res.json()
        except Exception as e:
            print("JSONデコード失敗:", e)
            return collected

        # 結果から「カテゴリ内のページ一覧」を取り出す
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title:
                continue
            # サブカテゴリを見つけたら、深さが残っていれば再帰
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)  # アクセス間隔を空ける
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep)
                continue
            # 除外ルール（団体類などを排除）
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]):
                continue

            # 個人名をセットに追加
            collected.add(title)

        # 結果に「続き」がある場合は、次のページを取得する
        if "continue" in data:
            cont = data["continue"]
            time.sleep(sleep)
        else:
            # 全て取得し終えたら終了
            break

    # すべてのタイトルを返す（set型）
    return collected



def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5)")

    choice = input("> ").strip()
    selected = []
    for part in choice.split(","):
        try:
            idx = int(part)-1
            if 0 <= idx < len(CATEGORIES):
                selected.append(CATEGORIES[idx])
        except:
            pass
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。")
        return CATEGORIES
    return selected








# -----------------------
# Step1: 全カテゴリから人物を収集して保存
# -----------------------

# 指定したWikipediaカテゴリから、そのカテゴリに含まれる人物のタイトルを取得する関数（ 、APIで一回に取得する件数、下位カテゴリをどの階層まで探索するか、API呼び出し間の待機時間）
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    if os.path.exists(save_path):
        print(f"{save_path} が既に存在するため、collect はスキップします。")
        with open(save_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print("=== カテゴリから人物リストを収集します ===")
    all_people = set()
    for cat in categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        print(f"  → {len(people)} 人取得")
        all_people.update(people)
        time.sleep(sleep)

    people_list = sorted(list(all_people))
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(people_list, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）")
    return people_list







# -----------------------
# Wikidata取得補助: Wikipediaページからwikibase_itemを得る
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {
        "action": "query",      # データを取得するアクション
        "titles": title,        # 対象ページのタイトル
        "prop": "pageprops",    # ページのプロパティ情報を取得（Wikibase item ID を含む）
        "format": "json"        # 返り値の形式をJSONに指定
    }
    try:
        # Wikipedia APIにリクエストを送信
        # ここでは、あらかじめ定義してあるグローバル変数 WIKI_API と HEADERS を使用
        # timeout=15 は15秒以内に応答がなければ中断する設定
        
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        # 返ってきたデータをJSON形式に変換
        data = res.json()
        # JSONから目的のデータ構造（"query" → "pages"）を取得
        pages = data.get("query", {}).get("pages", {})
        # ページ情報がなければ None を返す（エラー回避）
        if not pages:
            return None
        # ページ情報は通常1件なので、最初の要素を取得
        page = next(iter(pages.values()))
        # pageprops というキーに Wikidata ID が格納されている
        pp = page.get("pageprops", {})
        # WikidataのQID（例："Q706142"）を取得して返す
        return pp.get("wikibase_item")
    except Exception:
        # 何らかの通信エラー・構文エラー・タイムアウトが発生した場合は安全に None を返す
        return None






# -----------------------
# Wikidataから構造化属性を取得（P106: 職業, P21: 性別, P569: 生年月日, P570: 死亡日）
# ※ 返り値は辞書。失敗時はNone
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        data = res.json()
        entity = data.get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {}
        # occupation (P106) -> list of ids
        if "P106" in claims:
            occ = []
            for c in claims["P106"]:
                mainsnak = c.get("mainsnak", {})
                dv = mainsnak.get("datavalue", {})
                if dv:
                    v = dv.get("value")
                    if isinstance(v, dict) and "id" in v:
                        occ.append(v["id"])
            result["occupation_qids"] = occ
        # gender (P21)
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v:
                    result["gender_qid"] = v["id"]
            except Exception:
                pass
        # birth (P569)
        if "P569" in claims:
            try:
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["birth_time"] = t  # +YYYY-MM-DD...
            except Exception:
                pass
        # death (P570)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["death_time"] = t
            except Exception:
                pass
        return result
    except Exception:
        return None

# -----------------------
# summaryからキーワードベースで特徴を抽出する（拡張版）
# -----------------------
FEATURE_KEYWORDS = {
    "taiga": ["大河ドラマ", "大河"],
    "tokusatsu": ["仮面ライダー", "スーパー戦隊", "ウルトラマン", "特撮"],
    "romance_drama": ["恋愛", "ラブストーリー", "恋人"],
    "movie": ["映画", "劇場版"],
    "action": ["アクション", "殺陣", "アクション俳優"],
    "seiyuu": ["声優", "アニメで声"],
    "singer": ["歌手", "シンガー", "ボーカル"],
    "stage": ["舞台", "ミュージカル", "劇団"],
    "model": ["モデル", "ファッションモデル"],
    "comedian": ["お笑い", "芸人", "コント"],
    "anime": ["アニメ"],
    "hollywood": ["ハリウッド", "海外映画"],
    "idol": ["アイドル", "グループ"],
    "award": ["受賞", "賞を受賞", "主演男優賞", "最優秀"],
    "nhk": ["NHK", "連続テレビ小説", "朝ドラ"],
    "youtuber": ["YouTube", "チャンネル"],
    "director": ["監督"],
    "athlete": ["選手", "オリンピック", "サッカー", "野球", "柔道", "レスリング"],
    "politician": ["政治家", "衆議院", "参議院", "首相"]
}

def extract_features_from_summary(summary):
    s = summary or ""
    features = {}
    for k, keywords in FEATURE_KEYWORDS.items():
        features[k] = int(any(kw in s for kw in keywords))
    # 年代判定（summaryに年が書かれている場合）
    # try to find birth year pattern: YYYY年
    m = re.search(r'(\d{4})年', s)
    birth_year = None
    if m:
        try:
            birth_year = int(m.group(1))
        except:
            birth_year = None
    features["birth_year"] = birth_year
    # alive (naive: "没" or "死去" presence)
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1
    return features

# -----------------------
# Step2: people list -> build dataset (attributes per person)
# - resume: 既存のDATASET_FILEがあれば読み込み、まだ無い人だけ処理
# - limit: デバッグ用に処理件数を制限可能
# -----------------------
def build_dataset(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, limit=None, sleep=0.8):
    # 人物リストがなければ終了
    if not os.path.exists(people_list_path):
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None

    with open(people_list_path, "r", encoding="utf-8") as f:
        people = json.load(f)

    # 既存データセットがあれば読み込み、処理済み人物をスキップ
    existing = {}
    if os.path.exists(dataset_path):
        with open(dataset_path, "r", encoding="utf-8") as f:
            try:
                existing = {p["name"]: p for p in json.load(f)}
                print(f"{len(existing)} 件の既存データを読み込みました。未処理の人物のみ処理します。")
            except:
                existing = {}

    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    new_records = []
    processed = 0

    for name in people:
        if limit and processed >= limit:
            break
        if name in existing:
            print(f"処理済み: {name} ... スキップ")
            continue  # 既存データがある場合はスキップ

        print(f"処理中: {name}  ...", end=" ")
        rec = {"name": name, "summary": None, "features": None, "wikidata": None}
        try:
            page = wiki.page(name)
            if not page.exists():
                print("ページなし")
                processed += 1
                continue
            summary = page.summary
            rec["summary"] = summary
            rec["features"] = extract_features_from_summary(summary)
            wikibase_id = get_wikibase_item_from_wikipedia(name)
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd
                if wd:
                    g = wd.get("gender_qid")
                    if g == "Q6581097":
                        rec["features"]["gender"] = "male"
                    elif g == "Q6581072":
                        rec["features"]["gender"] = "female"
                    occ_qs = wd.get("occupation_qids", [])
                    if "Q33999" in occ_qs:  # actor
                        rec["features"]["actor_wikidata"] = 1
                    if "Q177220" in occ_qs:  # singer
                        rec["features"]["singer_wikidata"] = 1
                    if "Q82955" in occ_qs:  # politician
                        rec["features"]["politician_wikidata"] = 1
                    if wd.get("birth_time"):
                        rec["features"]["birth_time"] = wd.get("birth_time")
                    if wd.get("death_time"):
                        rec["features"]["death_time"] = wd.get("death_time")
            print("OK")
        except Exception as e:
            print("失敗:", e)
        new_records.append(rec)
        processed += 1
        time.sleep(sleep)

    # 既存 + 新規データをマージして保存
    merged = list(existing.values()) + new_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"データセットを保存しました: {dataset_path}（合計 {len(merged)} 件）")
    return merged


# -----------------------
# Step3: アキネーター本体（datasetを読み込んで対話で絞り込み）
# - 質問は dataset の features keys と FEATURE_KEYWORDS に基づくものを提示する
# -----------------------
def load_dataset(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

#-----------------------
# 質問マップの自動生成（カテゴリ選択に応じて）
#-----------------------
def generate_question_map(selected_categories=None):
    """
    アキネーター形式質問マップ生成：
    - 質問をカテゴリ階層（職業→活動→特徴）に整理
    - カテゴリ外質問を除外
    - 質問重複を防止
    """

    import random
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}

    # --- カテゴリ別の質問データ ---
    CATEGORY_KEYWORD_MAP = {
        "日本の俳優": {
            "occupation": ["俳優"],
            "activity": ["大河ドラマ", "映画", "舞台", "特撮", "恋愛ドラマ", "海外映画"],
            "feature": ["受賞", "NHK"]
        },
        "日本の女優": {
            "occupation": ["俳優"],
            "activity": ["大河ドラマ", "映画", "舞台", "恋愛ドラマ"],
            "feature": ["受賞", "NHK"]
        },
        "お笑い芸人": {
            "occupation": ["お笑い芸人"],
            "activity": ["コント", "漫才", "バラエティ番組"],
            "feature": []
        },
        "日本の声優": {
            "occupation": ["声優"],
            "activity": ["アニメ", "ゲーム", "吹き替え"],
            "feature": []
        },
        "日本の歌手": {
            "occupation": ["歌手"],
            "activity": ["ライブ", "舞台", "音楽番組"],
            "feature": ["受賞"]
        },
        "日本のアイドル": {
            "occupation": ["アイドル"],
            "activity": ["歌手", "バラエティ番組"],
            "feature": []
        },
        "日本の作家": {
            "occupation": ["作家", "漫画家", "小説家", "詩人"],
            "activity": ["アニメ化", "漫画", "小説"],
            "feature": ["受賞"]
        },
        "日本のYouTuber": {
            "occupation": ["YouTuber"],
            "activity": ["配信", "動画制作"],
            "feature": []
        },
    }

    if not selected_categories:
        selected_categories = CATEGORY_KEYWORD_MAP.keys()

    # --- 職業（大カテゴリ） ---
    for cat in selected_categories:
        for occ in CATEGORY_KEYWORD_MAP[cat]["occupation"]:
            qm["occupation"].append({
                "key": f"occ_{occ}",
                "text": f"この人物は {occ} ですか？",
                "check": lambda rec, o=occ: rec.get("summary") and o in rec["summary"]
            })

    # --- 活動対象（中カテゴリ） ---
    for cat in selected_categories:
        for act in CATEGORY_KEYWORD_MAP[cat]["activity"]:
            qm["activity"].append({
                "key": f"act_{act}",
                "text": f"{act} に関係していますか？",
                "check": lambda rec, a=act: rec.get("summary") and a in rec["summary"]
            })

    # --- 特徴（小カテゴリ） ---
    for cat in selected_categories:
        for feat in CATEGORY_KEYWORD_MAP[cat]["feature"]:
            qm["feature"].append({
                "key": f"feat_{feat}",
                "text": f"{feat} が特徴的ですか？",
                "check": lambda rec, f=feat: rec.get("summary") and f in rec["summary"]
            })

    # --- 共通質問（性別・生存） ---
    qm["common"] = [
        {
            "key": "alive_text",
            "text": "現在もご存命ですか？",
            "check": lambda rec: rec.get("features", {}).get("alive_text") == 1
        },
        {
            "key": "gender_male",
            "text": "男性ですか？",
            "check": lambda rec: rec.get("features", {}).get("gender") == "male"
        },
        {
            "key": "gender_female",
            "text": "女性ですか？",
            "check": lambda rec: rec.get("features", {}).get("gender") == "female"
        }
    ]

    # --- 質問順を制御（職業→活動→特徴→共通） ---
    for k in qm:
        random.shuffle(qm[k])

    return qm








#-----------------------
# アキネーター対話部分
#-----------------------
def akinator_play(dataset, max_questions=30, check_every=10):
    candidates = dataset.copy()
    qm_dict = generate_question_map()
    
    # occupation / activity / feature / common を全部まとめる
    qm = []
    for qlist in qm_dict.values():
        qm.extend(qlist)
    
    random.shuffle(qm)

    print("=== アキネーター開始 ===")
    print(f"候補人数: {len(candidates)} 件")

    asked = 0
    i_qm = 0

    while asked < max_questions and len(candidates) > 1 and i_qm < len(qm):
        question = qm[i_qm]
        key, q_text, test = question.get("key"), question.get("text"), question.get("check")

        ans = input(q_text + " （はい/いいえ/わからない） > ").strip()
        if ans not in ["はい", "いいえ"]:
            print("スキップ")
            i_qm += 1
            continue

        if ans == "はい":
            candidates = [c for c in candidates if test(c)]
        else:
            candidates = [c for c in candidates if not test(c)]

        asked += 1
        i_qm += 1

        if asked % check_every == 0 or len(candidates) <= 3:
            print(f"\nここまでの質問で絞り込んだ候補（上位3件）:")
            for j, c in enumerate(candidates[:3], 1):
                print(f"{j}. {c['name']}")
            choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
            if choice.isdigit():
                idx = int(choice)-1
                if 0 <= idx < len(candidates[:3]):
                    print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
                    return candidates[idx]
            elif choice.lower() in ["なし", "n", "no"]:
                print("わかりました。質問を続けます。")

    if not candidates:
        print("候補が見つかりませんでした。")
        return None

    print("\n最終候補（上位3件）:")
    for i, c in enumerate(candidates[:3], 1):
        print(f"{i}. {c['name']}")
    choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
    if choice.isdigit():
        idx = int(choice)-1
        if 0 <= idx < len(candidates[:3]):
            print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
            return candidates[idx]

    print(f"私の推測：『{candidates[0]['name']}』かもしれません。")
    return candidates[0]




# -----------------------
# 改良版: 並列処理でデータセット構築
# -----------------------
def build_dataset(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, limit=None, sleep=0.8):
    """
    データセット構築をスキップして、既存ファイルをそのまま読み込む。
    """
    if os.path.exists(dataset_path):
        print(f"{dataset_path} が既に存在するため、処理はスキップします。")
        with open(dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        print(f"{dataset_path} が存在しません。事前に collect_people と build_dataset を実行してください。")
        return None



def fetch_data(person):
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    page = wiki.page(person)
    summary = page.summary if page.exists() else None
    wikibase_id = get_wikibase_item_from_wikipedia(person)
    wikidata = fetch_wikidata_entity(wikibase_id) if wikibase_id else None
    return {"title": person, "summary": summary, "wikidata": wikidata}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_data, p) for p in people]
        for future in as_completed(futures):
            results.append(future.result())

    with open(PEOPLE_DATASET_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)




# -----------------------
# エントリポイント用関数
# -----------------------

def run_step(step="collect", **kwargs):
    """
    step: "collect" / "build" / "play"
    collect: categories -> people_list.json
        kwargs: cmlimit, depth, sleep
    build: people_list.json -> people_dataset.json
        kwargs: limit (int, optional), sleep
    play: load people_dataset.json -> interactive game
        kwargs: max_questions
    """
    step = step.lower()

    if step == "collect":
        save_path = kwargs.get("save_path", PEOPLE_LIST_FILE)
        #if os.path.exists(save_path):
        #    print(f"{save_path} が既に存在するため、collect はスキップします。")
        #    with open(save_path, "r", encoding="utf-8") as f:
        #        return json.load(f)
        cmlimit = kwargs.get("cmlimit", 50)
        depth = kwargs.get("depth", 1)
        sleep = kwargs.get("sleep", 0.8)
        return collect_people(categories=kwargs.get("categories", CATEGORIES),
                              cmlimit=cmlimit, depth=depth, sleep=sleep)

    elif step == "build":
        dataset_path = kwargs.get("dataset_path", DATASET_FILE)
        #if os.path.exists(dataset_path):
        #    print(f"{dataset_path} が既に存在するため、build はスキップします。")
        #    with open(dataset_path, "r", encoding="utf-8") as f:
        #        return json.load(f)
        limit = kwargs.get("limit", None)
        sleep = kwargs.get("sleep", 0.8)
        return build_dataset(limit=limit, sleep=sleep)

    elif step == "play":
        ds = load_dataset()
        if not ds:
            return None
        return akinator_play(ds, max_questions=kwargs.get("max_questions", 30))

    else:
        raise ValueError("step must be one of: collect, build, play")



# -----------------------
# 実行部分
# -----------------------
if __name__ == "__main__":
    selected_categories = choose_categories()
    # データ収集
    run_step("collect", categories=selected_categories, cmlimit=20, depth=1, sleep=0.0)
    # データセットを構築
    run_step("build", limit=200, sleep=0.0)
    # アキネーターをプレイ
    run_step("play", max_questions=25)