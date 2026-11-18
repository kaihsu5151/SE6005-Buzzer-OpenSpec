import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

from app import create_app


class BuzzerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'DATABASE': self.path})
        self.teacher, self.one, self.two = (self.app.test_client() for _ in range(3))
        self.teacher.post('/api/join', json={'role': 'teacher'})
        self.one.post('/api/join', json={'role': 'student', 'team': 1})
        self.two.post('/api/join', json={'role': 'student', 'team': 2})

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        self.assertEqual(self.teacher.post('/api/demo', json={'numbers': [3, 8, 9]}).status_code, 200)
        self.questions = {q['number']: q['id'] for q in self.teacher.get('/api/state').json['questions']}
        self.assertEqual(self.teacher.post('/api/activity/start', json={}).status_code, 200)

    def submit(self, client, number, answer='答案', **extra):
        return client.post('/api/answer', json={'question_id': self.questions[number], 'answer': answer, **extra})

    def test_transitions_and_authorization(self):
        self.assertEqual(self.teacher.post('/api/activity/start', json={}).status_code, 409)
        self.assertEqual(self.one.post('/api/demo', json={'numbers':[1]}).status_code, 403)
        self.assertEqual(self.one.post('/api/activity/end', json={}).status_code, 403)
        self.prepare()
        self.assertEqual(self.teacher.post('/api/activity/start', json={}).status_code, 409)
        self.assertEqual(self.submit(self.one, 3, team=2).status_code, 403)
        self.assertEqual(self.teacher.post('/api/activity/end', json={}).status_code, 200)
        self.assertEqual(self.submit(self.one, 3).status_code, 409)
        self.assertEqual(self.teacher.post('/api/activity/end', json={}).status_code, 409)

    def test_submission_and_privacy(self):
        self.prepare()
        self.assertEqual(self.submit(self.one, 3, '  ').status_code, 400)
        self.assertEqual(self.submit(self.one, 3, '秘密').status_code, 200)
        self.assertEqual(self.submit(self.one, 3, '改答案').status_code, 409)
        self.assertEqual(self.submit(self.two, 3, '第二').status_code, 200)
        self.assertEqual(self.submit(self.two, 8, '另一題').status_code, 200)
        visible = self.two.get('/api/state').get_data(as_text=True)
        self.assertNotIn('秘密', visible)
        self.assertNotIn('rank', visible)
        self.assertEqual(self.teacher.get('/api/state').json['questions'][0]['submissions'][0]['answer'], '秘密')
        self.teacher.post('/api/activity/end', json={})
        result = self.two.get('/api/state').json['questions']
        self.assertEqual([x['rank'] for x in result[0]['submissions']], [1, 2])
        self.assertEqual(result[1]['submissions'][0]['rank'], 1)
        self.assertEqual(result[2]['submissions'], [])

    def test_concurrent_submissions(self):
        self.prepare()
        gate = threading.Barrier(2)
        def submit(team):
            with self.app.test_client() as client:
                client.post('/api/join', json={'role':'student','team':team})
                gate.wait()
                return self.submit(client, 3, str(team)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, [1, 2]))
        self.assertEqual(statuses, [200, 200])
        rows = self.teacher.get('/api/state').json['questions'][0]['submissions']
        self.assertEqual([row['rank'] for row in rows], [1, 2])

    def test_end_race(self):
        self.prepare()
        gate = threading.Barrier(2)
        def end():
            with self.app.test_client() as c:
                c.post('/api/join', json={'role':'teacher'}); gate.wait()
                return c.post('/api/activity/end', json={}).status_code
        def answer():
            with self.app.test_client() as c:
                c.post('/api/join', json={'role':'student','team':1}); gate.wait()
                return self.submit(c, 3).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(end), pool.submit(answer)
            self.assertEqual(a.result(), 200)
            status = b.result()
        self.assertIn(status, (200, 409))
        rows = self.teacher.get('/api/state').json['questions'][0]['submissions']
        self.assertEqual(len(rows), int(status == 200))
        self.assertEqual(self.submit(self.two, 3).status_code, 409)

    def test_database_uniqueness(self):
        self.prepare(); self.submit(self.one, 3)
        with closing(sqlite3.connect(self.path)) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO submissions(question_id,team_id,answer,rank) VALUES(?,?,?,?)', (self.questions[3], 1, 'x', 2))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO submissions(question_id,team_id,answer,rank) VALUES(?,?,?,?)', (self.questions[3], 2, 'x', 1))


if __name__ == '__main__':
    unittest.main()
