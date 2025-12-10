import os
import uuid
import logging
# ★ send_from_directory を追加
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from flask_session import Session

import inf_learn as logic

app = Flask(__name__)
CORS(app, supports_credentials=True)

app.config["SECRET_KEY"] = "super-dynamic-akinator-key"
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./flask_session"
Session(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# キャッシュ
DATASET_CACHE = {}

def get_cached_dataset_and_qm(categories):
    list_path = logic.get_dynamic_cache_path(categories, prefix="people_list")
    dataset_path = logic.get_dynamic_cache_path(categories, prefix="people_dataset")

    if dataset_path in DATASET_CACHE:
        return dataset_path, DATASET_CACHE[dataset_path]["data"], DATASET_CACHE[dataset_path]["qm"]

    if not os.path.exists(dataset_path):
        return dataset_path, None, None

    logger.info(f"ロード中... {dataset_path}")
    ds = logic.load_dataset(dataset_path, min_feature_threshold=15)
    
    if not ds:
        return dataset_path, None, None

    logger.info("質問マップ生成中...")
    qm = logic.generate_question_map(ds, selected_categories=categories)

    DATASET_CACHE[dataset_path] = {
        "data": ds,
        "qm": qm
    }
    return dataset_path, ds, qm

# ==========================================
# ルーティング (ここが修正ポイント！)
# ==========================================

# 1. トップページにアクセスしたら index.html を表示する
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# 2. HTMLがデータセット一覧を取りに来た時の対応
@app.route('/datasets', methods=['GET'])
def get_datasets_compatibility():
    # HTMLの選択肢に「自動生成データ」を表示させる
    return jsonify({
        "datasets": [
            {"id": "dynamic", "label": "自動生成データセット", "is_default": True}
        ]
    })

@app.route('/start', methods=['POST'])
def start_game():
    data = request.json or {}
    
    # HTMLからの dataset_id は無視して、Python側のカテゴリロジックを使う
    # (本来はHTML側でカテゴリ選択UIを作るべきですが、今回は全カテゴリ対象として進めます)
    selected_cats = logic.CATEGORIES 

    path, ds, qm = get_cached_dataset_and_qm(selected_cats)

    if ds is None:
        # データがない場合のエラーメッセージ
        return jsonify({
            "type": "question", # エラー表示用に形式を合わせる
            "question_text": "データがありません。先に黒い画面で 'python inf_learn.py' を実行してデータを収集してください。",
            "question_key": None,
            "session_data": {"steps": 0, "candidates_count": 0}
        })

    session['sid'] = str(uuid.uuid4())[:8]
    session['dataset_path'] = path
    session['categories'] = selected_cats
    session['candidates'] = ds
    session['asked_keys'] = []
    session['steps'] = 0
    session['history'] = []

    question = logic.find_best_question(ds, qm, [])
    
    if not question:
        # 質問が見つからない場合
        winner = ds[0]
        return jsonify({
            "type": "guess",
            "name": winner['name'],
            "image": logic.get_wikipedia_main_image(winner['name']),
            "confidence": 50,
            "session_data": {"steps": 0, "candidates_count": len(ds)}
        })

    return jsonify({
        "type": "question",
        "question_text": question["text"],
        "question_key": question["key"],
        "session_data": {"steps": 0, "candidates_count": len(ds)}
    })

@app.route('/answer', methods=['POST'])
def answer_question():
    data = request.json or {}
    answer = data.get('answer')
    question_key = data.get('question_key')

    current_candidates = session.get('candidates', [])
    asked_keys = session.get('asked_keys', [])
    steps = session.get('steps', 0)
    dataset_path = session.get('dataset_path')
    
    if dataset_path in DATASET_CACHE:
        qm = DATASET_CACHE[dataset_path]["qm"]
    else:
        # キャッシュ切れの再ロード (エラー回避のため簡易的に全カテゴリ)
        _, _, qm = get_cached_dataset_and_qm(session.get('categories', logic.CATEGORIES))

    session['history'].append({
        'candidates': current_candidates,
        'asked_keys': asked_keys,
        'steps': steps
    })

    new_candidates = []
    if answer == "dont_know":
        new_candidates = current_candidates
    else:
        # ユーザーの答えに合わせてフィルタリング
        target_val = 1 if answer == "yes" else 0
        for person in current_candidates:
            # 特徴値を取得 (Noneは0扱い)
            feat_val = person.get("features", {}).get(question_key)
            has_feature = (feat_val == 1)
            
            if answer == "yes" and has_feature:
                new_candidates.append(person)
            elif answer == "no" and not has_feature:
                new_candidates.append(person)

    session['candidates'] = new_candidates
    if question_key: asked_keys.append(question_key)
    session['asked_keys'] = asked_keys
    session['steps'] = steps + 1
    
    # 判定ロジック
    if len(new_candidates) == 1:
        winner = new_candidates[0]
        img_url = logic.get_wikipedia_main_image(winner['name'])
        return jsonify({
            "type": "guess",
            "name": winner['name'],
            "image": img_url,
            "confidence": 100,
            "session_data": {"steps": session['steps'], "candidates_count": 1}
        })
    elif len(new_candidates) == 0:
        return jsonify({
            "type": "guess",
            "name": "該当なし",
            "image": None,
            "confidence": 0,
            "session_data": {"steps": session['steps'], "candidates_count": 0}
        })
    else:
        next_q = logic.find_best_question(new_candidates, qm, asked_keys)
        if next_q is None:
            winner = new_candidates[0]
            img_url = logic.get_wikipedia_main_image(winner['name'])
            return jsonify({
                "type": "guess",
                "name": winner['name'] + " (推測)",
                "image": img_url,
                "confidence": int(100/len(new_candidates)),
                "session_data": {"steps": session['steps'], "candidates_count": len(new_candidates)}
            })

        return jsonify({
            "type": "question",
            "question_text": next_q["text"],
            "question_key": next_q["key"],
            "session_data": {"steps": session['steps'], "candidates_count": len(new_candidates)}
        })

@app.route('/undo', methods=['POST'])
def undo_last():
    history = session.get('history', [])
    if not history: return jsonify({"undo": False})
    
    last = history.pop()
    session['candidates'] = last['candidates']
    session['asked_keys'] = last['asked_keys']
    session['steps'] = last['steps']
    session['history'] = history
    
    # 次の質問再計算
    dataset_path = session.get('dataset_path')
    if dataset_path in DATASET_CACHE:
        qm = DATASET_CACHE[dataset_path]["qm"]
    else:
        _, _, qm = get_cached_dataset_and_qm(session.get('categories', logic.CATEGORIES))
        
    next_q = logic.find_best_question(session['candidates'], qm, session['asked_keys'])
    
    return jsonify({
        "undo": True,
        "type": "question",
        "question_text": next_q["text"] if next_q else "再計算エラー",
        "question_key": next_q["key"] if next_q else None,
        "session_data": {"steps": session['steps'], "candidates_count": len(session['candidates'])}
    })

if __name__ == '__main__':
    if not os.path.exists("./flask_session"):
        os.makedirs("./flask_session")
    
    # 起動前にデータがあるかチェックして警告を出す親切機能
    dummy_path = logic.get_dynamic_cache_path(logic.CATEGORIES, prefix="people_dataset")
    if not os.path.exists(dummy_path):
        print("\n!!!!!!!!!!!!!!! 注意 !!!!!!!!!!!!!!!")
        print("データセットファイルが見つかりません。")
        print("まずは黒い画面で 'python inf_learn.py' を実行して、")
        print("データを収集(collect) → 構築(build) してください。")
        print("そうしないと、ブラウザで開始しても「データがありません」と表示されます。")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")

    print("=== Server Starting ===")
    app.run(debug=True, port=5001)
    