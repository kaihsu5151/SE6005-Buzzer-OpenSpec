import copy
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import create_app
from sheets import GoogleSheets, SheetsError, scan, spreadsheet_id


def document(cells, merges=None):
    rows = []
    for r in range(max((x[0] for x in cells), default=0) + 1):
        row = []
        for c in range(max((x[1] for x in cells), default=0) + 1):
            value = cells.get((r, c))
            row.append({'userEnteredValue': {'stringValue': value}} if value is not None else {})
        rows.append({'values': row})
    return {'sheets': [{'properties': {'sheetId': 17, 'sheetType': 'GRID'}, 'merges': merges or [], 'data': [{'rowData': rows}]}]}


class FakeSheets:
    def __init__(self, doc):
        self.doc = doc
        self.writes = []
        self.read_error = None
        self.write_error = None
    def read(self, sid):
        if self.read_error: raise SheetsError(self.read_error)
        return copy.deepcopy(self.doc)
    def write(self, sid, writes):
        if self.write_error: raise SheetsError(self.write_error)
        self.writes.append((sid, copy.deepcopy(writes)))


class ScanTests(unittest.TestCase):
    def test_dynamic_positions_and_numbers(self):
        items = scan(document({(1, 8): '{{Q12}}', (8, 2): '{{Q3}}'}))
        self.assertEqual([(x['number'], x['row'], x['col']) for x in items], [(3, 8, 2), (12, 1, 8)])
        self.assertEqual(len(scan(document({(4, 5): '{{Q98}}'}))), 1)

    def test_duplicate_missing_invalid(self):
        for cells in ({}, {(0, 0): '{{Q1}}', (1, 0): '{{Q1}}'}, {(0, 0): '{{Q0}}'}, {(0, 0): '答案 {{Q1}}'}, {(0, 0): '{{Qx}}'}, {(0, 0): '{{Q' + '9' * 5000 + '}}'}):
            with self.subTest(cells=cells), self.assertRaises(SheetsError): scan(document(cells))

    def test_merged_cells(self):
        merge = {'startRowIndex': 2, 'endRowIndex': 3, 'startColumnIndex': 4, 'endColumnIndex': 6}
        self.assertEqual(scan(document({(2, 4): '{{Q1}}'}, [merge]))[0]['merge'], [2, 3, 4, 6])
        with self.assertRaises(SheetsError): scan(document({(2, 5): '{{Q1}}'}, [merge]))

    def test_url_validation(self):
        self.assertEqual(spreadsheet_id('https://docs.google.com/spreadsheets/d/abc-123/edit#gid=0'), 'abc-123')
        for value in ['https://evil.example/spreadsheets/d/x', 'https://docs.google.com.evil.example/spreadsheets/d/x', '']:
            with self.assertRaises(SheetsError): spreadsheet_id(value)

    def test_google_gateway_auth_and_network_errors(self):
        with patch('google.auth.default', side_effect=Exception('secret')):
            with self.assertRaisesRegex(SheetsError, '憑證'): GoogleSheets()
        g = GoogleSheets.__new__(GoogleSheets)
        g.session = Mock()
        g.session.get.side_effect = OSError('secret')
        with self.assertRaisesRegex(SheetsError, '讀取失敗'): g.read('id')
        g.session.post.side_effect = OSError('secret')
        with self.assertRaisesRegex(SheetsError, '結果不明'): g.write('id', [{'sheet_id':1,'row':0,'col':0,'answer':'x'}])

    def test_google_gateway_write_string_value(self):
        g = GoogleSheets.__new__(GoogleSheets); g.session = Mock()
        g.write('id', [{'sheet_id':17,'row':2,'col':7,'answer':'=1+1'}])
        request = g.session.post.call_args.kwargs['json']['requests'][0]['updateCells']
        self.assertEqual(request['rows'][0]['values'][0]['userEnteredValue'], {'stringValue':'=1+1'})
        self.assertEqual(request['start'], {'sheetId':17,'rowIndex':2,'columnIndex':7})


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeSheets(document({(1, 3): '{{Q4}}', (5, 7): '{{Q9}}', (6, 3): '保持內容'}))
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'test-only', 'DATABASE':os.path.join(self.tmp.name,'db'), 'SHEETS_FACTORY':lambda:self.fake})
        self.teacher = self.app.test_client(); self.student = self.app.test_client()
        self.teacher.post('/api/join', json={'role':'teacher'})
        self.student.post('/api/join', json={'role':'student','team':1})
    def tearDown(self): self.tmp.cleanup()
    def imp(self): return self.teacher.post('/api/sheets/import', json={'spreadsheet':'test_id','confirmed_single_questions':True})
    def start_end(self, answer=True):
        self.assertEqual(self.imp().status_code, 200)
        q = self.teacher.get('/api/state').json['questions'][0]['id']
        self.teacher.post('/api/activity/start', json={})
        if answer: self.student.post('/api/answer', json={'question_id':q,'answer':'=答案'})
        self.teacher.post('/api/activity/end', json={})

    def test_import_permission_and_atomic_failure(self):
        self.assertEqual(self.teacher.post('/api/sheets/import', json={'spreadsheet':'test_id'}).status_code, 400)
        self.assertEqual(self.student.post('/api/sheets/import', json={'spreadsheet':'test_id'}).status_code, 403)
        self.assertEqual(self.imp().json['numbers'], [4,9])
        self.fake.doc = document({(0,0):'{{Q1}}',(1,0):'{{Q1}}'})
        self.assertEqual(self.imp().status_code, 400)
        self.assertEqual([q['number'] for q in self.teacher.get('/api/state').json['questions']], [4,9])

    def test_write_winner_and_preserve_unanswered(self):
        self.start_end()
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).json['count'], 1)
        writes = self.fake.writes[0][1]
        self.assertEqual([(x['number'], x['row'], x['col'], x['answer']) for x in writes], [(4,1,3,'=答案')])
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).status_code, 409)
        self.assertEqual(self.student.post('/api/sheets/export',json={}).status_code, 403)

    def test_changed_markers_and_merge_abort(self):
        self.start_end()
        self.fake.doc = document({(2,3):'{{Q4}}',(5,7):'{{Q9}}'})
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).status_code, 400)
        self.assertEqual(self.fake.writes, [])

    def test_changed_merge_abort(self):
        self.start_end()
        self.fake.doc['sheets'][0]['merges'] = [{'startRowIndex':1,'endRowIndex':2,'startColumnIndex':3,'endColumnIndex':5}]
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).status_code, 400)
        self.assertEqual(self.fake.writes, [])

    def test_network_and_uncertain_write(self):
        self.fake.read_error = '無法讀取'
        self.assertEqual(self.imp().status_code, 400)
        self.assertEqual(self.teacher.get('/api/state').json['questions'], [])
        self.fake.read_error = None; self.start_end()
        self.fake.write_error = '結果不明'
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).status_code, 400)
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).status_code, 409)

    def test_no_answers_produces_no_writes(self):
        self.start_end(answer=False)
        self.assertEqual(self.teacher.post('/api/sheets/export',json={}).json['count'], 0)
        self.assertEqual(self.fake.writes[0][1], [])


if __name__ == '__main__': unittest.main()
