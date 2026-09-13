from text_utils.text_utils import sort_and_uniq_by_column

def test_visible_functional(tmp_path):
    source = tmp_path / 'records.txt'
    target = tmp_path / 'ordered.txt'
    source.write_text('b 2\na 1\na 1\n')
    sort_and_uniq_by_column(str(source), 1, str(target))
    assert target.read_text().splitlines() == ['a 1', 'b 2']
