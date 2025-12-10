import os
import uuid
import logging
import glob
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

# キャッシュ: { "ファイル名": { "data": [...], "qm": {...} } }
DATASET_CACHE = {}

def get_dataset_list():
    """フォルダにあるデータセットファイルの一覧を取得"""
    files = glob.glob("people_dataset_*.json")
    dataset_list = []
    
    # ファイル名からラベルを作る (例: people_dataset_日本のYouTuber.json -> 日本のYouTuber)
    for f in files:
        label = f.replace("people_dataset_", "").replace(".json", "")
        dataset_list.append({"id": f, "label": label})
        
    return dataset_list

def load_specific_dataset(filename):
    """指定されたファイルだけを読み込む"""
    # キャッシュにあればそれを返す
    if filename in DATASET_CACHE:
        return DATASET_CACHE[filename]["data"], DATASET_CACHE[filename]["qm"]

    if not os.path.exists(filename):
        return None, None

    logger.info(f"データセット読み込み中: {filename}")
    # 指定ファイルのみ読み込み (閾値は適宜調整)
    ds = logic.load_dataset(filename, min_feature_threshold=10)
    
    if not ds:
        return None, None

    logger.info("質問マップ生成中...")
    qm = logic.generate_question_map(ds, selected_categories=None)

    # キャッシュに保存
    DATASET_CACHE[filename] = {
        "data": ds,
        "qm": qm
    }
    return ds, qm

# ================= Routes =================

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/datasets', methods=['GET'])
def get_datasets():
    """フロントエンドにファイル一覧を返す"""
    return jsonify({"datasets": get_dataset_list()})

@app.route('/start', methods=['POST'])
def start_game():
    data = request.json or {}
    # フロントエンドから送られてきたファイルID (ファイル名)
    dataset_id = data.get('dataset_id')

    # IDがない場合は、リストの一番最初のファイルを使う
    if not dataset_id:
        files = get_dataset_list()
        if files:
            dataset_id = files[0]['id']
        else:
            return jsonify({"type": "error", "message": "データファイルが見つかりません。"}), 404

    # 指定されたデータをロード
    ds, qm = load_specific_dataset(dataset_id)

    if ds is None:
        return jsonify({"type": "error", "message": "データの読み込みに失敗しました。"}), 500

    # セッション開始
    session['sid'] = str(uuid.uuid4())[:8]
    session['dataset_id'] = dataset_id  # 現在使っているファイル名を保存
    session['candidates'] = ds
    session['asked_keys'] = []
    session['steps'] = 0
    session['history'] = []

    question = logic.find_best_question(ds, qm, [])
    
    if not question:
        return jsonify({
            "type": "guess",
            "name": ds[0]['name'],
            "image": logic.get_wikipedia_main_image(ds[0]['name']),
            "confidence": 50,
            "session_data": {"steps": 0}
        })

    return jsonify({
        "type": "question",
        "question_text": question["text"],
        "question_key": question["key"],
        "session_data": {"steps": 0}
    })

@app.route('/answer', methods=['POST'])
def answer_question():
    data = request.json or {}
    answer = data.get('answer')
    question_key = data.get('question_key')

    # セッション復元
    current_candidates = session.get('candidates', [])
    asked_keys = session.get('asked_keys', [])
    steps = session.get('steps', 0)
    dataset_id = session.get('dataset_id')

    # 質問マップが必要なので再取得 (キャッシュから速攻で取れる)
    ds, qm = load_specific_dataset(dataset_id)

    session['history'].append({
        'candidates': current_candidates,
        'asked_keys': asked_keys,
        'steps': steps
    })

    new_candidates = []
    if answer == "dont_know":
        new_candidates = current_candidates
    else:
        for person in current_candidates:
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

    if len(new_candidates) == 1:
        winner = new_candidates[0]
        return jsonify({
            "type": "guess",
            "name": winner['name'],
            "image": logic.get_wikipedia_main_image(winner['name']),
            "confidence": 100,
            "session_data": {"steps": session['steps']}
        })
    elif len(new_candidates) == 0:
        return jsonify({
            "type": "guess",
            "name": "該当なし",
            "image": None,
            "confidence": 0,
            "session_data": {"steps": session['steps']}
        })
    else:
        next_q = logic.find_best_question(new_candidates, qm, asked_keys)
        if next_q is None:
            winner = new_candidates[0]
            return jsonify({
                "type": "guess",
                "name": winner['name'] + " (質問切れ)",
                "image": logic.get_wikipedia_main_image(winner['name']),
                "confidence": int(100/len(new_candidates)),
                "session_data": {"steps": session['steps']}
            })

        return jsonify({
            "type": "question",
            "question_text": next_q["text"],
            "question_key": next_q["key"],
            "session_data": {"steps": session['steps']}
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
    
    dataset_id = session.get('dataset_id')
    ds, qm = load_specific_dataset(dataset_id)
    next_q = logic.find_best_question(session['candidates'], qm, session['asked_keys'])
    
    return jsonify({
        "undo": True,
        "type": "question",
        "question_text": next_q["text"] if next_q else "再開",
        "question_key": next_q["key"] if next_q else None,
        "session_data": {"steps": session['steps']}
    })

if __name__ == '__main__':
    if not os.path.exists("./flask_session"):
        os.makedirs("./flask_session")
    app.run(debug=True, port=5001)