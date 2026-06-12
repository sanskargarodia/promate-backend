"""CSV schema validation tests."""

from app.catalog.csv_schema import validate_parts_csv_text

SAMPLE_CSV = """part_id,part_name,part_price,appliance_type,in_stock,brand
PS11752778,Door Shelf Bin,36.08,refrigerator,1,Whirlpool
PS99999999,Dishwasher Rack,12.00,dishwasher,yes,KitchenAid
"""


def test_validate_parts_csv_ok() -> None:
    result = validate_parts_csv_text(SAMPLE_CSV, min_rows=2)
    assert result.ok
    assert result.row_count == 2


def test_validate_parts_csv_missing_column() -> None:
    bad = "part_id,part_name\nPS1,Foo\n"
    result = validate_parts_csv_text(bad)
    assert not result.ok
    assert any("Missing required columns" in err for err in result.errors)
