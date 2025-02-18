import json
from gallery import util

def test_read_metadata(tmp_path):
    path = tmp_path / 'test'
    json_path = tmp_path / 'test.meta.json'
    src = {
        'title': 'foo',
        'fancy': [1, 2, 3],
    }
    with json_path.open('w') as f:
        json.dump(src, f)
    ret = util.read_metadata(path)

    for k in src:
        assert src[k] == ret[k]


def test_write_metadata(tmp_path):
    path = tmp_path / 'test'
    json_path = tmp_path / 'test.meta.json'
    src = {
        'title': 'foo',
        'fancy': [1, 2, 3],
    }
    util.write_metadata(path, src)
    with json_path.open() as f:
        ret = json.load(f)

    for k in src:
        assert src[k] == ret[k]
