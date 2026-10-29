"""Danh mục PT001–PT099 do người dùng cung cấp; giá là dữ liệu minh họa."""

import hashlib

COMPATIBILITY_ACCURACY = ("Các trường hãng/dòng xe/năm/phiên bản/động cơ được ghi theo hướng dẫn "
                          "đối chiếu; không khẳng định phụ tùng nào vừa với xe cụ thể.")
USAGE_REQUIREMENTS = ("Đối chiếu VIN, mã OEM, kích thước, phiên bản, động cơ và catalogue của "
                      "hãng/nhà cung cấp trước khi sử dụng thực tế.")
PRICE_NOTE = "Giá giả lập phục vụ demo hệ thống, không phải báo giá thị trường."
SUPPLIER_NOTE = "Tên nhà cung cấp mẫu, cần thay bằng thông tin nhà cung cấp thực tế."
OUT_OF_STOCK_CODES = {"PT024", "PT071", "PT118", "PT155", "PT189"}


_ITEMS_TEXT = """
PT001|Lọc dầu động cơ|Bảo dưỡng – lọc
PT002|Lọc gió động cơ|Bảo dưỡng – lọc
PT003|Lọc gió điều hòa|Điều hòa – lọc
PT004|Lọc nhiên liệu xăng|Nhiên liệu – lọc
PT005|Lọc nhiên liệu diesel|Nhiên liệu – lọc
PT006|Lọc dầu hộp số tự động|Hộp số – lọc
PT007|Lọc dầu hộp số CVT|Hộp số – lọc
PT008|Lọc dầu trợ lực lái|Hệ thống lái – lọc
PT009|Lọc cặn bình nhiên liệu|Nhiên liệu – lọc
PT010|Lọc hơi dầu PCV|Động cơ – thông hơi
PT011|Ắc quy 12V|Điện – khởi động
PT012|Cọc bình ắc quy|Điện – khởi động
PT013|Dây cáp ắc quy dương|Điện – khởi động
PT014|Dây cáp ắc quy âm|Điện – khởi động
PT015|Máy phát điện|Điện – khởi động
PT016|Bộ điều áp máy phát|Điện – khởi động
PT017|Máy khởi động|Điện – khởi động
PT018|Solenoid máy khởi động|Điện – khởi động
PT019|Cầu chì tổng|Điện – cầu chì
PT020|Hộp cầu chì|Điện – cầu chì
PT021|Rơ-le khởi động|Điện – rơ-le
PT022|Rơ-le quạt làm mát|Điện – rơ-le
PT023|Cuộn đánh lửa|Đánh lửa
PT024|Bugi đánh lửa|Đánh lửa
PT025|Dây cao áp bugi|Đánh lửa
PT026|Cảm biến trục khuỷu|Điện – cảm biến
PT027|Cảm biến trục cam|Điện – cảm biến
PT028|Cảm biến oxy trước|Khí thải – cảm biến
PT029|Cảm biến oxy sau|Khí thải – cảm biến
PT030|Cảm biến lưu lượng khí nạp MAF|Điện – cảm biến
PT031|Cảm biến áp suất đường ống nạp MAP|Điện – cảm biến
PT032|Cảm biến nhiệt độ nước làm mát|Điện – cảm biến
PT033|Cảm biến nhiệt độ khí nạp|Điện – cảm biến
PT034|Cảm biến vị trí bướm ga|Điện – cảm biến
PT035|Cảm biến ABS bánh xe trước|Phanh – cảm biến
PT036|Cảm biến ABS bánh xe sau|Phanh – cảm biến
PT037|Cảm biến áp suất lốp TPMS|Lốp – cảm biến
PT038|Cảm biến lùi|Điện – hỗ trợ đỗ xe
PT039|Mô-đun điều khiển động cơ ECU|Điện – điều khiển
PT040|Công tắc đèn phanh|Điện – công tắc
PT041|Dây curoa phụ|Động cơ – truyền động
PT042|Bộ tăng đai curoa|Động cơ – truyền động
PT043|Puly trục khuỷu|Động cơ – truyền động
PT044|Bộ xích cam|Động cơ – phối khí
PT045|Bộ dây đai cam|Động cơ – phối khí
PT046|Bộ tăng xích cam|Động cơ – phối khí
PT047|Bánh răng trục cam|Động cơ – phối khí
PT048|Trục cam|Động cơ – phối khí
PT049|Trục khuỷu|Động cơ – cơ khí
PT050|Piston động cơ|Động cơ – cơ khí
PT051|Xéc-măng piston|Động cơ – cơ khí
PT052|Thanh truyền|Động cơ – cơ khí
PT053|Bạc biên|Động cơ – cơ khí
PT054|Bạc cổ trục|Động cơ – cơ khí
PT055|Bơm dầu động cơ|Động cơ – bôi trơn
PT056|Cácte dầu động cơ|Động cơ – bôi trơn
PT057|Nắp châm dầu động cơ|Động cơ – bôi trơn
PT058|Que thăm dầu|Động cơ – bôi trơn
PT059|Nắp dàn cò|Động cơ – gioăng/phớt
PT060|Gioăng nắp dàn cò|Động cơ – gioăng/phớt
PT061|Gioăng quy lát|Động cơ – gioăng/phớt
PT062|Phớt trục khuỷu trước|Động cơ – gioăng/phớt
PT063|Phớt trục khuỷu sau|Động cơ – gioăng/phớt
PT064|Gioăng cổ hút|Động cơ – gioăng/phớt
PT065|Gioăng cổ xả|Động cơ – gioăng/phớt
PT066|Chân máy động cơ|Động cơ – chân máy
PT067|Chân hộp số|Hộp số – chân máy
PT068|Van PCV|Động cơ – thông hơi
PT069|Bướm ga điện tử|Động cơ – nạp khí
PT070|Cổ hút khí nạp|Động cơ – nạp khí
PT071|Két nước làm mát|Làm mát
PT072|Nắp két nước|Làm mát
PT073|Bình nước phụ|Làm mát
PT074|Nắp bình nước phụ|Làm mát
PT075|Bơm nước động cơ|Làm mát
PT076|Van hằng nhiệt|Làm mát
PT077|Quạt két nước|Làm mát – điện
PT078|Mô-tơ quạt két nước|Làm mát – điện
PT079|Ống nước trên|Làm mát – ống
PT080|Ống nước dưới|Làm mát – ống
PT081|Ống sưởi cabin|Làm mát – ống
PT082|Cảm biến mức nước làm mát|Làm mát – cảm biến
PT083|Két làm mát dầu động cơ|Làm mát
PT084|Bơm nhiên liệu trong bình|Nhiên liệu
PT085|Kim phun xăng|Nhiên liệu
PT086|Kim phun diesel|Nhiên liệu
PT087|Bơm cao áp diesel|Nhiên liệu
PT088|Van điều áp nhiên liệu|Nhiên liệu
PT089|Thân bướm ga|Nhiên liệu – nạp khí
PT090|Canister than hoạt tính|Khí thải
PT091|Van purge EVAP|Khí thải
PT092|Van EGR|Khí thải
PT093|Bộ xúc tác khí thải|Khí thải
PT094|Cổ góp xả|Khí thải
PT095|Ống xả giữa|Khí thải
PT096|Bầu giảm thanh sau|Khí thải
PT097|Gioăng ống xả|Khí thải
PT098|Bộ ly hợp|Hộp số – ly hợp
PT099|Đĩa ly hợp|Hộp số – ly hợp
PT100|Mâm ép ly hợp|Hộp số – ly hợp
PT101|Bi tê ly hợp|Hộp số – ly hợp
PT102|Xi lanh côn tổng|Hộp số – ly hợp
PT103|Xi lanh côn con|Hộp số – ly hợp
PT104|Cáp số|Hộp số – điều khiển
PT105|Cần chuyển số|Hộp số – điều khiển
PT106|Cảm biến tốc độ hộp số|Hộp số – cảm biến
PT107|Solenoid hộp số tự động|Hộp số – điều khiển
PT108|Các-te hộp số|Hộp số – vỏ
PT109|Trục láp trái|Truyền động
PT110|Trục láp phải|Truyền động
PT111|Chụp bụi láp ngoài|Truyền động
PT112|Chụp bụi láp trong|Truyền động
PT113|Khớp đồng tốc ngoài|Truyền động
PT114|Khớp các-đăng|Truyền động
PT115|Gối đỡ trục các-đăng|Truyền động
PT116|Cao su chân vi sai|Truyền động
PT117|Dầu hộp số tự động|Dầu – dung dịch
PT118|Má phanh trước|Phanh
PT119|Má phanh sau|Phanh
PT120|Đĩa phanh trước|Phanh
PT121|Đĩa phanh sau|Phanh
PT122|Tang trống phanh sau|Phanh
PT123|Guốc phanh sau|Phanh
PT124|Cùm phanh trước|Phanh
PT125|Cùm phanh sau|Phanh
PT126|Piston cùm phanh|Phanh
PT127|Xi lanh phanh chính|Phanh
PT128|Bầu trợ lực phanh|Phanh
PT129|Ống dầu phanh mềm trước|Phanh – ống
PT130|Ống dầu phanh mềm sau|Phanh – ống
PT131|Dầu phanh DOT|Dầu – dung dịch
PT132|Cáp phanh tay|Phanh
PT133|Mô-tơ phanh tay điện tử|Phanh – điện
PT134|Cảm biến độ mòn má phanh|Phanh – cảm biến
PT135|Giảm xóc trước|Hệ thống treo
PT136|Giảm xóc sau|Hệ thống treo
PT137|Lò xo giảm xóc trước|Hệ thống treo
PT138|Lò xo giảm xóc sau|Hệ thống treo
PT139|Càng A trước|Hệ thống treo
PT140|Cao su càng A|Hệ thống treo
PT141|Rotuyn trụ đứng|Hệ thống treo
PT142|Rotuyn lái trong|Hệ thống lái
PT143|Rotuyn lái ngoài|Hệ thống lái
PT144|Thước lái|Hệ thống lái
PT145|Bơm trợ lực lái|Hệ thống lái
PT146|Dây curoa trợ lực lái|Hệ thống lái
PT147|Bạc đạn bánh trước|Bánh xe – ổ bi
PT148|Bạc đạn bánh sau|Bánh xe – ổ bi
PT149|Moay-ơ bánh trước|Bánh xe
PT150|Moay-ơ bánh sau|Bánh xe
PT151|Thanh cân bằng|Hệ thống treo
PT152|Cao su thanh cân bằng|Hệ thống treo
PT153|Thanh giằng cân bằng|Hệ thống treo
PT154|Cao su chân giảm xóc|Hệ thống treo
PT155|Lốp xe ô tô|Lốp – bánh xe
PT156|Mâm hợp kim|Lốp – bánh xe
PT157|Bu-lông bánh xe|Lốp – bánh xe
PT158|Đai ốc bánh xe|Lốp – bánh xe
PT159|Van lốp|Lốp – bánh xe
PT160|Cảm biến áp suất lốp|Lốp – cảm biến
PT161|Nắp capo|Thân vỏ
PT162|Bản lề nắp capo|Thân vỏ
PT163|Khóa nắp capo|Thân vỏ
PT164|Dây mở nắp capo|Thân vỏ
PT165|Cản trước|Thân vỏ
PT166|Cản sau|Thân vỏ
PT167|Lưới tản nhiệt|Thân vỏ
PT168|Tai xe trước trái|Thân vỏ
PT169|Tai xe trước phải|Thân vỏ
PT170|Cửa trước trái|Thân vỏ
PT171|Cửa trước phải|Thân vỏ
PT172|Cửa sau trái|Thân vỏ
PT173|Cửa sau phải|Thân vỏ
PT174|Cốp sau / nắp khoang hành lý|Thân vỏ
PT175|Bản lề cửa|Thân vỏ
PT176|Tay nắm cửa ngoài|Thân vỏ
PT177|Gương chiếu hậu trái|Thân vỏ – gương
PT178|Gương chiếu hậu phải|Thân vỏ – gương
PT179|Kính chắn gió trước|Kính xe
PT180|Kính hậu|Kính xe
PT181|Kính cửa trước|Kính xe
PT182|Kính cửa sau|Kính xe
PT183|Gioăng cửa|Thân vỏ – gioăng
PT184|Chắn bùn trước|Thân vỏ
PT185|Chắn bùn sau|Thân vỏ
PT186|Ốp hốc bánh xe|Thân vỏ
PT187|Tấm chắn gầm động cơ|Thân vỏ
PT188|Ty chống capo|Thân vỏ
PT189|Cụm đèn pha trái|Chiếu sáng
PT190|Cụm đèn pha phải|Chiếu sáng
PT191|Đèn hậu trái|Chiếu sáng
PT192|Đèn hậu phải|Chiếu sáng
PT193|Đèn sương mù|Chiếu sáng
PT194|Bóng đèn pha|Chiếu sáng
PT195|Đèn xi-nhan gương|Chiếu sáng
PT196|Mô-tơ gạt mưa|Gạt mưa
PT197|Cần gạt mưa trước|Gạt mưa
PT198|Cần gạt mưa sau|Gạt mưa
PT199|Bơm nước rửa kính|Gạt mưa
PT200|Bình nước rửa kính|Gạt mưa
""".strip()

_PRICES_TEXT = """
90000|110000
170000|200000
210000|250000
130000|170000
980000|1220000
400000|490000
520000|700000
690000|860000
1060000|1380000
830000|1120000
720000|900000
740000|960000
2520000|3400000
260000|350000
330000|430000
1470000|1980000
590000|700000
1320000|1650000
120000|160000
210000|280000
280000|380000
60000|80000
480000|570000
370000|460000
100000|120000
930000|1100000
1590000|2150000
770000|960000
660000|810000
1370000|1710000
320000|380000
550000|650000
210000|250000
1080000|1270000
240000|290000
660000|820000
1190000|1610000
1020000|1330000
550000|720000
350000|430000
230000|300000
780000|1010000
350000|460000
4060000|5080000
540000|640000
3800000|5130000
3440000|4300000
3070000|3990000
2990000|3530000
1790000|2240000
1930000|2610000
930000|1260000
1030000|1290000
2240000|2800000
600000|750000
1200000|1420000
890000|1160000
1110000|1440000
740000|960000
700000|950000
1790000|2420000
1270000|1500000
910000|1180000
890000|1200000
1040000|1350000
1270000|1590000
1000000|1220000
1410000|1830000
800000|940000
150000|200000
1210000|1510000
2150000|2540000
1570000|1960000
200000|240000
2490000|2940000
1990000|2430000
500000|610000
1210000|1510000
580000|720000
700000|880000
560000|730000
1150000|1550000
2200000|2750000
3070000|3750000
280000|330000
2220000|2620000
2750000|3440000
2920000|3940000
840000|1020000
430000|540000
6770000|8460000
6820000|8050000
4840000|6050000
770000|940000
1060000|1430000
7420000|10020000
6330000|7470000
4490000|5610000
3340000|4180000
2690000|3500000
2830000|3540000
6420000|7830000
2430000|3040000
860000|1010000
650000|790000
1430000|1930000
1040000|1300000
730000|890000
2190000|2670000
2510000|3390000
2760000|3260000
1610000|2010000
2090000|2470000
2190000|2960000
1200000|1500000
320000|420000
310000|370000
1390000|1740000
3380000|4560000
230000|280000
2990000|3890000
840000|1130000
3120000|4210000
2460000|3000000
2240000|2910000
520000|650000
2170000|2930000
930000|1160000
440000|520000
150000|200000
520000|630000
2000000|2360000
750000|980000
740000|1000000
1810000|2440000
1390000|1640000
430000|520000
2270000|3060000
1470000|1910000
2620000|3090000
1430000|1790000
2400000|2830000
3560000|4810000
4200000|4960000
370000|440000
7430000|9060000
1450000|1710000
1680000|2050000
2440000|3170000
2330000|2840000
430000|510000
250000|300000
2700000|3190000
2020000|2630000
4390000|5180000
2100000|2620000
1790000|2180000
4180000|4930000
1670000|2170000
740000|870000
1910000|2580000
5200000|7020000
350000|470000
3130000|3910000
6150000|8000000
7460000|9100000
5560000|7230000
8570000|10460000
2400000|3120000
4210000|4970000
4730000|5580000
3570000|4360000
5750000|6780000
5580000|6580000
6940000|8470000
3760000|4700000
1170000|1580000
2180000|2940000
1240000|1610000
3730000|4850000
5000000|6100000
5420000|6610000
410000|530000
6830000|8540000
6630000|8090000
1690000|2280000
7050000|8600000
5290000|7140000
1040000|1400000
4110000|5340000
1460000|1970000
190000|250000
5760000|7030000
2750000|3240000
1430000|1690000
470000|610000
510000|620000
90000|120000
670000|790000
260000|350000
""".strip()


def _unit(name: str) -> str:
    if name.startswith(("Bộ ", "Hộp ")):
        return "bộ"
    if name.startswith(("Dây ", "Ống ", "Cáp ")):
        return "sợi"
    if name.startswith("Dầu "):
        return "chai"
    if "ắc quy" in name.casefold():
        return "bình"
    return "cái"


def _stable_number(code: str, low: int, high: int, salt: str) -> int:
    value = int(hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()[:8], 16)
    return low + value % (high - low + 1)


def inventory_rows():
    items = [line.split("|") for line in _ITEMS_TEXT.splitlines()]
    prices = [tuple(map(int, line.split("|"))) for line in _PRICES_TEXT.splitlines()]
    if len(items) != 200 or len(prices) != 200:
        raise ValueError("Danh mục PT phải có đúng 200 tên và 200 cặp giá")
    suppliers = "ABCDE"
    for index, ((code, name, category), (cost, sell)) in enumerate(zip(items, prices), start=1):
        stock = 0 if code in OUT_OF_STOCK_CODES else _stable_number(code, 5, 30, "stock")
        minimum = _stable_number(code, 2, 6, "minimum")
        compatible = (f"Nhóm {category}; cần đối chiếu VIN, hãng, dòng xe, đời xe, "
                      "phiên bản, động cơ và mã linh kiện trước khi lắp")
        yield (code, name, category, compatible, _unit(name), cost, sell, stock,
               minimum, f"Nhà cung cấp mẫu {suppliers[index % 5]}",
               COMPATIBILITY_ACCURACY, USAGE_REQUIREMENTS, PRICE_NOTE, SUPPLIER_NOTE)


def upsert_pt_inventory(db) -> tuple[int, int]:
    """Thêm mã mới và cập nhật dữ liệu minh họa của đúng dải PT001–PT200."""
    inserted = updated = 0
    for row in inventory_rows():
        existing = db.execute("SELECT id FROM parts WHERE code=?", (row[0],)).fetchone()
        if existing:
            db.execute("""UPDATE parts SET name=?,category=?,compatible=?,unit=?,cost_price=?,
                sell_price=?,stock=?,min_stock=?,supplier=?,compatibility_accuracy=?,
                usage_requirements=?,price_note=?,supplier_note=?,active=1 WHERE code=?""",
                (*row[1:], row[0]))
            updated += 1
        else:
            db.execute("""INSERT INTO parts(code,name,category,compatible,unit,cost_price,
                sell_price,stock,min_stock,supplier,compatibility_accuracy,usage_requirements,
                price_note,supplier_note,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""", row)
            inserted += 1
    return inserted, updated


if __name__ == "__main__":
    from .database import connect, transaction
    with connect() as db, transaction(db):
        added, changed = upsert_pt_inventory(db)
    print(f"PT inventory: {added} inserted, {changed} updated")
