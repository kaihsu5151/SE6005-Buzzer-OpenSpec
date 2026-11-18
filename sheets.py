"""Google Sheets integration; all remote access is through an injectable gateway."""
import re
from urllib.parse import urlparse

MARKER = re.compile(r'\{\{Q([1-9][0-9]*)\}\}')
ID = re.compile(r'[A-Za-z0-9_-]+')


class SheetsError(Exception):
    pass


def spreadsheet_id(value):
    if not isinstance(value, str):
        raise SheetsError('請輸入試算表網址或 ID')
    value = value.strip()
    if ID.fullmatch(value):
        return value
    url = urlparse(value)
    match = re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)(?:/.*)?', url.path)
    if url.scheme == 'https' and url.hostname == 'docs.google.com' and match:
        return match.group(1)
    raise SheetsError('試算表網址或 ID 格式不正確')


def scan(document):
    found = {}
    for sheet in document.get('sheets', []):
        props = sheet.get('properties', {})
        if props.get('sheetType', 'GRID') != 'GRID':
            raise SheetsError('不支援非一般工作表')
        sid = props['sheetId']
        merges = sheet.get('merges', [])
        for grid in sheet.get('data', []):
            start_r, start_c = grid.get('startRow', 0), grid.get('startColumn', 0)
            for ri, row in enumerate(grid.get('rowData', [])):
                for ci, cell in enumerate(row.get('values', [])):
                    val = cell.get('userEnteredValue', {})
                    text = val.get('stringValue', '')
                    if not isinstance(text, str):
                        continue
                    if '{{' not in text and '}}' not in text:
                        continue
                    match = MARKER.fullmatch(text)
                    if not match:
                        raise SheetsError('發現無效標記，請使用完整格式 {{Q正整數}}')
                    digits = match.group(1)
                    if len(digits) > 10:
                        raise SheetsError('題號超出範圍')
                    number = int(digits)
                    if number > 2147483647 or number in found:
                        raise SheetsError('題號重複或超出範圍')
                    row_i, col_i = start_r + ri, start_c + ci
                    merged = None
                    for merge in merges:
                        if merge.get('startRowIndex', 0) <= row_i < merge['endRowIndex'] and merge.get('startColumnIndex', 0) <= col_i < merge['endColumnIndex']:
                            if (row_i, col_i) != (merge.get('startRowIndex', 0), merge.get('startColumnIndex', 0)):
                                raise SheetsError('合併儲存格標記必須位於左上角')
                            merged = [merge.get('startRowIndex', 0), merge['endRowIndex'], merge.get('startColumnIndex', 0), merge['endColumnIndex']]
                    found[number] = {'number': number, 'sheet_id': sid, 'row': row_i, 'col': col_i, 'marker': text, 'merge': merged}
    if not found:
        raise SheetsError('沒有題目標記；請先逐題準備並核對題數')
    return sorted(found.values(), key=lambda x: x['number'])


class GoogleSheets:
    def __init__(self):
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/spreadsheets'])
            self.session = AuthorizedSession(credentials)
        except Exception as exc:
            raise SheetsError('無法載入 Google 憑證，請檢查外部憑證設定') from exc

    def read(self, sid):
        try:
            response = self.session.get('https://sheets.googleapis.com/v4/spreadsheets/' + sid, params={'includeGridData': 'true'}, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise SheetsError('讀取失敗：請檢查網路、試算表 ID 與讀取權限') from exc

    def write(self, sid, writes):
        requests = [{'updateCells': {'start': {'sheetId': x['sheet_id'], 'rowIndex': x['row'], 'columnIndex': x['col']}, 'rows': [{'values': [{'userEnteredValue': {'stringValue': x['answer']}}]}], 'fields': 'userEnteredValue'}} for x in writes]
        if not requests:
            return
        try:
            response = self.session.post('https://sheets.googleapis.com/v4/spreadsheets/' + sid + ':batchUpdate', json={'requests': requests}, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            raise SheetsError('寫入失敗或結果不明；請先檢查原試算表，勿盲目重試') from exc
