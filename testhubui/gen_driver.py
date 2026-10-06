"""Dev driver: generate all six formats programmatically via generator.generate().
Writes assets under studio* asset names so the hand-written examples are untouched.
Run from testhubui/ with the venv active:  python gen_driver.py
"""
import json, sys
sys.dont_write_bytecode = True
from pathlib import Path
from generator import generate

ROOT = Path(__file__).resolve().parent.parent / 'testhub-api-quality-accelerator'   # the API accelerator
PATHS = {
    'request': str(ROOT / 'src/requestPayload'),
    'spec':    str(ROOT / 'src/tests'),
    'excel':   str(ROOT / 'test-data/excel'),
    'response':str(ROOT / 'test-data/json'),
}

CASES = {
    'json': {
        'assetName': 'studioJson', 'serviceName': 'userJson', 'bodyFormat': 'JSON',
        'method': 'POST', 'endpoint': '/api/users/2', 'expectedStatus': '201',
        'authType': 'apikey', 'requestPayload': '{"name":"John","job":"QA"}',
    },
    'xml': {
        'assetName': 'studioXml', 'serviceName': 'userXml', 'bodyFormat': 'XML',
        'method': 'POST', 'endpoint': '/api/users/2', 'expectedStatus': '201',
        'authType': 'apikey',
        'requestPayload': '<user><name>John</name><job>QA</job></user>',
    },
    'form': {
        'assetName': 'studioForm', 'serviceName': 'userForm', 'bodyFormat': 'form',
        'method': 'POST', 'endpoint': '/api/upload', 'expectedStatus': '201',
        'authType': 'apikey',
        # Mirror formData1's parts: a `doc` file + an `Email` text field, so the
        # Invalid-Email negative can trigger the upload mock's email validation.
        'formFields': {'fields': {'Email': 'jane.doe@example.com'},
                       'files': [{'field': 'doc', 'path': 'test-data/files/agreement.pdf',
                                  'contentType': 'application/pdf'}]},
    },
    'urlencoded': {
        'assetName': 'studioUrlenc', 'serviceName': 'userUrlenc', 'bodyFormat': 'urlencoded',
        # Collection endpoint → Unsupported PUT/PATCH are 404 (matches the sheet).
        'method': 'POST', 'endpoint': '/api/urlencoded', 'expectedStatus': '201',
        'authType': 'apikey',
        'formFields': {'fields': {'name': 'John', 'job': 'QA'}, 'files': []},
    },
    'binary': {
        'assetName': 'studioBinaryGen', 'serviceName': 'userBinary', 'bodyFormat': 'binary',
        # Collection endpoint → Unsupported PUT/PATCH are 404 (matches the sheet).
        'method': 'POST', 'endpoint': '/api/upload', 'expectedStatus': '201',
        'authType': 'apikey', 'requestPayload': 'test-data/files/agreement.pdf',
    },
    'mft': {
        'assetName': 'studioMft', 'serviceName': 'userMft', 'bodyFormat': 'mft',
        'method': 'GET', 'endpoint': '/api/users/2', 'expectedStatus': '201',
        'authType': 'none',
        'mftFields': {'websiteUrl': 'https://httpbin.org/post', 'username': 'demo',
                      'passwordRef': 'MFT_PASSWORD', 'filePath': 'test-data/files/agreement.pdf'},
    },
}

def main():
    only = sys.argv[1:] or list(CASES)
    for fmt in only:
        payload = dict(CASES[fmt])
        payload['paths'] = dict(PATHS)
        try:
            res = generate(payload)
            print(f"[OK]   {fmt:10} rows={res['rows']:>2} sheet={res['sheet']}")
            for f in res['files']:
                print(f"           {f}")
        except Exception as e:
            print(f"[FAIL] {fmt:10} {type(e).__name__}: {e}")

if __name__ == '__main__':
    main()
