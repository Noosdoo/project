import flask
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
import os
from flask_session import Session

# ==== 重要: ロジックは test_matsumoto_namae.py を利用 ====
try:
    import test_matsumoto_namae as logic
except ImportError:
    print("エラー: 'test_matsumoto_namae.py' が見つかりません。ファイル名/配置を確認してください。")
    exit(1)

app = Flask(__name__)

# CORS（Cookie 付きでの通信を許可）
CORS(app, supports_credentials=True)

# セッション管理
app.secret_key = "my-super-secret-key-for-akinator"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_FILE_DIR"] = "./flask_session"
Session(app)

# -----------------------
# HTML配信用のルート
# -----------------------
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


# --- サーバー起動時にデータセットと質問マップを読み込む ---
print("データセットを読み込んでいます...")
try:
    DATASET = logic.load_dataset(logic.DATASET_FILE)
    if DATASET is None:
        raise Exception(f"{logic.DATASET_FILE} が見つからないか、読み込みに失敗しました。")

    print("質問マップを生成しています...")
    QM_DICT = logic.generate_question_map(DATASET, selected_categories=None)
    print(f"読み込み完了。{len(DATASET)}件のデータ。")

except Exception as e:
    print(f"起動時エラー: {e}")
    print("データセットのロードに失敗しました。")
    print(f"先に 'test_matsumoto_namae.py' の 'collect' と 'build' を実行して '{getattr(logic, 'DATASET_FILE', 'people_dataset.json')}' を生成してください。")
    DATASET = []
    QM_DICT = {}

# -----------------------
# 便利関数
# -----------------------
def _get_question_by_key(q_key):
    """質問キーから質問オブジェクトを取得"""
    if not q_key:
        return None
    for q_list in QM_DICT.values():
        for q in q_list:
            if q.get('key') == q_key:
                return q
    return None

def get_session_stats():
    """フロント表示用の統計データ"""
    sid_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    cookie_val = request.cookies.get(sid_name, '-')
    return {
        "steps": session.get('steps', 0),
        "yes": session.get('yes_count', 0),
        "no": session.get('no_count', 0),
        "sid": (cookie_val or '-')[:8]
    }

def find_next_question():
    """次の質問 or 推測 結果を構築"""
    candidates = session.get('candidates', [])
    asked_keys = session.get('asked_keys', [])

    # 1. 候補1人
    if len(candidates) == 1:
        guess = candidates[0]['name']
        session['last_q_key'] = None  # 以降の戻しで誤用しないように
        return {
            "type": "guess",
            "name": guess,
            "confidence": 100,
            "candidates_count": 1,
            "session_data": get_session_stats()
        }

    # 2. 最適な質問
    question = logic.find_best_question(candidates, QM_DICT, asked_keys)

    if question:
        # 直近の質問キーを保存（戻る時の再提示用）
        session['last_q_key'] = question['key']
        return {
            "type": "question",
            "question_text": question['text'],
            "question_key": question['key'],
            "candidates_count": len(candidates),
            "session_data": get_session_stats()
        }

    # 3. 質問尽きたが複数候補
    if len(candidates) > 1:
        guess = candidates[0]['name']
        confidence = (1 / len(candidates)) * 100
        session['last_q_key'] = None
        return {
            "type": "guess",
            "name": guess,
            "confidence": confidence,
            "candidates_count": len(candidates),
            "session_data": get_session_stats()
        }

    # 4. 候補0
    session['last_q_key'] = None
    return {
        "type": "guess",
        "name": "候補が見つかりませんでした",
        "confidence": 0,
        "candidates_count": 0,
        "session_data": get_session_stats()
    }

# -----------------------
# API エンドポイント
# -----------------------
@app.route('/start', methods=['POST'])
def start_session():
    """新しいセッションを開始し、最初の質問を返す"""
    session['candidates'] = DATASET[:]  # 全候補
    session['asked_keys'] = []
    session['steps'] = 0
    session['yes_count'] = 0
    session['no_count'] = 0
    session['history'] = []        # ★ 戻る用に履歴をスタックで保持
    session['last_q_key'] = None   # ★ 直近に提示した質問キー
    print(f"[START] 新規セッション開始。候補: {len(session.get('candidates', []))}人")

    question_data = find_next_question()
    return jsonify(question_data)

@app.route('/answer', methods=['POST'])
def handle_answer():
    """ユーザーの回答を処理し、次の質問または推測を返す"""
    if 'candidates' not in session:
        print("[ERROR] /answer: セッションがありません。")
        return jsonify({"error": "セッションが開始されていません。"}), 400

    data = request.json or {}
    answer = data.get('answer')  # 'yes', 'no', 'dont_know'
    current_q_key = data.get('question_key') or session.get('last_q_key')

    candidates = session.get('candidates', [])
    asked_keys = session.get('asked_keys', [])
    history = session.get('history', [])

    # ★ 回答適用前にスナップショットを保存（戻る用）
    snapshot = {
        "candidates": candidates[:],
        "asked_keys": asked_keys[:],
        "steps": session.get('steps', 0),
        "yes": session.get('yes_count', 0),
        "no": session.get('no_count', 0),
        "prev_q_key": current_q_key
    }
    history.append(snapshot)
    session['history'] = history

    # 質問キーを既問へ（dont_know でも一応入れておく）
    if current_q_key and current_q_key not in asked_keys:
        asked_keys.append(current_q_key)

    # 回答に基づき候補を絞る
    if answer in ('yes', 'no'):
        q_obj = _get_question_by_key(current_q_key)
        if q_obj:
            test_func = q_obj['check']
            if answer == 'yes':
                candidates = [c for c in candidates if test_func(c)]
                session['yes_count'] = session.get('yes_count', 0) + 1
            else:
                candidates = [c for c in candidates if not test_func(c)]
                session['no_count'] = session.get('no_count', 0) + 1
            session['candidates'] = candidates
    # 'dont_know' は絞り込みなし

    session['steps'] = session.get('steps', 0) + 1
    session['asked_keys'] = asked_keys

    print(f"[ANSWER:{answer}] 候補: {len(session.get('candidates', []))}人")

    response_data = find_next_question()
    return jsonify(response_data)

@app.route('/back', methods=['POST'])
def go_back():
    """1つ前の状態に戻り、そのときの質問を再提示する"""
    if 'candidates' not in session:
        return jsonify({"error": "セッションが開始されていません。"}), 400

    history = session.get('history', [])
    if not history:
        # 戻れない → 現在状態で通常の次質問
        data = find_next_question()
        data["notice"] = "これ以上戻れません。"
        return jsonify(data)

    # 直前スナップショットに完全復元
    snap = history.pop()
    session['history'] = history
    session['candidates'] = snap["candidates"]
    session['asked_keys'] = snap["asked_keys"]
    session['steps'] = snap["steps"]
    session['yes_count'] = snap["yes"]
    session['no_count'] = snap["no"]

    # 直前の質問をそのまま再提示
    prev_q_key = snap.get("prev_q_key")
    q = _get_question_by_key(prev_q_key)

    if q:
        session['last_q_key'] = prev_q_key
        return jsonify({
            "type": "question",
            "question_text": q['text'],
            "question_key": q['key'],
            "candidates_count": len(session['candidates']),
            "session_data": get_session_stats(),
            "notice": "1つ前に戻りました。"
        })
    else:
        # 見つからなければ通常ロジックへ
        data = find_next_question()
        data["notice"] = "1つ前に戻りました。"
        return jsonify(data)

# -----------------------
# Main
# -----------------------
if __name__ == '__main__':
    if not DATASET:
        print("\n[警告] データセットが空です。APIは起動しますが、正常に動作しません。")
        print("先に 'python test_matsumoto_namae.py' で collect/build を実行してデータを生成してください。")

    # セッション保存フォルダ
    session_dir = app.config["SESSION_FILE_DIR"]
    if not os.path.exists(session_dir):
        os.makedirs(session_dir)
        print(f"セッション保存フォルダ '{session_dir}' を作成しました。")

    # 起動
    app.run(debug=True, use_reloader=False, port=5000)
