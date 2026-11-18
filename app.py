import os
import sqlite3
import json
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from sheets import GoogleSheets, SheetsError, scan, spreadsheet_id


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(SECRET_KEY=os.environ.get('BUZZER_SECRET_KEY'), DATABASE=os.path.join(app.instance_path, 'buzzer.sqlite3'))
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY']:
        raise RuntimeError('請設定 BUZZER_SECRET_KEY 環境變數')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def db():
        connection = sqlite3.connect(app.config['DATABASE'], timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            yield connection
        finally:
            connection.close()

    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL CHECK(state IN ('ready','active','ended')), source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activity(id), number INTEGER NOT NULL, sheet_id TEXT, cell TEXT, marker TEXT, UNIQUE(activity_id, number));
        CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES questions(id), team_id INTEGER NOT NULL REFERENCES teams(id), answer TEXT NOT NULL, rank INTEGER NOT NULL, UNIQUE(question_id, team_id), UNIQUE(question_id, rank));
        CREATE TABLE IF NOT EXISTS sheet_export (activity_id INTEGER PRIMARY KEY REFERENCES activity(id), status TEXT NOT NULL);
        INSERT OR IGNORE INTO activity VALUES (1, 'ready', 'demo');
        INSERT OR IGNORE INTO teams(id,name) VALUES (1,'第 1 組'),(2,'第 2 組');
        ''')

    def require(role=None):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if session.get('role') not in ('teacher', 'student') or (role and session.get('role') != role):
                    return jsonify(error='沒有權限，請重新選擇角色'), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.post('/api/join')
    def join():
        data = request.get_json(silent=True) or {}
        role = data.get('role')
        team = data.get('team')
        if role not in ('teacher', 'student'):
            return jsonify(error='角色無效'), 400
        with db() as con:
            if role == 'student' and (type(team) is not int or not con.execute('SELECT id FROM teams WHERE id=?', (team,)).fetchone()):
                return jsonify(error='組別無效'), 400
        session.clear()
        session['role'] = role
        if role == 'student':
            session['team'] = team
        return jsonify(ok=True)

    @app.get('/api/state')
    @require()
    def state():
        with db() as con:
            con.execute('BEGIN')
            activity = con.execute('SELECT state,source FROM activity WHERE id=1').fetchone()
            questions = con.execute('SELECT id,number FROM questions WHERE activity_id=1 ORDER BY number').fetchall()
            all_visible = session['role'] == 'teacher' or activity['state'] == 'ended'
            query = '''SELECT s.question_id,s.answer,s.rank,t.name AS team FROM submissions s JOIN teams t ON t.id=s.team_id'''
            rows = con.execute(query if all_visible else query + ' WHERE s.team_id=?', () if all_visible else (session['team'],)).fetchall()
            results = []
            for q in questions:
                entries = [dict(row) for row in rows if row['question_id'] == q['id']]
                entries.sort(key=lambda item: item['rank'])
                if not all_visible:
                    for entry in entries:
                        entry.pop('rank')
                results.append({'id': q['id'], 'number': q['number'], 'submissions': entries})
            exported = con.execute('SELECT status FROM sheet_export WHERE activity_id=1').fetchone()
            return jsonify(state=activity['state'], source='sheets' if activity['source'] != 'demo' else 'demo', export_status=exported['status'] if exported else None, role=session['role'], team=session.get('team'), questions=results)

    @app.post('/api/demo')
    @require('teacher')
    def demo():
        # Explicitly isolated temporary source until Sheets import is implemented.
        data = request.get_json(silent=True) or {}
        numbers = data.get('numbers')
        if not isinstance(numbers, list) or not numbers or any(type(n) is not int or n <= 0 for n in numbers) or len(numbers) != len(set(numbers)) or len(numbers) > 100:
            return jsonify(error='請輸入不重複的正整數題號'), 400
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT state FROM activity WHERE id=1').fetchone()['state'] != 'ready':
                con.rollback(); return jsonify(error='僅準備中可設定測試題目'), 409
            con.execute('DELETE FROM questions WHERE activity_id=1')
            con.executemany('INSERT INTO questions(activity_id,number) VALUES(1,?)', [(n,) for n in numbers])
            con.execute("UPDATE activity SET source='demo' WHERE id=1")
            con.commit()
        return jsonify(ok=True)

    def gateway():
        factory = app.config.get('SHEETS_FACTORY', GoogleSheets)
        return factory()

    @app.post('/api/sheets/import')
    @require('teacher')
    def import_sheets():
        try:
            data = request.get_json(silent=True) or {}
            if data.get('confirmed_single_questions') is not True:
                raise SheetsError('請先確認講義均為單題，且已逐題標記並核對題數')
            sid = spreadsheet_id(data.get('spreadsheet'))
            with db() as con:
                if con.execute('SELECT state FROM activity WHERE id=1').fetchone()['state'] != 'ready':
                    return jsonify(error='僅準備中可匯入'), 409
            items = scan(gateway().read(sid))
            with db() as con:
                con.execute('BEGIN IMMEDIATE')
                if con.execute('SELECT state FROM activity WHERE id=1').fetchone()['state'] != 'ready':
                    con.rollback(); return jsonify(error='活動階段已變更，匯入已取消'), 409
                con.execute('DELETE FROM questions WHERE activity_id=1')
                con.executemany('INSERT INTO questions(activity_id,number,sheet_id,cell,marker) VALUES(1,?,?,?,?)', [(i['number'], str(i['sheet_id']), json.dumps([i['row'],i['col'],i['merge']]), i['marker']) for i in items])
                con.execute('UPDATE activity SET source=? WHERE id=1', (sid,))
                con.commit()
            return jsonify(ok=True, count=len(items), numbers=[i['number'] for i in items])
        except SheetsError as exc:
            return jsonify(error=str(exc)), 400

    @app.post('/api/sheets/export')
    @require('teacher')
    def export_sheets():
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            activity_row = con.execute('SELECT state,source FROM activity WHERE id=1').fetchone()
            if activity_row['state'] != 'ended' or activity_row['source'] == 'demo':
                con.rollback(); return jsonify(error='僅可在活動結束後匯出 Sheets 題目'), 409
            if con.execute('SELECT 1 FROM sheet_export WHERE activity_id=1').fetchone():
                con.rollback(); return jsonify(error='已匯出或前次結果不明，請檢查原試算表'), 409
            con.execute("INSERT INTO sheet_export VALUES(1,'checking')")
            rows = con.execute('SELECT q.number,q.sheet_id,q.cell,q.marker,s.answer FROM questions q LEFT JOIN submissions s ON s.question_id=q.id AND s.rank=1 WHERE q.activity_id=1 ORDER BY q.number').fetchall()
            con.commit()
        writing = False
        try:
            client = gateway()
            fresh = scan(client.read(activity_row['source']))
            expected = [{'number': r['number'], 'sheet_id': int(r['sheet_id']), 'row': json.loads(r['cell'])[0], 'col': json.loads(r['cell'])[1], 'merge': json.loads(r['cell'])[2], 'marker': r['marker']} for r in rows]
            if fresh != expected:
                raise SheetsError('題目標記或位置已變更，已取消匯出；請檢查原表')
            writes = [dict(item, answer=row['answer']) for item, row in zip(expected, rows) if row['answer'] is not None]
            writing = True
            client.write(activity_row['source'], writes)
            with db() as con:
                con.execute("UPDATE sheet_export SET status='done' WHERE activity_id=1")
            return jsonify(ok=True, count=len(writes))
        except SheetsError as exc:
            with db() as con:
                if writing:
                    con.execute("UPDATE sheet_export SET status='unknown' WHERE activity_id=1")
                else:
                    con.execute('DELETE FROM sheet_export WHERE activity_id=1')
            return jsonify(error=str(exc)), 400

    @app.post('/api/activity/<action>')
    @require('teacher')
    def activity(action):
        if action not in ('start', 'end'):
            return jsonify(error='操作無效'), 404
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT state FROM activity WHERE id=1').fetchone()['state']
            if (action == 'start' and (current != 'ready' or not con.execute('SELECT 1 FROM questions WHERE activity_id=1').fetchone())) or (action == 'end' and current != 'active'):
                con.rollback(); return jsonify(error='目前階段無法執行此操作，請先設定題目'), 409
            con.execute('UPDATE activity SET state=? WHERE id=1', ('active' if action == 'start' else 'ended',))
            con.commit()
        return jsonify(ok=True)

    @app.post('/api/answer')
    @require('student')
    def answer():
        data = request.get_json(silent=True) or {}
        text = data.get('answer')
        qid = data.get('question_id')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000 or type(qid) is not int:
            return jsonify(error='請輸入有效的非空答案'), 400
        if 'team' in data and data['team'] != session['team']:
            return jsonify(error='不得代表其他組作答'), 403
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT state FROM activity WHERE id=1').fetchone()['state'] != 'active':
                con.rollback(); return jsonify(error='目前不在搶答階段'), 409
            if not con.execute('SELECT 1 FROM questions WHERE id=? AND activity_id=1', (qid,)).fetchone():
                con.rollback(); return jsonify(error='題目不存在'), 404
            if con.execute('SELECT 1 FROM submissions WHERE question_id=? AND team_id=?', (qid, session['team'])).fetchone():
                con.rollback(); return jsonify(error='本組已提交此題'), 409
            rank = con.execute('SELECT COALESCE(MAX(rank),0)+1 FROM submissions WHERE question_id=?', (qid,)).fetchone()[0]
            con.execute('INSERT INTO submissions(question_id,team_id,answer,rank) VALUES(?,?,?,?)', (qid, session['team'], text.strip(), rank))
            con.commit()
        return jsonify(ok=True)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, threaded=True)
