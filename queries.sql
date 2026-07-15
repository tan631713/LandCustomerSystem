-- 查詢全部土地資料
SELECT district AS 區,
       section AS 段,
       land_number AS 地號,
       area AS 面積,
       declared_value AS 公告現值,
       rights_scope AS 權利範圍,
       total_declared_value AS 總計公告現值,
       owner_name AS 所有權人,
       external_id AS ID,
       address AS 地址,
       registration_reason AS 登記原因,
       registration_order AS 登記次序,
       note AS 備註
FROM customers
ORDER BY id DESC;
-- 用關鍵字搜尋土地資料
SELECT district AS 區,
       section AS 段,
       land_number AS 地號,
       owner_name AS 所有權人,
       external_id AS ID,
       address AS 地址
FROM customers
WHERE district LIKE '%' || :keyword || '%'
   OR section LIKE '%' || :keyword || '%'
   OR land_number LIKE '%' || :keyword || '%'
   OR owner_name LIKE '%' || :keyword || '%'
   OR external_id LIKE '%' || :keyword || '%'
   OR address LIKE '%' || :keyword || '%'
ORDER BY id DESC;
