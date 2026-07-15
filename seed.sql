INSERT OR IGNORE INTO customers
    (id, district, section, land_number, area, declared_value, rights_scope,
     total_declared_value, owner_name, external_id, address, registration_reason,
     registration_order, note, name)
VALUES
    (1, '信義區', '三興段', '123-1', '35.2', '120000', '全部',
     '4224000', '王小明', 'A123456789', '台北市信義區', '買賣',
     '001', '範例資料', '王小明'),
    (2, '板橋區', '民生段', '88', '18.6', '98000', '1/2',
     '911400', '林美華', 'B223456789', '新北市板橋區', '繼承',
     '002', NULL, '林美華');
