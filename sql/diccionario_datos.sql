SELECT 
    c.table_name AS tabla,
    c.column_name AS columna,
    c.data_type AS tipo,
    c.is_nullable AS permite_null,
    c.column_default AS valor_por_defecto,
    tc.constraint_type AS tipo_clave,
    ccu.table_name AS tabla_referenciada,
    ccu.column_name AS columna_referenciada
FROM information_schema.columns c
LEFT JOIN information_schema.key_column_usage kcu
    ON c.table_name = kcu.table_name
    AND c.column_name = kcu.column_name
    AND c.table_schema = kcu.table_schema
LEFT JOIN information_schema.table_constraints tc
    ON kcu.constraint_name = tc.constraint_name
    AND kcu.table_schema = tc.table_schema
LEFT JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
    AND tc.table_schema = ccu.table_schema
WHERE c.table_schema = 'petalops'
ORDER BY c.table_name, c.ordinal_position;